# V2 baseline verification

V2 begins as a copy of tracked V1 files. Local state, virtual environments, credentials, backups and caches are excluded. Business-service implementations, migrations, dependencies and event contracts are unchanged.

Only version documentation, Compose identity/default ports and corresponding local tool endpoints differ. AWS infrastructure and tracing/lineage changes remain future V2 work.

Verified locally on 25 October 2026:

- V1 relocation: all 137 original tracked files retained byte-for-byte; lint, contracts and end-to-end scenario passed after relocation.
- V2 parity: all 106 tracked service files match V1, including migrations and dependency locks.
- V2 Compose configuration and startup passed; all three APIs became healthy on ports 8101–8103.
- Ruff lint/format checks and event-contract copy verification passed.
- Queue visibility, redelivery and dead-letter checks passed.
- PostgreSQL test suites: 41 passed (Trading 22, Market Data 10, Valuation 9).
- End-to-end scenario passed: booking, retry, position, valuation, worker recovery, forecast breach, cover, reconciliation, authorization and schema isolation.
- Separate PostgreSQL volumes confirmed: `renewables-electricity-trading_postgres-data` for V1 and `renewables-electricity-trading-v2_postgres-data` for V2.

CI now validates both runnable versions independently. Existing performance and recovery evidence in the copied documentation is inherited V1 evidence unless explicitly stated otherwise; the folder copy establishes no new capacity or AWS readiness claim.
