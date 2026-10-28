# Maritime intelligence — V1

A local Python backend using real Fintraffic AIS observations, Apache Kafka and
PostgreSQL with TimescaleDB/PostGIS. One application owns ingestion, validation,
position history, port-visit inference and an authenticated FastAPI read API.

## Run

From this project directory, with Docker Compose v2 installed:

```sh
cp -n .env.example .env
docker compose --env-file .env -f deploy/v1/compose.yaml up -d --build
```

API documentation: http://127.0.0.1:8200/docs. Authorize with the local `API_TOKEN`.
The application contacts the real AIS source immediately. Kafka, PostgreSQL and
S3-compatible storage have no host-published ports. Stop the stack with the same
Compose command followed by `stop`; volumes remain intact.

## Configuration

The ignored project `.env` is grouped and commented; `.env.example` is the tracked
template. Python loads it automatically; explicit environment variables win.
Compose forwards the same runtime overrides. Missing/invalid required values fail
before startup without printing secrets. Example credentials are local-only.

`AIS_BBOX` is west,south,east,north. The supplied Finnish area is a development
setting, not European coverage. API history ranges, page sizes, freshness limits,
Kafka settings, storage endpoints and inference thresholds are configurable.
Database/cluster credentials on persisted volumes require explicit migration when
changed; changing an environment file alone does not rotate a database password.

## Behaviour

- Latest positions never regress when delayed observations arrive.
- Duplicate deliveries create no second durable observation or visit.
- Kafka offsets commit after database persistence or durable quarantine.
- Position history is a Timescale hypertable; default retention is seven days.
- PostGIS stores positions/port polygons and evaluates geofences.
- No port polygons are fabricated or seeded. Import an operator-reviewed GeoJSON
  polygon with `tools/import_port.py`, a port ID, version and provenance.
- Arrival requires the supplied three observations over five minutes; departure
  requires two outside a 250 m exit buffer over two minutes. A ten-minute gap
  resets inference and leaves open visits uncertain rather than inventing departure.
- Reference port calls are collected every 15 minutes via S3-compatible snapshots;
  only approved fields are retained, excluding master/agent contacts and free text.

## API

All data endpoints require a bearer token:

- `GET /v1/status`
- `GET /v1/vessels/{mmsi}/latest`
- `GET /v1/vessels/{mmsi}/positions?start=...&end=...`
- `GET /v1/ports/{id}/visits`

`/health/live` is process liveness, not proof of fresh upstream data. Timestamps
require timezone offsets; example history queries cover up to 24 hours and page
sizes cap at 1,000. Source age and coverage limitations remain visible.

## Verify

```sh
uv sync --frozen
uv run ruff check src tests tools
uv run pytest -q
docker compose --env-file .env -f deploy/v1/compose.yaml -f deploy/v1/compose.test.yaml --profile test run --build --rm tests
```

The host suite skips four real-dependency contracts; the Compose runner enables
those against real Kafka, TimescaleDB/PostGIS and SeaweedFS. CI starts no AIS feed.

This is a development implementation. One trader workflow, operational boundaries,
source coverage and support commitments still need qualification. A single shared
API token, no per-user throttling and one Kafka/database node limit operational use.
Raw Kafka archiving, retroactive inference correction and automated retention of
non-position tables are deferred. No AWS resources are created by this version.

Data: [Fintraffic Digitraffic](https://www.digitraffic.fi/en/marine-traffic/), CC BY 4.0.
Adapted outputs include source attribution. See [architecture](docs/architecture.md)
and [operations](docs/operations.md).

## OpenTelemetry

The application sends traces, metrics and logs to the Compose OpenTelemetry Collector. Root traces use 1% sampling. The local collector prints signals for inspection; the AWS collector configuration exports to CloudWatch and X-Ray. See [telemetry](docs/telemetry.md) for signal names, privacy rules and verification. AWS provisioning follows in v2.
