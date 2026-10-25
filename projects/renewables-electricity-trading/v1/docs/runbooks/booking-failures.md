# Booking failures and unknown outcomes

Record request ID, operation, portfolio and idempotency key in your private incident notes; do not record the token. Check HTTP status and body before retrying.

- 401: missing/invalid token.
- 403: actor lacks portfolio membership or write role.
- 400/413: invalid shape, quantity, delivery horizon, boundary or request size.
- 409: key reused with different input, stale revision, cancelled trade or blocked portfolio.
- 422: persisted business rejection; inspect forecast freshness and limits.
- 503/timeout/disconnect: outcome may be unknown. Retry the **same operation, key and payload**.

Diagnosis: inspect Trading JSON logs, `/v1/status`, portfolio positions/breaches and current trade history. Check PostgreSQL blocking sessions from a privileged local shell:

```sh
docker compose --env-file .env exec -T postgres psql -U postgres -d renewables -c "SELECT pid, state, wait_event_type, wait_event, now()-xact_start AS age FROM pg_stat_activity WHERE datname='renewables';"
```

Do not kill transactions or submit a new key merely because the client timed out. External I/O is not part of booking; an Elexon outage is relevant only if required local forecasts expire.

Recovery: correct the underlying data/permission, or allow lock pressure to clear. Re-evaluating a previously rejected proposal requires a new key; replay returns the original decision. For blocked writes follow position reconciliation.

Verification: retrieve the accepted trade and its revision, verify one position effect, then reconcile. If results conflict, restrict the affected portfolio and retain evidence.
