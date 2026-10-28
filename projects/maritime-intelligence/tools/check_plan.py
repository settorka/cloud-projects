"""Refuse destructive or unexpectedly expensive infrastructure plans in CI."""

import json
import sys

ALLOWED = {
    "aws_s3_bucket",
    "aws_s3_bucket_public_access_block",
    "aws_s3_bucket_server_side_encryption_configuration",
    "aws_s3_bucket_lifecycle_configuration",
    "aws_s3_bucket_policy",
    "aws_s3_object",
    "aws_vpc",
    "aws_subnet",
    "aws_internet_gateway",
    "aws_route_table",
    "aws_route_table_association",
    "aws_security_group",
    "aws_instance",
    "aws_eip",
    "aws_cloudwatch_log_group",
    "aws_lambda_function",
    "aws_lambda_function_event_invoke_config",
    "aws_scheduler_schedule",
    "aws_cloudwatch_metric_alarm",
    "aws_budgets_budget",
    "aws_sns_topic",
    "aws_sns_topic_subscription",
}


def check(plan):
    instances = 0
    for item in plan.get("resource_changes", []):
        if item.get("mode") == "data":
            continue
        actions = item["change"]["actions"]
        if "delete" in actions:
            raise ValueError("Deletion/replacement requires a separate review: " + item["address"])
        kind = item["type"]
        if kind.startswith("aws_iam_"):
            raise ValueError("CI may not manage IAM resources")
        if kind not in ALLOWED:
            raise ValueError("Resource type needs an explicit budget/security review: " + kind)
        value = item["change"].get("after") or {}
        if kind == "aws_instance":
            instances += 1
            if value.get("instance_type") not in {"t3a.medium", "t3a.large"}:
                raise ValueError("Instance exceeds development envelope")
            if value["root_block_device"][0]["volume_size"] > 120:
                raise ValueError("Disk exceeds development envelope")
            if not value["root_block_device"][0]["encrypted"]:
                raise ValueError("Disk must be encrypted")
            if value["metadata_options"][0]["http_tokens"] != "required":
                raise ValueError("IMDSv2 must be required")
            if value["credit_specification"][0]["cpu_credits"] != "standard":
                raise ValueError("Surplus-credit billing is outside the development envelope")
        if kind == "aws_security_group":
            for rule in value.get("ingress") or []:
                if rule["from_port"] not in [80, 443] or rule["from_port"] != rule["to_port"]:
                    raise ValueError("Unexpected public ingress")
        if kind in {
            "aws_nat_gateway",
            "aws_db_instance",
            "aws_msk_cluster",
            "aws_eks_cluster",
            "aws_lb",
        }:
            raise ValueError("Unbudgeted managed infrastructure: " + kind)
    if instances > 1:
        raise ValueError("Only one development host is allowed")


if __name__ == "__main__":
    check(json.load(sys.stdin))
    print("Plan guard passed: no deletions, IAM mutations or unbudgeted infrastructure")
