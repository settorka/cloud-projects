output "public_ip" { value = aws_lightsail_static_ip.host.ip_address }
output "runtime_user" { value = aws_iam_user.runtime.name }
output "event_bus" { value = aws_cloudwatch_event_bus.domain.name }
output "queues" { value = { for k, q in aws_sqs_queue.input : k => q.name } }
output "backup_bucket" { value = aws_s3_bucket.backup.id }
output "ecr_registry" { value = "${data.aws_caller_identity.current.account_id}.dkr.ecr.${var.region}.amazonaws.com/${var.name}" }
output "log_group" { value = aws_cloudwatch_log_group.application.name }
output "https_url" { value = var.access_mode == "tunnel" ? "https://localhost:8443" : "https://${var.domain_name}" }
output "email_alerts_configured" { value = var.alert_email != "" }
output "ssh_tunnel" { value = "ssh -N -L 8443:127.0.0.1:443 ubuntu@${aws_lightsail_static_ip.host.ip_address}" }
