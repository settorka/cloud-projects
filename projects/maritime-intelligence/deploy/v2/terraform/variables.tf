variable "region" {
  type    = string
  default = "eu-west-2"
}
variable "name" {
  type    = string
  default = "maritime-intelligence"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,39}$", var.name))
    error_message = "Use 3–40 lowercase letters, digits or hyphens."
  }
}
variable "instance_type" {
  type    = string
  default = "t3a.large"
  validation {
    condition     = contains(["t3a.medium", "t3a.large"], var.instance_type)
    error_message = "Only the small x86 development instances are permitted."
  }
}
variable "domain" {
  description = "Optional DNS name for public HTTPS. Empty means SSM tunnel access only."
  type        = string
  default     = ""
  validation {
    condition     = var.domain == "" || can(regex("^[a-z0-9][a-z0-9.-]+\\.[a-z]{2,}$", var.domain))
    error_message = "Provide an empty string or a lowercase DNS name; no scheme or path."
  }
}
variable "api_tunnel_port" {
  description = "Loopback-only host port used by SSM port forwarding."
  type        = number
  default     = 8200
  validation {
    condition     = var.api_tunnel_port >= 1024 && var.api_tunnel_port <= 65535 && floor(var.api_tunnel_port) == var.api_tunnel_port
    error_message = "Tunnel port must be an integer between 1024 and 65535."
  }
}
variable "budget_email" {
  description = "Owner's address for AWS cost notifications."
  type        = string
  sensitive   = true
}
variable "monthly_budget_usd" {
  description = "USD billing threshold. Convert the £100 all-in ceiling, allowing for tax and FX."
  type        = number
  default     = 85
  validation {
    condition     = var.monthly_budget_usd > 0 && var.monthly_budget_usd <= 100
    error_message = "Keep the development alert budget between 0 and 100 USD."
  }
}
variable "application_archive" {
  type    = string
  default = "../../../dist/application.tar.gz"
}
variable "lambda_archive" {
  type    = string
  default = "../../../dist/references-lambda.zip"
}
variable "reference_environment_file" {
  description = "Generated from the grouped .env; includes no credentials."
  type        = string
  default     = "../../../dist/reference-environment.json"
}
variable "ais_bbox" {
  type    = string
  default = "19,59,30,66"
  validation {
    condition     = can(regex("^-?[0-9.]+,-?[0-9.]+,-?[0-9.]+,-?[0-9.]+$", var.ais_bbox))
    error_message = "Use west,south,east,north numeric coordinates."
  }
}
variable "disk_size_gb" {
  type    = number
  default = 100
  validation {
    condition     = var.disk_size_gb >= 40 && var.disk_size_gb <= 120
    error_message = "Development disk size must be 40–120 GB; recheck cost before increasing."
  }
}
variable "disk_free_min_percent" {
  type    = number
  default = 15
}
variable "backup_max_age_hours" {
  type    = number
  default = 26
}
