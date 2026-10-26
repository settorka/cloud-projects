mock_provider "aws" {
  mock_data "aws_caller_identity" { defaults = { account_id = "123456789012" } }
  mock_resource "aws_sqs_queue" {
    defaults = {
      arn = "arn:aws:sqs:eu-west-2:123456789012:mock-queue"
      url = "https://sqs.eu-west-2.amazonaws.com/123456789012/mock-queue"
    }
  }
  mock_resource "aws_s3_bucket" { defaults = { arn = "arn:aws:s3:::mock-backup" } }
  mock_resource "aws_cloudwatch_event_bus" { defaults = { arn = "arn:aws:events:eu-west-2:123456789012:event-bus/mock" } }
  mock_resource "aws_cloudwatch_event_rule" { defaults = { arn = "arn:aws:events:eu-west-2:123456789012:rule/mock" } }
  mock_resource "aws_cloudwatch_log_group" { defaults = { arn = "arn:aws:logs:eu-west-2:123456789012:log-group:mock" } }
  mock_resource "aws_sns_topic" { defaults = { arn = "arn:aws:sns:eu-west-2:123456789012:mock" } }
  mock_resource "aws_ecr_repository" { defaults = { arn = "arn:aws:ecr:eu-west-2:123456789012:repository/mock" } }
}
variables {
  access_mode        = "tunnel"
  aws_account_id     = "123456789012"
  operating          = { "log_retention_days" : 7, "queue_visibility_seconds" : 60, "queue_wait_seconds" : 20, "queue_retention_seconds" : 345600, "dlq_retention_seconds" : 1209600, "max_receive_count" : 5, "event_max_age_seconds" : 3600, "event_retry_attempts" : 10, "backup_retention_days" : 7, "ecr_retained_images" : 3, "queue_age_alarm_seconds" : 120, "disk_alarm_percent" : 70, "backup_alarm_hours" : 26 }
  region             = "eu-west-2"
  name               = "renewables-v2-dev"
  bundle_id          = "medium_3_0"
  ssh_public_key     = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestOnlyPublicKey"
  operator_cidr      = "203.0.113.10/32"
  client_cidr        = "203.0.113.10/32"
  alert_email        = "operator@example.com"
  domain_name        = "trading-dev.example.com"
  backup_bucket_name = "renewables-test-backup"
}
run "budget_profile" {
  command = plan
  assert {
    condition     = aws_lightsail_instance.host.bundle_id == "medium_3_0"
    error_message = "The budget profile must stay on the reviewed $24 bundle."
  }
  assert {
    condition     = aws_cloudwatch_event_target.queue["trading-input"].input_path == "$.detail.envelope"
    error_message = "SQS must receive the application envelope, not the AWS wrapper."
  }
  assert {
    condition     = aws_sqs_queue.input["trading-input"].visibility_timeout_seconds == 60 && aws_sqs_queue.dlq["trading-input"].message_retention_seconds == 1209600
    error_message = "Queue visibility and DLQ retention must match the operating contract."
  }
  assert {
    condition     = aws_budgets_budget.monthly.limit_amount == "50"
    error_message = "Account budget must remain $50."
  }
}
run "reject_public_ssh" {
  command = plan
  variables { operator_cidr = "0.0.0.0/0" }
  expect_failures = [var.operator_cidr]
}
run "reject_unreviewed_size" {
  command = plan
  variables { bundle_id = "large_3_0" }
  expect_failures = [var.bundle_id]
}

run "reject_public_https" {
  command = plan
  variables { client_cidr = "0.0.0.0/0" }
  expect_failures = [var.client_cidr]
}

run "tunnel_without_email" {
  command = plan
  variables { alert_email = "" }
  assert {
    condition     = length(aws_sns_topic_subscription.email) == 0 && length(aws_lightsail_instance_public_ports.host.port_info) == 1
    error_message = "Tunnel mode should require neither public HTTP/S ingress nor a fabricated email subscription."
  }
}
