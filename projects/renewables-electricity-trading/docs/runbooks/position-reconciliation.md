# Position discrepancy

Impact: stored gross position may be wrong. Restrict writes to the affected portfolio. The reconciliation command detects and persists mismatches and sets its write-block flag.

```sh
docker compose --env-file .env exec -T trading python manage.py reconcile demo
```

A nonzero exit signals mismatch. Preserve the reconciliation record, trade revisions and logs. The calculation independently sums effective active trade legs; it does not overwrite history.

After identifying the cause, repair aggregates from authoritative trades:

```sh
docker compose --env-file .env exec -T trading python manage.py reconcile demo --repair
docker compose --env-file .env exec -T trading python manage.py reconcile demo
```

**Repair modifies position aggregates.** It does not unblock on its own. Only a subsequent clean independent check clears the block. This is a local operator command, not a trader API permission.

Verification: zero mismatches, expected gross purchases/sales, correct forecast-based exposure and intact trade history. If trade history itself is corrupted, aggregate repair is insufficient: stop writes and investigate/restore first. Do not use a direct SQL edit as an undocumented business correction.
