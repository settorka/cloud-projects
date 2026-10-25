# V1 HTTP and event contracts

No trailing slashes. JSON APIs require `Authorization: Token <token>`. Local examples use seeded trader/risk/viewer identities. Decimal quantities and financial outputs are strings. Liveness/readiness are unauthenticated; metrics and status require a token.

## Trading (port 8001)

- `GET /v1/portfolios`
- `GET /v1/portfolios/{id}/positions?limit=100&offset=0`
- `GET /v1/portfolios/{id}/breaches` (first 100, count included)
- `PUT /v1/portfolios/{id}/limits` (risk membership)
- `POST /v1/trades`
- `GET /v1/trades/{uuid}` (current revision + history)
- `POST /v1/trades/{uuid}/amendments`
- `POST /v1/trades/{uuid}/cancellations`

Booking/amendment body (replace start with an actual seeded future interval):

```json
{"portfolio":"demo","counterparty":"grid-buyer","direction":"SELL","reason":"Sell forecast generation","legs":[{"start":"2026-10-26T13:00:00Z","quantity":"80.000","price":"70.0000"}]}
```

Supply an actor-scoped `Idempotency-Key` (1–100 characters). Amendment additionally needs `expected_revision`; cancellation needs only `expected_revision` and `reason`. Limit body: `{"lower":"-20.000","upper":"200.000","expected_revision":1,"reason":"Risk review"}`.

Responses: 201 booking; 200 amendment/cancellation/replay; 400 invalid input; 401 missing identity; 403 denied portfolio/role; 409 conflicting key, stale revision, blocked portfolio or cancelled trade; 422 persisted business rejection; 503 retryable database issue. A timeout leaves the outcome unknown: retry the same key/payload. `Idempotent-Replay` distinguishes replay. Accepted and business-rejected responses include a persisted `decision` input snapshot with limit values, forecast versions/quantities and interval exposure calculations. New input or a new evaluation needs a new key.

## Market Data (port 8002)

`GET /v1/sources`: import summaries and provenance counts. `GET /v1/source-records?dataset=wind&limit=100&offset=0` exposes bounded raw aggregate records with provenance (datasets: wind, generation, prices). Input mutation is through documented CLI commands, not a public ingestion API. `scenario` emits four synthetic intervals; `replay <file>` reads explicit versioned synthetic fixture values; `import_elexon` stores real aggregate source records.

## Valuation (port 8003)

- `POST /v1/valuation-runs`, body `{"portfolio":"demo"}`
- `GET /v1/valuation-runs/{uuid}`

Returns state, total (null for incomplete), leg results and exact applied input versions. Old runs retain old state and are not silently rewritten as current prices change.

## Operational endpoints (all services)

- `GET /health/live`: process response, no database check.
- `GET /health/ready`: database connectivity.
- `GET /metrics`: Prometheus text; API counters plus persisted outbox/job signals.
- `GET /v1/status`: worker/import/reconciliation status and pending outbox count.

## Events

Canonical envelope: `contracts/event.schema.json`. Supported types: `trade.changed`, `forecast.updated`, `price.updated`, `meter.updated`. Trade events contain complete latest snapshots, not increments; source revision is authoritative. Forecast/meter updates route to `trading-input`, trade/price updates to `valuation-input`. Consumers reject unsupported types/versions and deduplicate event IDs. Adding a consumer means another destination/queue, not sharing a competing-consumer queue.
