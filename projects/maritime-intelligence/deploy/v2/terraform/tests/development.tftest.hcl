mock_provider "aws" {
  mock_data "aws_iam_instance_profile" {
    defaults = { name = "maritime-intelligence-host" }
  }
  mock_resource "aws_sns_topic" {
    defaults = { arn = "arn:aws:sns:eu-west-2:123456789012:maritime-intelligence-alerts" }
  }
  mock_data "aws_caller_identity" {
    defaults = { account_id = "123456789012" }
  }
  mock_data "aws_availability_zones" {
    defaults = { names = ["eu-west-2a"] }
  }
  mock_data "aws_ami" {
    defaults = { id = "ami-0123456789abcdef0" }
  }
  mock_data "aws_iam_role" {
    defaults = { arn = "arn:aws:iam::123456789012:role/test" }
  }
  mock_resource "aws_lambda_function" {
    defaults = { arn = "arn:aws:lambda:eu-west-2:123456789012:function:test" }
  }
  mock_resource "aws_s3_bucket" {
    defaults = { arn = "arn:aws:s3:::test-maritime" }
  }
  mock_resource "aws_cloudwatch_log_group" {
    defaults = { arn = "arn:aws:logs:eu-west-2:123456789012:log-group:test" }
  }
}

run "development_security_boundaries" {
  command = plan
  variables {
    domain       = "maritime.example.com"
    budget_email = "owner@example.com"
  }
  assert {
    condition     = length(aws_security_group.web.ingress) == 2 && alltrue([for rule in aws_security_group.web.ingress : contains([80, 443], rule.from_port) && rule.from_port == rule.to_port])
    error_message = "Only HTTP/HTTPS ingress may be public."
  }
  assert {
    condition     = aws_instance.application.metadata_options[0].http_tokens == "required"
    error_message = "IMDSv2 is required."
  }
  assert {
    condition     = aws_instance.application.credit_specification[0].cpu_credits == "standard"
    error_message = "Avoid unexpected surplus CPU credit charges."
  }
  assert {
    condition     = aws_instance.application.root_block_device[0].encrypted
    error_message = "Database volume must be encrypted."
  }
  assert {
    condition     = aws_s3_bucket_public_access_block.data.block_public_policy && aws_s3_bucket_public_access_block.data.block_public_acls
    error_message = "Observation/reference storage must block public access."
  }
  assert {
    condition     = aws_lambda_function.fetch.reserved_concurrent_executions == 2
    error_message = "Bound scheduled-function concurrency."
  }
}

run "without_domain_has_no_public_ingress" {
  command = plan
  variables {
    domain       = ""
    budget_email = "owner@example.com"
  }
  assert {
    condition     = length(aws_security_group.web.ingress) == 0
    error_message = "No-domain deployments must have no inbound public ports."
  }
  assert {
    condition     = strcontains(output.api_url, "through SSM tunnel")
    error_message = "The output must explain private SSM access."
  }
}
