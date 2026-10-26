# Renewables electricity trading — V2 development baseline

> V2 adds explicit OpenTelemetry instrumentation, durable event-attempt state machines, an AWS development runtime and Terraform configuration. AWS deployment and performance acceptance still require an authenticated plan and real deployment checks.

See [configuration and v2.env loading](docs/configuration.md).

See [AWS architecture, budget and quantified bounds](docs/aws-design.md), [process lineage](docs/process-lineage.md) and [AWS runbooks](docs/runbooks/README.md). V1 remains the preserved local reference.

V2 uses Compose project `renewables-electricity-trading-v2`, an independent database volume and default ports 8101–8103. V1 keeps its existing project identity, data and ports 8001–8003. Override V2 ports through its environment file. Do not point both versions at one database.

A simulated Great Britain renewable electricity trading desk, implemented as three Django services. It books proposed bilateral trades, enforces interval position limits, applies versioned generation inputs and calculates simplified trade marks. It does not execute exchange orders, move money or submit official market notifications.

## Quick start

Requirements: Docker Engine/Desktop with Compose v2, GNU Make (optional), and uv for host-side tooling. Allow roughly 4 GB of available Docker memory. Run all commands in this directory.

```sh
cp v2.env.example v2.env
make up
make demo
```

`make up` builds the images, initializes three isolated PostgreSQL schemas, runs migrations and seeds local users. Application ports bind **only to loopback**:

- Trading: http://127.0.0.1:8101
- Market Data: http://127.0.0.1:8102
- Valuation: http://127.0.0.1:8103

Use the seeded tokens from your local environment. Example with the example-only trader token:

```sh
curl -H 'Authorization: Token 1111111111111111111111111111111111111111'   http://127.0.0.1:8101/v1/portfolios/demo/positions
```

Read the first returned interval and use its `start` when booking. `make demo` publishes four **synthetic** intervals at 13:00 UTC tomorrow; allow bounded worker catch-up. See [API contracts](docs/api.md) and [the startup runbook](docs/runbooks/local-startup.md).

```sh
make test       # Real PostgreSQL tests, including competing transactions
make e2e        # Actual HTTP + broker + stopped-worker recovery + schema permissions
make lint
make load       # 100 small seeded requests at 10/s; not a capacity claim
make reconcile
make down       # Preserve database volume
```

`make e2e` creates a separate portfolio each run. It requires host Docker access and uses the same `ENV_FILE` selected by Make. The simulator profile can be invoked with explicit parameters as documented in the load-testing runbook.

## Architecture

- **Trading:** authoritative trades/revisions, gross positions, limits, portfolio permissions, forecast copies and metered exposure. Booking, amendments and cancellation use one atomic transaction and a portfolio lock. Idempotency is actor-scoped across mutation routes.
- **Market Data:** versioned synthetic portfolio inputs and separately stored Elexon aggregate source records. Bounded async HTTP requests; real national data never silently becomes a private asset forecast.
- **Valuation:** event-driven local trade/price copies, versioned valuation results, missing/stale statuses and results API. Simple undiscounted fixed-price marks, not total business profit.
- **PostgreSQL:** one database with `trading`, `market_data`, `valuation` schemas and service-specific users. It is a shared infrastructure failure boundary.
- **ElasticMQ:** SQS-compatible local queues plus DLQs. Consumer commits precede message deletion. Outbox deliveries are tracked per destination; no AWS EventBridge emulator is needed.

Each service owns its `pyproject.toml`, `uv.lock`, Python 3.11 environment and image. API and worker processes reuse that image. No cross-service ORM models or table reads.

## V1 decisions and limits

See [design and invariants](docs/design.md), [observability](docs/observability.md), [test strategy](docs/testing.md) and [runbooks](docs/runbooks/README.md).

- GBP, GB half-hour intervals; 46/48/50-period dates handled explicitly.
- Next seven local delivery dates, maximum 50 legs on one delivery day, 64 KiB booking body, page limit 100.
- Quantity precision: 0.001 MWh; prices: 0.0001 GBP/MWh. Synthetic scenario and source units remain labelled.
- Example limits: −20 to +200 MWh; configure with the risk role.
- A pre-existing breach may only be reduced by a proposed trade, without creating an opposite breach. Missing/expired forecasts block affected proposals. Cancelling/amending delivered intervals is not supported.
- Accepted mutations never rely on a live external API request. An accepted request is a simulated internal commitment, not evidence of an external contract.
- One API process with four threads; workers default to two handlers (configurable 1–8). PostgreSQL connection, statement and lock waits are bounded. No claim of sustained 1,000 accepted trades/s.
- Local seeded tokens and HTTP are for loopback development only. Production authentication/TLS, AWS IAM, alert delivery and Terraform are V2/V3 work.

## Real Elexon data

```sh
docker compose --env-file v2.env exec -T market-data python manage.py import_elexon --dataset wind
make live   # Opt-in scheduler, wind import every five minutes
```

The importer retains raw source fields, publication times where supplied, content identities and ingestion runs. A failed/empty response is recorded as a failure. Query windows are at most 24 hours; at most two concurrent HTTP requests and three attempts per request. Live API availability does not affect fixture tests or booking.

REST APIs are public and require no key. Coverage and publication cadence vary by dataset; polling frequency is not source freshness. Elexon aggregate data does **not** supply our fictional portfolios, counterparty trades or a complete forward curve. Synthetic prices drive demo valuations; no claim is made that they are executable quotes. [Developer portal](https://developer.data.elexon.co.uk/).

Contains BMRS data © Elexon Limited copyright and database right 2026. [BMRS licence](https://www.elexon.co.uk/bsc/data/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/). Source data may contain third-party rights; retain provenance and do not imply endorsement.

## Delivery milestones

V1 preserves the local business workflow. V2 adds tracing, durable process lineage and a Terraform-configured Lightsail/SQS/EventBridge development environment under the $50 budget profile. AWS deployment acceptance is pending; Fargate and RDS are outside this profile. V3 covers production operating requirements and measured readiness. No cloud resources have been provisioned by these changes.
