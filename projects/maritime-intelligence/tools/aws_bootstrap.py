"""One-time state/IAM setup. Dry-run unless --apply; never provisions compute.

The existing GitHub role's OIDC trust is left unchanged. Runtime roles are created
here so the deployment workflow needs PassRole but no IAM mutation permission.
"""

import argparse
import json
import re
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]


def statement(actions, resources, condition=None):
    value = {"Effect": "Allow", "Action": actions, "Resource": resources}
    if condition:
        value["Condition"] = condition
    return value


def policies(account, region, name):
    data = f"{name}-{account}-{region}"
    state = f"{name}-state-{account}-{region}"
    arn = f"arn:aws:s3:::{data}"
    state_arn = f"arn:aws:s3:::{state}"
    roles = {kind: f"{name}-{kind}" for kind in ["host", "fetch", "schedule"]}
    function = f"arn:aws:lambda:{region}:{account}:function:{name}-references"
    runtime = {
        "host": [
            statement(["s3:ListBucket"], arn, {"StringLike": {"s3:prefix": "references/*"}}),
            statement(
                ["s3:GetObject"], [f"{arn}/{p}/*" for p in ["artifacts", "references", "backups"]]
            ),
            statement(["s3:PutObject"], f"{arn}/backups/*"),
            statement(
                [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents",
                    "logs:DescribeLogStreams",
                ],
                [
                    f"arn:aws:logs:{region}:{account}:log-group:/{name}/{group}{suffix}"
                    for group in ["application", "metrics"]
                    for suffix in ["", ":*"]
                ],
            ),
            statement(["xray:PutTraceSegments", "xray:PutTelemetryRecords"], "*"),
        ],
        "fetch": [
            statement(["s3:PutObject"], f"{arn}/references/*"),
            statement(
                ["logs:CreateLogStream", "logs:PutLogEvents"],
                f"arn:aws:logs:{region}:{account}:log-group:/aws/lambda/{name}-references:*",
            ),
        ],
        "schedule": [statement(["lambda:InvokeFunction"], function)],
    }
    regional = {"StringEquals": {"aws:RequestedRegion": region}}
    owned = {"StringEquals": {"aws:RequestedRegion": region, "ec2:ResourceTag/Project": name}}
    requested = {"StringEquals": {"aws:RequestedRegion": region, "aws:RequestTag/Project": name}}
    deploy = [
        statement(["ec2:Describe*"], "*", regional),
        statement(
            [
                "ec2:CreateVpc",
                "ec2:CreateSubnet",
                "ec2:CreateInternetGateway",
                "ec2:CreateRouteTable",
                "ec2:CreateSecurityGroup",
                "ec2:AllocateAddress",
            ],
            "*",
            requested,
        ),
        statement(
            ["ec2:RunInstances"],
            [f"arn:aws:ec2:{region}:{account}:{kind}/*" for kind in ["instance", "volume"]],
            requested,
        ),
        statement(
            ["ec2:RunInstances"],
            [f"arn:aws:ec2:{region}::{kind}/*" for kind in ["image", "snapshot"]]
            + [
                f"arn:aws:ec2:{region}:{account}:{kind}/*"
                for kind in ["subnet", "security-group", "network-interface"]
            ],
            regional,
        ),
        statement(
            ["ec2:CreateTags"],
            "*",
            {
                "StringEquals": {
                    "aws:RequestedRegion": region,
                    "ec2:CreateAction": [
                        "RunInstances",
                        "CreateVpc",
                        "CreateSubnet",
                        "CreateInternetGateway",
                        "CreateRouteTable",
                        "CreateSecurityGroup",
                        "AllocateAddress",
                    ],
                }
            },
        ),
        statement(
            [
                "ec2:DeleteVpc",
                "ec2:ModifyVpcAttribute",
                "ec2:DeleteSubnet",
                "ec2:ModifySubnetAttribute",
                "ec2:AttachInternetGateway",
                "ec2:DetachInternetGateway",
                "ec2:DeleteInternetGateway",
                "ec2:CreateRoute",
                "ec2:DeleteRoute",
                "ec2:DeleteRouteTable",
                "ec2:AssociateRouteTable",
                "ec2:DisassociateRouteTable",
                "ec2:ReplaceRouteTableAssociation",
                "ec2:AuthorizeSecurityGroupIngress",
                "ec2:RevokeSecurityGroupIngress",
                "ec2:AuthorizeSecurityGroupEgress",
                "ec2:RevokeSecurityGroupEgress",
                "ec2:DeleteSecurityGroup",
                "ec2:TerminateInstances",
                "ec2:StopInstances",
                "ec2:StartInstances",
                "ec2:ModifyInstanceAttribute",
                "ec2:ModifyInstanceCreditSpecification",
                "ec2:ModifyInstanceMetadataOptions",
                "ec2:AssociateIamInstanceProfile",
                "ec2:DisassociateIamInstanceProfile",
                "ec2:ReplaceIamInstanceProfileAssociation",
                "ec2:AssociateAddress",
                "ec2:DisassociateAddress",
                "ec2:ReleaseAddress",
            ],
            "*",
            owned,
        ),
        statement(
            ["iam:GetRole", "iam:GetInstanceProfile"],
            [f"arn:aws:iam::{account}:role/{v}" for v in roles.values()]
            + [f"arn:aws:iam::{account}:instance-profile/{roles['host']}"],
        ),
        statement(
            ["iam:PassRole"],
            [f"arn:aws:iam::{account}:role/{v}" for v in roles.values()],
            {
                "StringEquals": {
                    "iam:PassedToService": [
                        "ec2.amazonaws.com",
                        "lambda.amazonaws.com",
                        "scheduler.amazonaws.com",
                    ]
                }
            },
        ),
        statement(
            [
                "s3:CreateBucket",
                "s3:DeleteBucket",
                "s3:GetBucket*",
                "s3:ListBucket",
                "s3:PutBucket*",
                "s3:GetEncryptionConfiguration",
                "s3:PutEncryptionConfiguration",
                "s3:GetLifecycleConfiguration",
                "s3:PutLifecycleConfiguration",
            ],
            arn,
        ),
        statement(["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], f"{arn}/artifacts/*"),
        statement(["s3:GetBucketLocation", "s3:ListBucket"], state_arn),
        statement(
            ["s3:GetObject", "s3:PutObject"],
            [f"{state_arn}/development.tfstate", f"{state_arn}/development.tfstate.tflock"],
        ),
        statement(["s3:DeleteObject"], f"{state_arn}/development.tfstate.tflock"),
        statement(
            [
                "lambda:CreateFunction",
                "lambda:GetFunction",
                "lambda:GetFunctionConfiguration",
                "lambda:GetFunctionCodeSigningConfig",
                "lambda:GetRuntimeManagementConfig",
                "lambda:UpdateFunctionCode",
                "lambda:UpdateFunctionConfiguration",
                "lambda:DeleteFunction",
                "lambda:ListVersionsByFunction",
                "lambda:GetPolicy",
                "lambda:ListTags",
                "lambda:TagResource",
                "lambda:UntagResource",
                "lambda:PutFunctionConcurrency",
                "lambda:GetFunctionConcurrency",
                "lambda:DeleteFunctionConcurrency",
                "lambda:PutFunctionEventInvokeConfig",
                "lambda:GetFunctionEventInvokeConfig",
                "lambda:DeleteFunctionEventInvokeConfig",
                "lambda:InvokeFunction",
            ],
            function,
        ),
        statement(
            [
                "scheduler:CreateSchedule",
                "scheduler:GetSchedule",
                "scheduler:UpdateSchedule",
                "scheduler:DeleteSchedule",
            ],
            f"arn:aws:scheduler:{region}:{account}:schedule/default/{name}-references",
        ),
        statement(
            [
                "logs:CreateLogGroup",
                "logs:DescribeLogStreams",
                "logs:ListTagsForResource",
                "logs:TagResource",
                "logs:UntagResource",
                "logs:PutRetentionPolicy",
                "logs:DeleteLogGroup",
            ],
            [
                f"arn:aws:logs:{region}:{account}:log-group:/aws/lambda/{name}-references",
                f"arn:aws:logs:{region}:{account}:log-group:/aws/lambda/{name}-references:*",
                *[
                    f"arn:aws:logs:{region}:{account}:log-group:/{name}/{group}{suffix}"
                    for group in ["application", "metrics"]
                    for suffix in ["", ":*"]
                ],
            ],
        ),
        statement(["logs:DescribeLogGroups"], "*"),
        statement(["cloudwatch:DescribeAlarms", "cloudwatch:ListTagsForResource"], "*"),
        statement(
            [
                "cloudwatch:PutMetricAlarm",
                "cloudwatch:DeleteAlarms",
                "cloudwatch:TagResource",
                "cloudwatch:UntagResource",
            ],
            f"arn:aws:cloudwatch:{region}:{account}:alarm:{name}-*",
        ),
        statement(
            [
                "sns:CreateTopic",
                "sns:DeleteTopic",
                "sns:GetTopicAttributes",
                "sns:SetTopicAttributes",
                "sns:Subscribe",
                "sns:ListSubscriptionsByTopic",
                "sns:GetSubscriptionAttributes",
                "sns:Unsubscribe",
                "sns:ListTagsForResource",
                "sns:TagResource",
                "sns:UntagResource",
            ],
            [
                f"arn:aws:sns:{region}:{account}:{name}-alerts",
                f"arn:aws:sns:{region}:{account}:{name}-alerts:*",
            ],
        ),
        statement(
            [
                "budgets:ViewBudget",
                "budgets:ModifyBudget",
                "budgets:TagResource",
                "budgets:UntagResource",
                "budgets:ListTagsForResource",
            ],
            f"arn:aws:budgets::{account}:budget/{name}",
        ),
        statement(["ssm:SendCommand"], f"arn:aws:ssm:{region}::document/AWS-RunShellScript"),
        statement(
            ["ssm:SendCommand"],
            f"arn:aws:ec2:{region}:{account}:instance/*",
            {"StringEquals": {"ssm:resourceTag/Project": name}},
        ),
        statement(["ssm:GetCommandInvocation", "ssm:DescribeInstanceInformation"], "*", regional),
    ]
    return {
        "state_bucket": state,
        "data_bucket": data,
        "roles": roles,
        "runtime": {
            key: {"Version": "2012-10-17", "Statement": value} for key, value in runtime.items()
        },
        "deployment": {"Version": "2012-10-17", "Statement": deploy},
    }


def bootstrap(session, region, name, github_role, apply):
    account = session.client("sts").get_caller_identity()["Account"]
    config = policies(account, region, name)
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    (output / "github-deployment-policy.json").write_text(
        json.dumps(config["deployment"], indent=2)
    )
    (output / "backend.hcl").write_text(
        f'bucket = "{config["state_bucket"]}"\nkey = "development.tfstate"\nregion = "{region}"\nuse_lockfile = true\nencrypt = true\n'
    )
    print("State bucket:", config["state_bucket"], "; GitHub role:", github_role)
    if not apply:
        print("Dry run: policy and backend configuration generated; no AWS changes")
        return
    s3 = session.client("s3", region_name=region)
    iam = session.client("iam")
    tags = [{"Key": "Project", "Value": name}]
    try:
        s3.head_bucket(Bucket=config["state_bucket"], ExpectedBucketOwner=account)
        current = s3.get_bucket_tagging(Bucket=config["state_bucket"])["TagSet"]
        if {"Key": "Project", "Value": name} not in current:
            raise ValueError("Existing state bucket is not tagged for this project")
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in {"404", "NoSuchBucket"}:
            raise
        args = {"Bucket": config["state_bucket"]}
        if region != "us-east-1":
            args["CreateBucketConfiguration"] = {"LocationConstraint": region}
        s3.create_bucket(**args)
        s3.put_bucket_tagging(Bucket=config["state_bucket"], Tagging={"TagSet": tags})
    bucket = config["state_bucket"]
    s3.put_public_access_block(
        Bucket=bucket,
        PublicAccessBlockConfiguration={
            k: True
            for k in [
                "BlockPublicAcls",
                "IgnorePublicAcls",
                "BlockPublicPolicy",
                "RestrictPublicBuckets",
            ]
        },
    )
    s3.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={"Status": "Enabled"})
    s3.put_bucket_encryption(
        Bucket=bucket,
        ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
        },
    )
    s3.put_bucket_policy(
        Bucket=bucket,
        Policy=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Deny",
                        "Principal": "*",
                        "Action": "s3:*",
                        "Resource": [f"arn:aws:s3:::{bucket}", f"arn:aws:s3:::{bucket}/*"],
                        "Condition": {"Bool": {"aws:SecureTransport": "false"}},
                    }
                ],
            }
        ),
    )
    for kind, role in config["roles"].items():
        try:
            current = iam.get_role(RoleName=role)["Role"]
            if {"Key": "Project", "Value": name} not in current.get("Tags", []):
                raise ValueError("Existing runtime role is not owned by this project: " + role)
        except iam.exceptions.NoSuchEntityException:
            service = {"host": "ec2", "fetch": "lambda", "schedule": "scheduler"}[kind]
            iam.create_role(
                RoleName=role,
                Tags=tags,
                AssumeRolePolicyDocument=json.dumps(
                    {
                        "Version": "2012-10-17",
                        "Statement": [
                            {
                                "Effect": "Allow",
                                "Principal": {"Service": service + ".amazonaws.com"},
                                "Action": "sts:AssumeRole",
                            }
                        ],
                    }
                ),
            )
        iam.put_role_policy(
            RoleName=role,
            PolicyName="MaritimeRuntime",
            PolicyDocument=json.dumps(config["runtime"][kind]),
        )
    iam.attach_role_policy(
        RoleName=config["roles"]["host"],
        PolicyArn="arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore",
    )
    try:
        profile = iam.get_instance_profile(InstanceProfileName=config["roles"]["host"])[
            "InstanceProfile"
        ]
    except iam.exceptions.NoSuchEntityException:
        profile = iam.create_instance_profile(
            InstanceProfileName=config["roles"]["host"], Tags=tags
        )["InstanceProfile"]
    if {"Key": "Project", "Value": name} not in profile.get("Tags", []):
        raise ValueError("Existing instance profile is not owned by this project")
    if not profile["Roles"]:
        iam.add_role_to_instance_profile(
            InstanceProfileName=config["roles"]["host"], RoleName=config["roles"]["host"]
        )
    elif [r["RoleName"] for r in profile["Roles"]] != [config["roles"]["host"]]:
        raise ValueError("Existing instance profile contains a different role")
    iam.put_role_policy(
        RoleName=github_role,
        PolicyName="MaritimeDeployment",
        PolicyDocument=json.dumps(config["deployment"]),
    )
    print("Bootstrap complete; runtime roles and locked/versioned state bucket ready")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--region", default="eu-west-2")
    parser.add_argument("--name", default="maritime-intelligence")
    parser.add_argument("--github-role", default="GitHubActionsDevRole")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not re.fullmatch("[a-z][a-z0-9-]{2,39}", args.name):
        parser.error("Invalid project name")
    bootstrap(boto3.Session(), args.region, args.name, args.github_role, args.apply)
