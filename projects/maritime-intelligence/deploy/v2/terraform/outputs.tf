output "instance_id" { value = aws_instance.application.id }
output "public_ip" { value = aws_eip.application.public_ip }
output "bucket" { value = aws_s3_bucket.data.id }
output "artifact" { value = aws_s3_object.application.key }
output "region" { value = var.region }
output "project" { value = var.name }
output "reference_function" { value = aws_lambda_function.fetch.function_name }
output "deployment_config" {
  value = { bucket = aws_s3_bucket.data.id, region = var.region, project = var.name, domain = var.domain, bbox = var.ais_bbox, tunnel_port = var.api_tunnel_port }
}
output "api_url" { value = var.domain == "" ? "http://127.0.0.1:${var.api_tunnel_port} (through SSM tunnel)" : "https://${var.domain}" }
output "ssm_tunnel_command" {
  value = "aws ssm start-session --region ${var.region} --target ${aws_instance.application.id} --document-name AWS-StartPortForwardingSession --parameters '${jsonencode({ portNumber = [tostring(var.api_tunnel_port)], localPortNumber = [tostring(var.api_tunnel_port)] })}'"
}

output "cloudwatch_console_url" {
  value = "https://${var.region}.console.aws.amazon.com/cloudwatch/home?region=${var.region}"
}
