# Azure retirement — 31 October 2026

The user requested removal of the Elexon acceptance environment after verification.
Both Terraform destroy applies completed successfully: 19 application resources
and five foundation resources destroyed. Both final local Terraform states are
empty. An independent follow-up Azure CLI inventory could not run because automatic
approval review hit an account usage limit; completion is evidenced by Terraform
provider deletion results and final state.

## Scope

Reviewed Terraform destroy plans contain only 19 application resources in
`rg-elexon-etl-dev` and five foundation resources: `rg-elexon-tfstate`, its state
account/container/operator role and `elexon-subscription-monthly` budget.
Other projects' resource groups are outside the plans.

The job, schedule, registry, application storage, identity, monitoring rules,
Container Apps environment, workspace and both Elexon resource groups were deleted.
The state storage and Elexon budget were also removed.

## Local preservation

Private, Git-ignored files under `data/teardown/` contain:

- Application and bootstrap state snapshots from before deletion, plus local
  teardown configurations, plans and resulting state.
- 73 metadata JSON records and 20 currently published Parquet files; the published
  file checksums were verified. These exports total 143,671,715 bytes.
- 122 exported console-log rows in `cloud-backup/console-logs.json`.

This is not a full backup of all Azure blobs: cloud raw files, unpublished Parquet
generations and registry images are deleted. Public source files can be fetched
again. Existing local pipeline data, code and acceptance documentation are retained.
These backups exist on this machine and need separate storage if long-term
retention is required.

Normal infrastructure source retains its destruction safeguards. Only the ignored
teardown copies remove those guards and use local state, allowing the cloud state
account to be retired safely. Bootstrap's normal local state is synchronized after
its destroy completes.

## Redeployment and cost

Run bootstrap again, initialize the recreated remote backend, then deploy the
application infrastructure, rebuild/push the image and configure its new digest.
Ignored development variables are reset to no image and no schedule, with a fixed
pilot date, so redeployment starts without an enabled daily job.

The last available posted budget spend was £0.00, subject to billing delay. This
is not a final invoice. Earlier usage can appear after deletion. The former
£5–10/month planning estimate describes an active deployment, not continuing
charges for deleted resources. Azure may retain soft-deleted recovery data under
its service policies; this teardown does not claim immediate irreversible erasure.
