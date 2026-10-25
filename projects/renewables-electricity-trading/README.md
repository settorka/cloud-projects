# Renewables electricity trading — V1

A simulated Great Britain renewable electricity trading desk, implemented as three Django services. It books proposed bilateral trades, enforces interval position limits, applies versioned generation inputs and calculates simplified trade marks. It does not execute exchange orders, move money or submit official market notifications.

## Quick start

Requirements: Docker Engine/Desktop with Compose v2, GNU Make (optional), and uv for host-side tooling. Allow roughly 4 GB of available Docker memory. Run all commands in this directory.

```sh
cp .env.example .env
make up
make demo
```

`make up` builds the images, initializes three isolated PostgreSQL schemas, runs migrations and seeds local users. Application ports bind **only to loopback**:

- Trading: http://127.0.0.1:8001
- Market Data: http://127.0.0.1:8002
- Valuation: http://127.0.0.1:8003

Use the seeded tokens from your local environment. Example with the example-only trader token:

```sh
curl -H 'Authorization: Token 1111111111111111111111111111111111111111'   http://127.0.0.1:8001/v1/portfolios/demo/positions
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
docker compose --env-file .env exec -T market-data python manage.py import_elexon --dataset wind
make live   # Opt-in scheduler, wind import every five minutes
```

The importer retains raw source fields, publication times where supplied, content identities and ingestion runs. A failed/empty response is recorded as a failure. Query windows are at most 24 hours; at most two concurrent HTTP requests and three attempts per request. Live API availability does not affect fixture tests or booking.

REST APIs are public and require no key. Coverage and publication cadence vary by dataset; polling frequency is not source freshness. Elexon aggregate data does **not** supply our fictional portfolios, counterparty trades or a complete forward curve. Synthetic prices drive demo valuations; no claim is made that they are executable quotes. [Developer portal](https://developer.data.elexon.co.uk/).

Contains BMRS data © Elexon Limited copyright and database right 2026. [BMRS licence](https://www.elexon.co.uk/bsc/data/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/). Source data may contain third-party rights; retain provenance and do not imply endorsement.

## Delivery milestones

V1: local Compose and verified business workflow. V2: AWS dev-ready Terraform/Fargate/SQS/Scheduler, existing OIDC reuse and live integration checks. V3: production operating procedures, restoration evidence, security, cost and measured service-level limits. No cloud resources are provisioned by this project yet.
