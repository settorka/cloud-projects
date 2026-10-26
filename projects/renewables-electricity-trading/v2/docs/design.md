# Design and invariants

## Ownership

Trading is the financial source of truth. Market Data owns inputs; Valuation owns computed results. Shared database infrastructure is a cost compromise, not shared table ownership. PostgreSQL users have their own schema as their search path. Schema changes belong to that service. Local tests use an isolated administrator-created **test database**, not the runtime role.

## Booking consistency

A transaction acquires an actor/idempotency-key advisory lock, then the portfolio row lock. Every trade mutation, forecast application, limit change and reconciliation uses the portfolio protocol. There are no network calls during booking. The portfolio lock protects initial position-row creation too. Different portfolios can proceed independently; one portfolio is a deliberate serialization point.

The transaction commits the effective trade revision, gross position delta, decision audit and one outbox row per destination together. Both accepted and valid business-rejected requests retain their decisions. Retry with the same raw JSON value and key replays the original result even after its delivery interval becomes historical; a changed payload conflicts. Whitespace/key ordering do not affect the hash, but different JSON representations of numeric values do.

Amendments require the expected revision, reverse old contributions and apply new contributions atomically. Cancelled revisions carry no effective legs. History is retained; no delete API exists. A risk user changes limits with an expected revision and reason. Portfolio membership is service-local authorization; there is no public signup.

Expected exposure = forecast + purchases − sales. Actual exposure = metered generation + purchases − sales. These are simplified internal measures, not official GB imbalance settlement. Limits use MWh, not currency/VaR/credit. Net zero does not erase gross obligations.

For a currently breached interval, the distance outside the configured bounds must strictly decrease. A proposal cannot create a new opposite-side breach. This policy applies per affected interval. A forecast change can legitimately create a breach after an earlier decision.

## Asynchronous delivery

Envelopes have a UUID, schema version, entity ID, source revision and occurrence time. The canonical contract is copied into independently built images; `tools/check_contracts.py` prevents divergence. Local publishers send directly to consumer queues. V2 can publish through EventBridge, with destination-specific rules forwarding envelopes to SQS without changing the booking transaction.

An outbox relay locks one pending destination record, sends, then records publication. A crash after send may repeat delivery. Consumer transactions serialize through a service-local guard, apply monotonic source revisions, record inbox identity, then acknowledge SQS. This is idempotent application over at-least-once transport, not exactly-once networking. The guard prioritizes V1 correctness over maximum consumer throughput.

Expired inputs remain stored and visible. Unknown/malformed events fail and eventually reach the configured DLQ. DLQs are not automatically replayed. Queue/inbox/outbox retention is manual in V1; growth must be monitored and no cleanup may discard undelivered work.

## Valuation

Purchase mark = MWh × (mark − contract price); sale mark uses the opposite sign. Round each leg to GBP pennies using HALF_EVEN, then sum. Missing marks yield `INCOMPLETE` with no unqualified total; expired marks yield `STALE`. Results retain marks, price revisions, trade revisions and method. `CURRENT` means current relative to applied local inputs, not proof all upstream events have arrived. Results are append-only. Automatic calculations occur when trade/price events apply; explicit runs are available through the API.

## Deliberate V1 limits

No official notifications, exchange execution, clearing, collateral, tax, derivatives pricing or real settlement. One currency, GB only. AWS readiness and production security are later milestones. Demo profiles bind to loopback and use known tokens. No full global-latency or high-availability promise. External 1,000-request/s tests report admission and completion independently.


## V2 additions

[Durable process attempts and W3C tracing](process-lineage.md) augment existing business audit. [AWS operating bounds](aws-design.md) define the single-host development deployment and explicitly unproven acceptance targets.
