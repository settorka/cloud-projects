terraform {
  required_version = ">= 1.10, < 2.0"
  required_providers {
    azurerm = { source = "hashicorp/azurerm", version = "~> 4.0" }
  }
}

variable "subscription_id" {
  type = string
}

variable "alert_email" { type = string }
variable "budget_start_date" {
  type        = string
  description = "First day of deployment month: YYYY-MM-01T00:00:00Z."
}

variable "state_account_name" {
  type        = string
  description = "Globally unique lowercase alphanumeric name, 3–24 characters."
  validation {
    condition     = can(regex("^[a-z0-9]{3,24}$", var.state_account_name))
    error_message = "Use 3–24 lowercase letters/digits."
  }
}

provider "azurerm" {
  features {}
  subscription_id                 = var.subscription_id
  storage_use_azuread             = true
  resource_provider_registrations = "none"
}

data "azurerm_client_config" "operator" {}

# Establish notifications before creating even state storage. A rejected budget
# blocks chargeable resources, rather than leaving them running without a budget.
resource "azurerm_consumption_budget_subscription" "monthly" {
  name            = "elexon-subscription-monthly"
  subscription_id = "/subscriptions/${var.subscription_id}"
  amount          = 50
  time_grain      = "Monthly"
  time_period { start_date = var.budget_start_date }
  dynamic "notification" {
    for_each = [50, 80, 100]
    content {
      enabled        = true
      threshold      = notification.value
      operator       = "GreaterThanOrEqualTo"
      threshold_type = "Actual"
      contact_emails = [var.alert_email]
    }
  }
}

resource "azurerm_resource_group" "state" {
  name     = "rg-elexon-tfstate"
  location = "uksouth"
  tags     = { Project = "elexon-etl", ManagedBy = "terraform" }
  lifecycle { prevent_destroy = true }
  depends_on = [azurerm_consumption_budget_subscription.monthly]
}

resource "azurerm_storage_account" "state" {
  name                            = var.state_account_name
  resource_group_name             = azurerm_resource_group.state.name
  location                        = azurerm_resource_group.state.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  shared_access_key_enabled       = false
  allow_nested_items_to_be_public = false
  blob_properties {
    versioning_enabled = true
    delete_retention_policy { days = 7 }
    container_delete_retention_policy { days = 7 }
  }
  lifecycle { prevent_destroy = true }
}

resource "azurerm_role_assignment" "operator_state" {
  scope                = azurerm_storage_account.state.id
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = data.azurerm_client_config.operator.object_id
}

resource "azurerm_storage_container" "state" {
  name                  = "tfstate"
  storage_account_id    = azurerm_storage_account.state.id
  container_access_type = "private"
  depends_on            = [azurerm_role_assignment.operator_state]
}

output "storage_account_name" { value = azurerm_storage_account.state.name }
