data "aws_caller_identity" "current" {}
locals {
  reference_environment = jsondecode(file(var.reference_environment_file))
  reference_minutes     = tonumber(local.reference_environment["REFERENCE_INTERVAL_SECONDS"]) / 60
}
data "aws_availability_zones" "available" { state = "available" }
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"]
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-amd64-server-*"]
  }
  filter {
    name   = "architecture"
    values = ["x86_64"]
  }
}

resource "aws_s3_bucket" "data" {
  bucket        = "${var.name}-${data.aws_caller_identity.current.account_id}-${var.region}"
  force_destroy = false
}
resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    id     = "references"
    status = "Enabled"
    filter { prefix = "references/" }
    expiration { days = 30 }
  }
  rule {
    id     = "backups"
    status = "Enabled"
    filter { prefix = "backups/" }
    expiration { days = 7 }
  }
  rule {
    id     = "old-artifacts"
    status = "Enabled"
    filter { prefix = "artifacts/" }
    expiration { days = 30 }
  }
}
resource "aws_s3_object" "application" {
  bucket      = aws_s3_bucket.data.id
  key         = "artifacts/${filesha256(var.application_archive)}.tar.gz"
  source      = var.application_archive
  source_hash = filesha256(var.application_archive)
}

resource "aws_vpc" "main" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
}
resource "aws_subnet" "public" {
  vpc_id                  = aws_vpc.main.id
  cidr_block              = "10.42.1.0/24"
  availability_zone       = data.aws_availability_zones.available.names[0]
  map_public_ip_on_launch = true
}
resource "aws_internet_gateway" "main" { vpc_id = aws_vpc.main.id }
resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }
}
resource "aws_route_table_association" "public" {
  subnet_id      = aws_subnet.public.id
  route_table_id = aws_route_table.public.id
}
resource "aws_security_group" "web" {
  name_prefix = "${var.name}-"
  vpc_id      = aws_vpc.main.id
  ingress = [for port in(var.domain == "" ? [] : [80, 443]) : {
    from_port       = port, to_port = port, protocol = "tcp",
    cidr_blocks     = ["0.0.0.0/0"], ipv6_cidr_blocks = [], prefix_list_ids = [],
    security_groups = [], self = false, description = "Optional public web access"
  }]
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

resource "aws_instance" "application" {
  ami                    = data.aws_ami.ubuntu.id
  instance_type          = var.instance_type
  subnet_id              = aws_subnet.public.id
  vpc_security_group_ids = [aws_security_group.web.id]
  iam_instance_profile   = data.aws_iam_instance_profile.host.name
  credit_specification { cpu_credits = "standard" }
  metadata_options {
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }
  root_block_device {
    volume_size           = var.disk_size_gb
    volume_type           = "gp3"
    encrypted             = true
    delete_on_termination = false
  }
  volume_tags = { Project = var.name, Environment = "development" }
  lifecycle { ignore_changes = [ami, user_data] }
  user_data = templatefile("${path.module}/cloud-init.sh.tftpl", {
    bucket       = aws_s3_bucket.data.id, artifact = aws_s3_object.application.key,
    region       = var.region, domain = var.domain, bbox = var.ais_bbox,
    tunnel_port  = var.api_tunnel_port, project = var.name,
    artifact_sha = filesha256(var.application_archive)
  })
  depends_on = [aws_route_table_association.public, aws_cloudwatch_log_group.otel]
  tags       = { Name = var.name }
}
resource "aws_eip" "application" {
  domain   = "vpc"
  instance = aws_instance.application.id
}

resource "aws_cloudwatch_log_group" "fetch" {
  name              = "/aws/lambda/${var.name}-references"
  retention_in_days = 14
}
resource "aws_lambda_function" "fetch" {
  depends_on                     = [aws_cloudwatch_log_group.fetch]
  function_name                  = "${var.name}-references"
  role                           = data.aws_iam_role.lambda.arn
  runtime                        = "python3.12"
  handler                        = "v2.lambda_handlers.fetch_references"
  filename                       = var.lambda_archive
  source_code_hash               = filebase64sha256(var.lambda_archive)
  timeout                        = 60
  memory_size                    = 512
  reserved_concurrent_executions = 2
  environment {
    variables = merge(local.reference_environment, { S3_BUCKET = aws_s3_bucket.data.id })
  }
}
resource "aws_lambda_function_event_invoke_config" "fetch" {
  function_name                = aws_lambda_function.fetch.function_name
  maximum_event_age_in_seconds = 900
  maximum_retry_attempts       = 1
}
resource "aws_scheduler_schedule" "fetch" {
  name                = "${var.name}-references"
  schedule_expression = "rate(${local.reference_minutes} ${local.reference_minutes == 1 ? "minute" : "minutes"})"
  flexible_time_window { mode = "OFF" }
  target {
    arn      = aws_lambda_function.fetch.arn
    role_arn = data.aws_iam_role.scheduler.arn
    input    = "{}"
    retry_policy {
      maximum_event_age_in_seconds = 900
      maximum_retry_attempts       = 1
    }
  }
}
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "${var.name}-reference-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 900
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  dimensions          = { FunctionName = aws_lambda_function.fetch.function_name }
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
resource "aws_budgets_budget" "monthly" {
  name         = var.name
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 80
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.budget_email]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.budget_email]
  }
}

# Administrative bootstrap creates these roles before the application plan.
data "aws_iam_instance_profile" "host" { name = "${var.name}-host" }
data "aws_iam_role" "lambda" { name = "${var.name}-fetch" }
data "aws_iam_role" "scheduler" { name = "${var.name}-schedule" }

resource "aws_s3_bucket_policy" "tls" {
  bucket = aws_s3_bucket.data.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Deny", Principal = "*", Action = "s3:*",
    Resource  = [aws_s3_bucket.data.arn, "${aws_s3_bucket.data.arn}/*"],
    Condition = { Bool = { "aws:SecureTransport" = "false" } }
  }] })
}
resource "aws_sns_topic" "alerts" { name = "${var.name}-alerts" }
resource "aws_sns_topic_subscription" "email" {
  topic_arn = aws_sns_topic.alerts.arn
  protocol  = "email"
  endpoint  = var.budget_email
}
resource "aws_cloudwatch_metric_alarm" "instance" {
  alarm_name          = "${var.name}-instance-failed"
  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed"
  dimensions          = { InstanceId = aws_instance.application.id }
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 3
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
resource "aws_cloudwatch_metric_alarm" "host" {
  for_each = {
    disk   = { metric = "system.filesystem.utilization", threshold = var.disk_free_min_percent / 100, comparison = "LessThanThreshold" }
    backup = { metric = "BackupAgeHours", threshold = var.backup_max_age_hours, comparison = "GreaterThanThreshold" }
  }
  alarm_name          = "${var.name}-${each.key}"
  namespace           = "MaritimeIntelligence"
  metric_name         = each.value.metric
  dimensions          = { Project = var.name }
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 2
  threshold           = each.value.threshold
  comparison_operator = each.value.comparison
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_log_group" "otel" {
  for_each          = toset(["application", "metrics"])
  name              = "/${var.name}/${each.key}"
  retention_in_days = 14
}
