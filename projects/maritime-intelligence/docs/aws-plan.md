# AWS development plan — 28 October 2026

The earlier pre-bootstrap Terraform plan succeeded: **27 additions, no changes, no deletions**.
It was generated with the local AWS login before role-based execution was selected.
No apply has run. The no-domain plan has an empty public-ingress rule set and uses
SSM forwarding to the loopback-bound API. The Session Manager plugin is installed.

## Recurring cost model

Prices were read from the AWS Pricing API in us-east-1, using its `EU (London)`
location label. The instance product is Linux/Shared/NA/Used/RunInstances.

| Item | Unit price USD | 31-day estimate USD |
|---|---:|---:|
| t3a.large | 0.085/hour | 63.24 |
| gp3, 100 GB, included baseline IOPS/throughput | 0.0928/GB-month | 9.28 |
| One public IPv4 address | 0.005/hour | 3.72 |
| S3, Lambda, logs, scheduling and minor usage | Planning allowance | 12.00 |
| **Total** | | **88.24** |

At an assumed **£0.85/USD** and **20% VAT**, this is **£90.00/month**. These FX/tax
figures are conservative modelling inputs, not a live exchange quote or tax advice.
The £100 ceiling leaves approximately £10.00 under these assumptions; it does not
meet the earlier optional £75 routine-spend aspiration. Retained EBS volumes,
unexpected transfers, larger backups or other account spending can increase cost.
AWS budget notifications do not enforce a spending cap. No free-tier credits are
needed in this model.

## GitHub role and deployment status

The approved `MaritimePlanRead` policy has been attached to `GitHubActionsDevRole`.
Its existing main-only GitHub OIDC trust is unchanged. The completed V2 bootstrap
prepares a broader project-scoped deployment policy, three runtime roles and locked
remote state; that bootstrap has not been applied. GitHub receives no IAM mutation
permissions. The new manual workflow is `.github/workflows/maritime-aws.yml`.

The earlier saved local plan is obsolete after these changes. See the V2 runbook
for the current bootstrap → plan → confirmed deploy sequence. There is no compute
infrastructure deployed by this project yet. The collector and application tests
validate implementation locally, not live AWS delivery.
