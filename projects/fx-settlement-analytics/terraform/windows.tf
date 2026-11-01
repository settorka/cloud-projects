variable "enable_windows" {
  type    = bool
  default = false
}
variable "vm_size" {
  type    = string
  default = "Standard_D4ns_v6"
}
variable "admin_password" {
  type      = string
  sensitive = true
  default   = null
}
variable "allowed_client_cidr" {
  type    = string
  default = null
  validation {
    condition     = var.allowed_client_cidr == null ? true : can(cidrhost(var.allowed_client_cidr, 0)) && !endswith(var.allowed_client_cidr, "/0")
    error_message = "Provide a restricted CIDR, never an unrestricted /0."
  }
}

resource "azurerm_virtual_network" "fx" {
  count               = var.enable_windows ? 1 : 0
  name                = "vnet-fx-dev"
  address_space       = ["10.42.0.0/16"]
  location            = data.azurerm_resource_group.fx.location
  resource_group_name = data.azurerm_resource_group.fx.name
}
resource "azurerm_subnet" "fx" {
  count                = var.enable_windows ? 1 : 0
  name                 = "windows"
  resource_group_name  = data.azurerm_resource_group.fx.name
  virtual_network_name = azurerm_virtual_network.fx[0].name
  address_prefixes     = ["10.42.1.0/24"]
}
resource "azurerm_network_security_group" "fx" {
  count               = var.enable_windows ? 1 : 0
  name                = "nsg-fx-dev"
  location            = data.azurerm_resource_group.fx.location
  resource_group_name = data.azurerm_resource_group.fx.name
  dynamic "security_rule" {
    for_each = var.allowed_client_cidr == null || var.enable_bastion ? [] : [var.allowed_client_cidr]
    content {
      name                       = "OperatorRemoteAccess"
      priority                   = 100
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "Tcp"
      source_port_range          = "*"
      destination_port_ranges    = ["22"]
      source_address_prefix      = security_rule.value
      destination_address_prefix = "*"
    }
  }
  dynamic "security_rule" {
    for_each = var.enable_bastion ? [1] : []
    content {
      name                       = "BastionSshOnly"
      priority                   = 110
      direction                  = "Inbound"
      access                     = "Allow"
      protocol                   = "Tcp"
      source_port_range          = "*"
      destination_port_range     = "22"
      source_address_prefix      = "10.42.2.0/26"
      destination_address_prefix = "*"
    }
  }
  security_rule {
    name                       = "DenyOtherInbound"
    priority                   = 200
    direction                  = "Inbound"
    access                     = "Deny"
    protocol                   = "*"
    source_port_range          = "*"
    destination_port_range     = "*"
    source_address_prefix      = "*"
    destination_address_prefix = "*"
  }
}
resource "azurerm_public_ip" "fx" {
  count               = var.enable_windows ? 1 : 0
  name                = "pip-fx-dev"
  location            = data.azurerm_resource_group.fx.location
  resource_group_name = data.azurerm_resource_group.fx.name
  allocation_method   = "Static"
  sku                 = "Standard"
}
resource "azurerm_network_interface" "fx" {
  count               = var.enable_windows ? 1 : 0
  name                = "nic-fx-dev"
  location            = data.azurerm_resource_group.fx.location
  resource_group_name = data.azurerm_resource_group.fx.name
  ip_configuration {
    name                          = "primary"
    subnet_id                     = azurerm_subnet.fx[0].id
    private_ip_address_allocation = "Dynamic"
    public_ip_address_id          = azurerm_public_ip.fx[0].id
  }
}
resource "azurerm_network_interface_security_group_association" "fx" {
  count                     = var.enable_windows ? 1 : 0
  network_interface_id      = azurerm_network_interface.fx[0].id
  network_security_group_id = azurerm_network_security_group.fx[0].id
}
resource "azurerm_windows_virtual_machine" "fx" {
  count                 = var.enable_windows ? 1 : 0
  name                  = "vm-fx-dev"
  computer_name         = "fxdev"
  location              = data.azurerm_resource_group.fx.location
  resource_group_name   = data.azurerm_resource_group.fx.name
  size                  = var.vm_size
  admin_username        = "fxadmin"
  admin_password        = var.admin_password
  network_interface_ids = [azurerm_network_interface.fx[0].id]
  provision_vm_agent    = true
  disk_controller_type  = "NVMe"
  patch_mode            = "AutomaticByOS"
  identity {
    type = "SystemAssigned"
  }
  os_disk {
    caching              = "ReadWrite"
    storage_account_type = "StandardSSD_LRS"
    disk_size_gb         = 128
  }
  source_image_reference {
    publisher = "MicrosoftSQLServer"
    offer     = "sql2022-ws2022"
    sku       = "sqldev-gen2"
    version   = "16.0.260610"
  }
  depends_on = [azurerm_network_interface_security_group_association.fx]
}
resource "azurerm_managed_disk" "data" {
  count                = var.enable_windows ? 1 : 0
  name                 = "disk-fx-data"
  location             = data.azurerm_resource_group.fx.location
  resource_group_name  = data.azurerm_resource_group.fx.name
  storage_account_type = "StandardSSD_LRS"
  create_option        = "Empty"
  disk_size_gb         = 64
}
resource "azurerm_virtual_machine_data_disk_attachment" "data" {
  count              = var.enable_windows ? 1 : 0
  managed_disk_id    = azurerm_managed_disk.data[0].id
  virtual_machine_id = azurerm_windows_virtual_machine.fx[0].id
  lun                = 0
  caching            = "ReadOnly"
}
resource "azurerm_role_assignment" "vm_data" {
  count                = var.enable_windows ? 1 : 0
  scope                = "${azurerm_storage_account.fx.id}/blobServices/default/containers/${azurerm_storage_container.data.name}"
  role_definition_name = "Storage Blob Data Contributor"
  principal_id         = azurerm_windows_virtual_machine.fx[0].identity[0].principal_id
  principal_type       = "ServicePrincipal"
}
output "windows_public_ip" {
  value = var.enable_windows ? azurerm_public_ip.fx[0].ip_address : null
}

resource "azurerm_dev_test_global_vm_shutdown_schedule" "fx" {
  count                 = var.enable_windows ? 1 : 0
  virtual_machine_id    = azurerm_windows_virtual_machine.fx[0].id
  location              = data.azurerm_resource_group.fx.location
  enabled               = true
  daily_recurrence_time = "2200"
  timezone              = "GMT Standard Time"
  notification_settings {
    enabled = false
  }
}
