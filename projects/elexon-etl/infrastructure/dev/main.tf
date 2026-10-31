locals {
  tags = { Project = "elexon-etl", Environment = "dev", ManagedBy = "terraform" }
}

# This resource group already exists: import it before the first application apply.
resource "azurerm_resource_group" "project" {
  name     = "rg-elexon-etl-dev"
  location = "uksouth"
  tags     = local.tags
  lifecycle { prevent_destroy = true }
}

resource "azurerm_storage_account" "data" {
  name                            = var.storage_account_name
  resource_group_name             = azurerm_resource_group.project.name
  location                        = azurerm_resource_group.project.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  shared_access_key_enabled       = false
  allow_nested_items_to_be_public = false
  tags                            = local.tags
  blob_properties {
    delete_retention_policy { days = 7 }
    container_delete_retention_policy { days = 7 }
  }
  lifecycle { prevent_destroy = true }
}

data "azurerm_client_config" "deployer" {}

resource "azurerm_role_assignment" "deployer_blob" {
  scope                = azurerm_storage_account.data.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = data.azurerm_client_config.deployer.object_id
}

resource "azurerm_role_assignment" "operator_blob" {
  count                = var.operator_object_id == data.azurerm_client_config.deployer.object_id ? 0 : 1
  scope                = azurerm_storage_account.data.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = var.operator_object_id
}

resource "azurerm_storage_container" "data" {
  for_each              = toset(["raw", "curated", "metadata"])
  name                  = each.value
  storage_account_id    = azurerm_storage_account.data.id
  container_access_type = "private"
  depends_on            = [azurerm_role_assignment.deployer_blob]
}

resource "azurerm_container_registry" "images" {
  name                = var.registry_name
  resource_group_name = azurerm_resource_group.project.name
  location            = azurerm_resource_group.project.location
  sku                 = "Basic"
  admin_enabled       = false
  tags                = local.tags
}

resource "azurerm_role_assignment" "operator_push" {
  scope                = azurerm_container_registry.images.id
  role_definition_name = "AcrPush"
  principal_id         = var.operator_object_id
}

resource "azurerm_user_assigned_identity" "pipeline" {
  name                = "id-elexon-etl-dev"
  resource_group_name = azurerm_resource_group.project.name
  location            = azurerm_resource_group.project.location
  tags                = local.tags
}

resource "azurerm_role_assignment" "pull" {
  scope                = azurerm_container_registry.images.id
  role_definition_name = "AcrPull"
  principal_id         = azurerm_user_assigned_identity.pipeline.principal_id
}

resource "azurerm_role_assignment" "pipeline_blob" {
  for_each             = toset(["raw", "curated", "metadata"])
  scope                = "${azurerm_storage_account.data.id}/blobServices/default/containers/${each.key}"
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_user_assigned_identity.pipeline.principal_id
  depends_on           = [azurerm_storage_container.data]
}

resource "azurerm_log_analytics_workspace" "logs" {
  name                = "log-elexon-etl-dev"
  resource_group_name = azurerm_resource_group.project.name
  location            = azurerm_resource_group.project.location
  sku                 = "PerGB2018"
  retention_in_days   = 30
  daily_quota_gb      = 0.1
  tags                = local.tags
}

resource "azurerm_container_app_environment" "pipeline" {
  name                       = "cae-elexon-etl-dev"
  resource_group_name        = azurerm_resource_group.project.name
  location                   = azurerm_resource_group.project.location
  log_analytics_workspace_id = azurerm_log_analytics_workspace.logs.id
  workload_profile {
    name                  = "Consumption"
    workload_profile_type = "Consumption"
    minimum_count         = 0
    maximum_count         = 0
  }
  tags = local.tags
}

resource "azurerm_container_app_job" "pipeline" {
  count                        = var.image_digest == null ? 0 : 1
  name                         = "job-elexon-etl-dev"
  resource_group_name          = azurerm_resource_group.project.name
  location                     = azurerm_resource_group.project.location
  container_app_environment_id = azurerm_container_app_environment.pipeline.id
  workload_profile_name        = "Consumption"
  replica_timeout_in_seconds   = 1800
  replica_retry_limit          = 0
  identity {
    type         = "UserAssigned"
    identity_ids = [azurerm_user_assigned_identity.pipeline.id]
  }
  registry {
    server   = azurerm_container_registry.images.login_server
    identity = azurerm_user_assigned_identity.pipeline.id
  }
  dynamic "manual_trigger_config" {
    for_each = var.schedule_cron == null ? [1] : []
    content {
      parallelism              = 1
      replica_completion_count = 1
    }
  }
  dynamic "schedule_trigger_config" {
    for_each = var.schedule_cron == null ? [] : [var.schedule_cron]
    content {
      cron_expression          = schedule_trigger_config.value
      parallelism              = 1
      replica_completion_count = 1
    }
  }
  template {
    container {
      name   = "pipeline"
      image  = "${azurerm_container_registry.images.login_server}/elexon-etl@${var.image_digest}"
      cpu    = 1
      memory = "2Gi"
      args = concat(
        [var.schedule_cron == null ? "run" : "daily", "--dataset", var.dataset, "--storage", "azure"],
        var.schedule_cron != null ? ["--lookback-days", tostring(var.lookback_days)] : (var.source_date == null ? [] : ["--date", var.source_date])
      )
      env {
        name  = "AZURE_STORAGE_ACCOUNT"
        value = azurerm_storage_account.data.name
      }
      env {
        name  = "AZURE_CLIENT_ID"
        value = azurerm_user_assigned_identity.pipeline.client_id
      }
      env {
        name  = "PIPELINE_IMAGE_DIGEST"
        value = var.image_digest
      }
    }
  }
  tags       = local.tags
  depends_on = [azurerm_role_assignment.pull, azurerm_role_assignment.pipeline_blob]
}
