# Market-data import failure or stale coverage

Diagnosis: check `/v1/sources`, `ImportRun.state/error`, market-data logs and `GET /v1/status`. Separate source publication age from importer success and Trading application age. Dataset cadence varies; WIND is not published every five minutes.

```sh
docker compose --env-file .env exec -T market-data python manage.py import_elexon --dataset wind
```

The command requests at most the previous 24 hours by default. Use explicit aware `--start` and `--end` to retry a bounded historical window. Do not run many parallel backfills. Empty/malformed results fail rather than silently replace usable data. Repeated retrieval deduplicates source content. Source aggregate records do not update fictional portfolio forecasts.

For the local demo only, `make demo` publishes clearly synthetic portfolio forecasts/marks. It is not an automatic or concealed replacement for real observations. `replay <path>` can load explicit synthetic fixture values; keep original timestamps when testing duplicates.

Verification: import run succeeded, records have source identities/publication time where supplied, and fixture-driven portfolio state remains separately labelled. If a live source remains unavailable, keep its failure visible and continue deterministic tests offline.
