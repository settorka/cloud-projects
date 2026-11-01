# Optional HTTPS transport when the client network blocks direct SSH.
# Standard keeps billing while provisioned, even when the VM is deallocated.
variable "enable_bastion" {
  type    = bool
  default = false
}
resource "azurerm_subnet" "bastion" {
  count                = var.enable_windows && var.enable_bastion ? 1 : 0
  name                 = "AzureBastionSubnet"
  resource_group_name  = data.azurerm_resource_group.fx.name
  virtual_network_name = azurerm_virtual_network.fx[0].name
  address_prefixes     = ["10.42.2.0/26"]
}
resource "azurerm_public_ip" "bastion" {
  count               = var.enable_windows && var.enable_bastion ? 1 : 0
  name                = "pip-fx-bastion"
  location            = data.azurerm_resource_group.fx.location
  resource_group_name = data.azurerm_resource_group.fx.name
  allocation_method   = "Static"
  sku                 = "Standard"
}
resource "azurerm_bastion_host" "fx" {
  count               = var.enable_windows && var.enable_bastion ? 1 : 0
  name                = "bastion-fx-dev"
  location            = data.azurerm_resource_group.fx.location
  resource_group_name = data.azurerm_resource_group.fx.name
  sku                 = "Standard"
  scale_units         = 2
  tunneling_enabled   = true
  ip_configuration {
    name                 = "primary"
    subnet_id            = azurerm_subnet.bastion[0].id
    public_ip_address_id = azurerm_public_ip.bastion[0].id
  }
  tags = {
    project     = "fx-settlement-analytics"
    environment = "dev"
  }
}
output "bastion_name" {
  value = var.enable_windows && var.enable_bastion ? azurerm_bastion_host.fx[0].name : null
}
output "windows_vm_id" {
  value = var.enable_windows ? azurerm_windows_virtual_machine.fx[0].id : null
}
