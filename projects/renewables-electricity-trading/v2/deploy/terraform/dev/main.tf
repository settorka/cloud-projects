data "aws_caller_identity" "current" {}
resource "aws_lightsail_key_pair" "operator" {
  name       = "${var.name}-operator"
  public_key = var.ssh_public_key
}
resource "aws_lightsail_instance" "host" {
  name              = var.name
  availability_zone = "${var.region}a"
  blueprint_id      = "ubuntu_24_04"
  bundle_id         = var.bundle_id
  key_pair_name     = aws_lightsail_key_pair.operator.name
  ip_address_type   = "ipv4"
  user_data         = file("${path.module}/../templates/bootstrap.sh")
}
resource "aws_lightsail_static_ip" "host" { name = "${var.name}-ip" }
resource "aws_lightsail_static_ip_attachment" "host" {
  static_ip_name = aws_lightsail_static_ip.host.name
  instance_name  = aws_lightsail_instance.host.name
}
resource "aws_lightsail_instance_public_ports" "host" {
  instance_name = aws_lightsail_instance.host.name
  port_info {
    from_port = 22
    to_port   = 22
    protocol  = "tcp"
    cidrs     = [var.operator_cidr]
  }
  dynamic "port_info" {
    for_each = var.access_mode == "public" ? { http = 80, https = 443 } : {}
    content {
      from_port = port_info.value
      to_port   = port_info.value
      protocol  = "tcp"
      cidrs     = port_info.key == "http" ? ["0.0.0.0/0"] : [var.client_cidr]
    }
  }
}
resource "aws_ecr_repository" "service" {
  for_each             = toset(["trading", "market-data", "valuation"])
  name                 = "${var.name}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  image_scanning_configuration { scan_on_push = true }
  force_delete = false
}
resource "aws_ecr_lifecycle_policy" "service" {
  for_each   = aws_ecr_repository.service
  repository = each.value.name
  policy     = jsonencode({ rules = [{ rulePriority = 1, description = "Bound retained images by operating profile", selection = { tagStatus = "any", countType = "imageCountMoreThan", countNumber = var.operating.ecr_retained_images }, action = { type = "expire" } }] })
}
resource "aws_s3_bucket" "backup" {
  bucket = var.backup_bucket_name
  lifecycle { prevent_destroy = true }
}
resource "aws_s3_bucket_public_access_block" "backup" {
  bucket                  = aws_s3_bucket.backup.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "backup" {
  bucket = aws_s3_bucket.backup.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_policy" "backup" {
  bucket = aws_s3_bucket.backup.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Deny", Principal = "*", Action = "s3:*",
    Resource  = [aws_s3_bucket.backup.arn, "${aws_s3_bucket.backup.arn}/*"],
    Condition = { Bool = { "aws:SecureTransport" = "false" } }
  }] })
}
resource "aws_s3_bucket_lifecycle_configuration" "backup" {
  bucket = aws_s3_bucket.backup.id
  rule {
    id     = "expire-daily-backups"
    status = "Enabled"
    filter { prefix = "postgres/" }
    expiration { days = var.operating.backup_retention_days }
    abort_incomplete_multipart_upload { days_after_initiation = 1 }
  }
}
resource "aws_sns_topic" "alerts" { name = "${var.name}-alerts" }
resource "aws_sns_topic_subscription" "email" {
  count     = var.alert_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.alert_email
}
resource "aws_budgets_budget" "monthly" {
  name         = "${var.name}-account-cap"
  budget_type  = "COST"
  limit_amount = "50"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"
  # Account-wide deliberately: all AWS spending competes with this ceiling.
  dynamic "notification" {
    for_each = var.alert_email == "" ? [] : [50, 70, 90]
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = notification.value
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.alert_email]
    }
  }
}
