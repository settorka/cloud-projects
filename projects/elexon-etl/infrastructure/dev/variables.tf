variable "subscription_id" { type = string }
variable "storage_account_name" {
  type = string
  validation {
    condition     = can(regex("^[a-z0-9]{3,24}$", var.storage_account_name))
    error_message = "Use a globally unique 3–24 character lowercase alphanumeric name."
  }
}
variable "registry_name" {
  type = string
  validation {
    condition     = can(regex("^[a-zA-Z0-9]{5,50}$", var.registry_name))
    error_message = "Use a globally unique 5–50 character alphanumeric registry name."
  }
}
variable "operator_object_id" {
  type        = string
  description = "Entra object ID of the developer who uploads images and reads Blob data."
}
variable "alert_email" {
  type = string
  validation {
    condition     = can(regex("^[^@ ]+@[^@ ]+\\.[^@ ]+$", var.alert_email))
    error_message = "Supply an alert recipient email."
  }
}
variable "image_digest" {
  type        = string
  default     = null
  nullable    = true
  description = "sha256 digest in this registry's elexon-etl repository. Null provisions foundations without a Job."
  validation {
    condition     = var.image_digest == null ? true : can(regex("^sha256:[0-9a-f]{64}$", var.image_digest))
    error_message = "Use sha256 followed by 64 lowercase hexadecimal characters."
  }
}
variable "dataset" {
  type    = string
  default = "BOTH"
  validation {
    condition     = contains(["PN", "BOD", "BOTH"], var.dataset)
    error_message = "Choose PN, BOD or BOTH."
  }
}
variable "source_date" {
  type        = string
  default     = "2025-01-01"
  nullable    = true
  description = "Explicit UTC source-file date for manual runs; null uses yesterday."
  validation {
    condition     = var.source_date == null ? true : can(formatdate("YYYY-MM-DD", "${var.source_date}T00:00:00Z"))
    error_message = "Use a valid YYYY-MM-DD date or null."
  }
}
variable "schedule_cron" {
  type        = string
  default     = null
  nullable    = true
  description = "Null means manual. A cron enables the daily rolling refresh for selected datasets."
  validation {
    condition     = var.schedule_cron == null || var.source_date == null
    error_message = "A schedule requires source_date=null so it does not repeatedly process a fixed date."
  }
  validation {
    condition     = var.schedule_cron == null ? true : can(regex("^([0-5]?[0-9]) ([01]?[0-9]|2[0-3]) [*] [*] [*]$", var.schedule_cron))
    error_message = "Choose one daily UTC time, e.g. 0 3 * * *. The 27-hour freshness alert assumes a daily schedule."
  }
}

variable "lookback_days" {
  type    = number
  default = 3
  validation {
    condition     = var.lookback_days >= 1 && var.lookback_days <= 7 && floor(var.lookback_days) == var.lookback_days
    error_message = "Choose an integer from 1 to 7."
  }
}
