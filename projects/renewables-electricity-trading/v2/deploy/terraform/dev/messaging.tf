resource "aws_cloudwatch_event_bus" "domain" { name = var.name }
resource "aws_sqs_queue" "dlq" {
  for_each                  = toset(["trading-input", "valuation-input"])
  name                      = "${var.name}-${each.key}-dlq"
  message_retention_seconds = var.operating.dlq_retention_seconds
  sqs_managed_sse_enabled   = true
}
resource "aws_sqs_queue" "input" {
  for_each                   = aws_sqs_queue.dlq
  name                       = "${var.name}-${each.key}"
  visibility_timeout_seconds = var.operating.queue_visibility_seconds
  receive_wait_time_seconds  = var.operating.queue_wait_seconds
  message_retention_seconds  = var.operating.queue_retention_seconds
  sqs_managed_sse_enabled    = true
  redrive_policy             = jsonencode({ deadLetterTargetArn = each.value.arn, maxReceiveCount = var.operating.max_receive_count })
}
resource "aws_sqs_queue_redrive_allow_policy" "dlq" {
  for_each             = aws_sqs_queue.dlq
  queue_url            = each.value.url
  redrive_allow_policy = jsonencode({ redrivePermission = "byQueue", sourceQueueArns = [aws_sqs_queue.input[each.key].arn] })
}
resource "aws_sqs_queue" "routing_dlq" {
  name                      = "${var.name}-routing-dlq"
  message_retention_seconds = var.operating.dlq_retention_seconds
  sqs_managed_sse_enabled   = true
}
resource "aws_cloudwatch_event_rule" "destination" {
  for_each       = aws_sqs_queue.input
  name           = "${var.name}-${each.key}"
  event_bus_name = aws_cloudwatch_event_bus.domain.name
  event_pattern  = jsonencode({ source = ["renewables.v2"], detail = { destination = [each.key] } })
}
resource "aws_sqs_queue_policy" "input" {
  for_each  = aws_sqs_queue.input
  queue_url = each.value.url
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect   = "Allow", Principal = { Service = "events.amazonaws.com" }, Action = "sqs:SendMessage",
    Resource = each.value.arn, Condition = { ArnEquals = { "aws:SourceArn" = aws_cloudwatch_event_rule.destination[each.key].arn } }
  }] })
}
resource "aws_sqs_queue_policy" "routing_dlq" {
  queue_url = aws_sqs_queue.routing_dlq.url
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Principal = { Service = "events.amazonaws.com" }, Action = "sqs:SendMessage",
    Resource  = aws_sqs_queue.routing_dlq.arn,
    Condition = { ArnEquals = { "aws:SourceArn" = [for r in aws_cloudwatch_event_rule.destination : r.arn] } }
  }] })
}
resource "aws_cloudwatch_event_target" "queue" {
  for_each       = aws_sqs_queue.input
  rule           = aws_cloudwatch_event_rule.destination[each.key].name
  event_bus_name = aws_cloudwatch_event_bus.domain.name
  arn            = each.value.arn
  input_path     = "$.detail.envelope"
  retry_policy {
    maximum_event_age_in_seconds = var.operating.event_max_age_seconds
    maximum_retry_attempts       = var.operating.event_retry_attempts
  }
  dead_letter_config { arn = aws_sqs_queue.routing_dlq.arn }
  depends_on = [aws_sqs_queue_policy.input, aws_sqs_queue_policy.routing_dlq]
}
