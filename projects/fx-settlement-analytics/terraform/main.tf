terraform {
  required_version = ">= 1.8, < 2.0"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "= 4.81.0"
    }
  }
}

provider "azurerm" {
  features {}
  subscription_id                 = var.subscription_id
  storage_use_azuread             = true
  resource_provider_registrations = "none"
}

variable "subscription_id" {
  type = string
}
variable "resource_group_name" {
  type    = string
  default = "rg-fx-warehouse-dev"
}
variable "operator_object_id" {
  type = string
}

data "azurerm_resource_group" "fx" {
  name = var.resource_group_name
}

resource "azurerm_storage_account" "fx" {
  name                            = "stfx${substr(sha256(var.subscription_id), 0, 12)}"
  resource_group_name             = data.azurerm_resource_group.fx.name
  location                        = data.azurerm_resource_group.fx.location
  account_tier                    = "Standard"
  account_replication_type        = "LRS"
  min_tls_version                 = "TLS1_2"
  shared_access_key_enabled       = false
  default_to_oauth_authentication = true
  allow_nested_items_to_be_public = false
  tags = {
    project     = "fx-settlement-analytics"
    environment = "dev"
  }
}

resource "azurerm_storage_container" "data" {
  name                  = "fx-data"
  storage_account_id    = azurerm_storage_account.fx.id
  container_access_type = "private"
}

resource "azurerm_role_assignment" "operator_data" {
  scope                = "${azurerm_storage_account.fx.id}/blobServices/default/containers/${azurerm_storage_container.data.name}"
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = var.operator_object_id
  principal_type       = "User"
}

output "storage_account_url" {
  value = azurerm_storage_account.fx.primary_blob_endpoint
}
output "storage_container" {
  value = azurerm_storage_container.data.name
}
