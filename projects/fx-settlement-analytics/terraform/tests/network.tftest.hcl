mock_provider "azurerm" {
  mock_data "azurerm_resource_group" {
    defaults = {
      name     = "rg-fx-warehouse-dev"
      location = "uksouth"
    }
  }
}
variables {
  enable_bastion      = false
  allowed_client_cidr = null
  subscription_id     = "00000000-0000-0000-0000-000000000001"
  operator_object_id  = "00000000-0000-0000-0000-000000000002"
  enable_windows      = true
  admin_password      = "Test-only!Password93817"
}
run "closed_by_default" {
  command = plan
  assert {
    condition     = length(azurerm_network_security_group.fx[0].security_rule) == 1
    error_message = "VM must have only the explicit deny rule without an operator CIDR."
  }
  assert {
    condition     = azurerm_dev_test_global_vm_shutdown_schedule.fx[0].enabled
    error_message = "Development compute requires automatic shutdown."
  }
  assert {
    condition     = !azurerm_storage_account.fx.shared_access_key_enabled && !azurerm_storage_account.fx.allow_nested_items_to_be_public
    error_message = "Shared keys and anonymous Blob access must stay disabled."
  }
}
run "reject_unrestricted_access" {
  command = plan
  variables {
    allowed_client_cidr = "0.0.0.0/0"
  }
  expect_failures = [var.allowed_client_cidr]
}
run "operator_ports_only" {
  command = plan
  variables {
    allowed_client_cidr = "192.0.2.1/32"
  }
  assert {
    condition = alltrue([
      for rule in azurerm_network_security_group.fx[0].security_rule :
      rule.access != "Allow" || (
        rule.source_address_prefix == "192.0.2.1/32" &&
        toset(rule.destination_port_ranges) == toset(["22"])
      )
    ])
    error_message = "Only SSH from the specified operator may be allowed."
  }
}
run "bastion_private_ssh_only" {
  command = plan
  variables {
    enable_bastion      = true
    allowed_client_cidr = "192.0.2.1/32"
  }
  assert {
    condition = alltrue([
      for rule in azurerm_network_security_group.fx[0].security_rule :
      rule.access != "Allow" || (
        rule.source_address_prefix == "10.42.2.0/26" &&
        rule.destination_port_range == "22"
      )
    ])
    error_message = "Bastion must replace public SSH with private subnet access only."
  }
  assert {
    condition     = azurerm_bastion_host.fx[0].sku == "Standard" && azurerm_bastion_host.fx[0].tunneling_enabled
    error_message = "Native dashboard tunnels require Standard Bastion with tunneling enabled."
  }
}
