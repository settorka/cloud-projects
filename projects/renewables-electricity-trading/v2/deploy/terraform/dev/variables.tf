variable "region" {
  type = string
  validation {
    condition     = var.region == "eu-west-2"
    error_message = "This budget and residency profile is reviewed for London only."
  }
}
variable "name" {
  type = string
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,29}$", var.name))
    error_message = "Use 3..30 lowercase letters, numbers and hyphens."
  }
}
variable "ssh_public_key" {
  type        = string
  description = "Public SSH key only; private keys never enter Terraform."
}
variable "operator_cidr" {
  type = string
  validation {
    condition     = can(cidrnetmask(var.operator_cidr)) && can(regex("/32$", var.operator_cidr))
    error_message = "Use the operator's single IPv4 /32 address."
  }
}
variable "client_cidr" {
  type        = string
  description = "Allowed HTTPS clients; default to the operator /32 in tfvars."
  validation {
    condition     = can(cidrnetmask(var.client_cidr)) && !contains(["0.0.0.0/0", "::/0"], var.client_cidr)
    error_message = "Development HTTPS must be restricted to a client CIDR."
  }
}
variable "alert_email" {
  type        = string
  description = "Empty disables email delivery; alarms and the budget remain visible in AWS."
}
variable "domain_name" {
  type        = string
  description = "Existing DNS name; point its A record at the static IP after apply."
}
variable "backup_bucket_name" { type = string }
variable "bundle_id" {
  type = string
  validation {
    condition     = var.bundle_id == "medium_3_0"
    error_message = "The reviewed $24 budget profile uses the 4 GB IPv4 Lightsail bundle only."
  }
}

variable "operating" {
  type = object({
    log_retention_days       = number
    queue_visibility_seconds = number
    queue_wait_seconds       = number
    queue_retention_seconds  = number
    dlq_retention_seconds    = number
    max_receive_count        = number
    event_max_age_seconds    = number
    event_retry_attempts     = number
    backup_retention_days    = number
    ecr_retained_images      = number
    queue_age_alarm_seconds  = number
    disk_alarm_percent       = number
    backup_alarm_hours       = number
  })
  validation {
    condition     = var.operating.queue_visibility_seconds >= 30 && var.operating.queue_visibility_seconds <= 300 && var.operating.log_retention_days <= 14 && var.operating.backup_retention_days <= 14
    error_message = "Operational tuning must stay within the reviewed development envelope."
  }
}

variable "access_mode" {
  type = string
  validation {
    condition     = contains(["tunnel", "public"], var.access_mode)
    error_message = "Choose tunnel or public access explicitly."
  }
}
variable "aws_account_id" {
  type = string
  validation {
    condition     = can(regex("^[0-9]{12}$", var.aws_account_id))
    error_message = "Set the intended 12-digit AWS account ID."
  }
}
