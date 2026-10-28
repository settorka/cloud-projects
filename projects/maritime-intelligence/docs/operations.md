# V1 operations

Inspect Compose logs for `ingestor`, `processor`, `references`, `postgres` and
`kafka`. `/health/live` means the API process is alive. Authenticated `/v1/status`
shows database readiness and source timestamps, not Kafka lag or complete coverage.

Database failures leave offsets uncommitted; Compose restarts the worker. Invalid
records are quarantined before advancing their offsets. Reconnects cannot recover
unreceived MQTT observations. Delayed positions do not overwrite newer latest state.

Kafka retention is 48 hours or its per-partition byte cap, whichever removes data
first. The example has three partitions and a 5 GiB cap per partition. Timescale
position retention is configurable; chunk deletion is periodic. Quarantine, visits,
latest-state and reference tables currently require operator growth/cleanup review.

Named volumes survive stop/down. Never use `down -v` against data you intend to
keep. Host tests use synthetic identifiers/geometry only for isolated contracts.
Do not run those contracts against an operational database.

A single node/host, shared API token and unqualified source coverage make this a
private development baseline, not a production trading or navigation service.
