# AWS credentials and access

Owner: project operator. Lightsail cannot use an EC2 instance profile. Terraform creates an IAM user with narrow bus/queue, backup upload, ECR pull and telemetry permissions. It creates no keys. All services share this host identity; this is a development compromise.

Use an authenticated administrator to create one access key out-of-band. Do not paste it into commands, chat, Git, Terraform variables, state, user-data or image builds. Install the standard `[default]` credentials file on the host at `/opt/renewables/credentials/credentials`. Root owns `/opt/renewables` with mode 0700. The credentials directory/file need 0755/0644 inside that protected parent so UID 10001 containers can read the read-only bind mount. Keep `v2.env` root-owned mode 0600. Anyone controlling Docker or root can read secrets.

Review access monthly and rotate keys at least every 30 days or immediately after suspected exposure. Create a second key, replace the file atomically, restart APIs/workers/collector to refresh credential caches, and verify publication, consumption, telemetry and backup. Deactivate the old key, observe a successful operating cycle, then delete it. Never leave two active keys indefinitely.

A compromised runtime key cannot administer infrastructure, delete backups or push images under this policy. It can read/modify queue traffic and publish domain events, so rotate immediately, stop accepting trades if integrity is uncertain, inspect inbox/audit/positions and reconcile. Disable the IAM user keys during full teardown.

SSH keys and operator AWS credentials are separate. Restrict the runtime user's access to its specific resources. The operator needs additional provisioning, ECR push and backup-download permissions; do not attach AdministratorAccess to the runtime user.
