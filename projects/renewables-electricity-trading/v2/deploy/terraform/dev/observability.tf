resource "aws_cloudwatch_log_group" "application" {
  name              = "/renewables/${var.name}"
  retention_in_days = var.operating.log_retention_days
}
resource "aws_cloudwatch_metric_alarm" "dlq" {
  for_each            = merge(aws_sqs_queue.dlq, { routing = aws_sqs_queue.routing_dlq })
  alarm_name          = "${var.name}-${each.key}-dlq"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  dimensions          = { QueueName = each.value.name }
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
resource "aws_cloudwatch_metric_alarm" "queue_age" {
  for_each            = aws_sqs_queue.input
  alarm_name          = "${var.name}-${each.key}-age"
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateAgeOfOldestMessage"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = var.operating.queue_age_alarm_seconds
  comparison_operator = "GreaterThanThreshold"
  dimensions          = { QueueName = each.value.name }
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
resource "aws_cloudwatch_metric_alarm" "heartbeat" {
  alarm_name          = "${var.name}-heartbeat"
  namespace           = "Renewables/V2"
  metric_name         = "HostHealthy"
  statistic           = "Minimum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

resource "aws_cloudwatch_metric_alarm" "disk" {
  alarm_name          = "${var.name}-disk"
  namespace           = "Renewables/V2"
  metric_name         = "DiskUsedPercent"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 2
  threshold           = var.operating.disk_alarm_percent
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
resource "aws_cloudwatch_metric_alarm" "backup" {
  alarm_name          = "${var.name}-backup"
  namespace           = "Renewables/V2"
  metric_name         = "BackupSucceeded"
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = var.operating.backup_alarm_hours
  datapoints_to_alarm = var.operating.backup_alarm_hours
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
resource "aws_cloudwatch_metric_alarm" "worker" {
  for_each            = toset(["trading", "market-data", "valuation"])
  alarm_name          = "${var.name}-${each.key}-worker"
  namespace           = "Renewables/V2"
  metric_name         = "WorkerHealthy"
  dimensions          = { Service = each.key }
  statistic           = "Minimum"
  period              = 300
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
