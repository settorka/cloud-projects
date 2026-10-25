# Verification strategy

`make test` builds dev-dependency images and runs pytest in isolated PostgreSQL test databases. Runtime services never receive the test administrator credentials. `make e2e` uses running Compose services and actual ElasticMQ delivery, creating a unique portfolio. `make lint` checks formatting, lint and canonical event schemas.

Unit tests cover GB clock-change dates, arithmetic and versioning. Database integration covers rollback, multi-interval rejection, amendment/cancellation, authorization, missing/expired forecasts, idempotency and independent reconciliation. Transactional tests open independent connections and synchronize threads to force overlapping submissions. Market Data uses HTTPX mock transports and pytest-asyncio to prove bounded HTTP concurrency. Valuation tests cover sign, stale/missing marks, cancellation and out-of-order revisions. Outbox failure/retry tests run for each service.

The end-to-end test verifies source-to-Trading delivery, booking/retry, valuation, stopped-consumer recovery, a revised forecast breach, a covering purchase, reconciliation and runtime schema permission denial. Broker redelivery/DLQ checks are documented in the queue runbook; actual AWS visibility, IAM and EventBridge tests are V2.

No routine test calls Elexon. Live calls are opt-in, save source provenance, and do not determine deterministic correctness. A load generator uses an open-loop schedule with bounded in-flight requests; generator shedding and schedule lag are reported, not concealed. Idempotent replays and business rejections are separate from unique accepted throughput. Never claim 1,000 accepted trades/s from a configured arrival rate alone.

See `docs/verification.md` for the actual run evidence and limitations.
