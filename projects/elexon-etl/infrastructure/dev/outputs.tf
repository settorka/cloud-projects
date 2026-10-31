output "storage_account_name" { value = azurerm_storage_account.data.name }
output "registry_name" { value = azurerm_container_registry.images.name }
output "registry_login_server" { value = azurerm_container_registry.images.login_server }
output "job_name" { value = try(azurerm_container_app_job.pipeline[0].name, null) }
output "resource_group_name" { value = azurerm_resource_group.project.name }
