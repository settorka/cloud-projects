# Maritime intelligence

Python, Apache Kafka, PostgreSQL/TimescaleDB/PostGIS and S3-compatible storage. Real
Fintraffic Digitraffic observations feed an authenticated vessel-history API and
conservative port-visit inference. V1 runs through Compose; V2 uses the same code
and adapters on AWS, with Terraform and a scheduled reference-fetch Lambda.

This is an initial development implementation, not an operational trading service.
The trader's commodity, two initial ports, coverage qualification and support owner
remain unresolved. No AWS resources have been provisioned. The £100/month all-in
ceiling is a deployment constraint, not a verified bill or an automatic spending cap.

## Run V1

Requires Docker Compose v2. Run from this project directory:

```sh
cp -n .env.example .env
docker compose --env-file .env -f deploy/v1/compose.yaml up -d --build
```

The API listens on `http://127.0.0.1:8200`; interactive API documentation is at
`/docs`. Use **Authorize** with the local `API_TOKEN` from the environment file.
The example credentials are local-only. Kafka, PostgreSQL and object storage have
no host-published ports. The live source is contacted immediately when ingestion
starts; stop it with `docker compose ... stop ingestor` when not needed.

```sh
docker compose --env-file .env -f deploy/v1/compose.yaml logs --tail 30 ingestor processor
docker compose --env-file .env -f deploy/v1/compose.yaml down
```

Named volumes survive `down`. Do not use `down -v` unless intentionally deleting
this project's local data.

## Configuration

V1 owns the implementation directly under `src/v1`, with external integrations in
`src/v1/adapters`.
`src/v2` reuses that application through AWS wrappers; it is not another copy of
the business logic.

The project-root `.env` is the runtime configuration source and is ignored by Git.
`.env.example` documents every setting in related groups: application/images, API,
database, Kafka client/topic, Kafka broker, S3, AIS, scheduled ingestion and visit
inference. The existing local `.env` has been preserved/migrated; do not overwrite it.

Python loads `.env` automatically, with exported variables taking precedence. Use
`ENV_FILE=/path/to/config.env` for Python commands using another file. Compose uses
the explicitly supplied `--env-file`; its service `env_file` points at the project
`.env`. Runtime settings are validated before services start: missing values,
invalid numbers, invalid booleans and inconsistent limits fail with the variable
name, without printing secrets. There are no fallback hostnames/topics/buckets in
the v1 application. Source schema, coordinate limits and attribution remain code
contracts, rather than environment-dependent rules.

After changing `.env`, recreate containers with the startup command above. Changing
`POSITION_RETENTION_DAYS` also reconfigures the Timescale retention policy when the
migration service runs. Historical SQL migrations remain immutable. Changing DB
credentials, Kafka cluster ID or listeners requires care with existing volumes.

Numbers described below are the supplied example configuration, not fixed code
limits. Change inference thresholds only after reviewing their effect on existing
visits; changing configuration does not recompute historical visits.

## Implemented API

| Endpoint | Behaviour |
|---|---|
| `GET /health/live` | Process liveness only; does not imply fresh data |
| `GET /v1/status` | Database status, latest timestamps and freshness |
| `GET /v1/vessels/{mmsi}/latest` | Latest observed position, freshness and attribution |
| `GET /v1/vessels/{mmsi}/positions?start=...&end=...` | Up to 24 hours per query, seven-day history, cursor pagination |
| `GET /v1/ports/{id}/visits` | Inferred visits and uncertainty; no port boundaries are seeded |

Timestamps must include timezone offsets. MMSIs contain nine ASCII digits. API
pages default to 100 and cap at 1,000. SQL statements time out after three seconds.
One shared bearer token is suitable for a private development pilot; separate
user identities, token rotation and per-user rate limits are not implemented.

## Real data and boundaries

The source is [Fintraffic's marine MQTT API](https://www.digitraffic.fi/en/marine-traffic/),
topic `vessels-v2/+/location`. `AIS_BBOX` is `west,south,east,north`; the default
Finnish coastal area is a development setting, not Europe-wide coverage. Geographic
filtering occurs in our application, so it does not reduce upstream MQTT traffic.
Position timestamps are epoch **seconds**, not metadata milliseconds. Unavailable
speed/course sentinels become null. The provider has no durable-delivery contract
with this application; collection failures can leave irrecoverable gaps.

Reference port calls are fetched every 15 minutes. Only explicitly allowed fields
are stored; master/agent names, contact information and free text are excluded.
Reference snapshots carry CC BY 4.0 attribution. They are imported directly into
a reference table; live positions use Kafka. Historical source snapshots cannot
overwrite newer imported snapshots.

Port inference remains disabled until an operator supplies a reviewed GeoJSON
Feature with Polygon/MultiPolygon geometry in longitude/latitude WGS84:

```sh
uv run python tools/import_port.py port.geojson --id selected-port --version 1 \
  --provenance 'Source URL, licence and review date'
```

Run that command with `DATABASE_URL` pointing to a reachable database and `API_TOKEN`
set, or copy the tool/file into the Compose application container. The database is
intentionally not exposed to the host by default. Updating geometry creates a new
version; it does not silently rewrite earlier inferred visits.

Arrival requires three observations spanning at least five minutes. Departure
requires two observations outside a 250 m exit buffer spanning at least two
minutes. Gaps over ten minutes reset inference without fabricating departure.
Open visits become uncertain after ten minutes without evidence. Earlier arrivals
are never automatically closed merely because new evidence appears after a gap.
The processor uses only increasing event time for live inference; delayed data
is stored in history but does not retroactively recompute visits in this slice.

## Shared code, explicit versions

```text
src/v1/bootstrap.py  local application entry point
src/v1/settings.py   validated grouped .env configuration
src/v1/api.py        authenticated read API
src/v1/models.py     observation contract and freshness
src/v1/visits.py     port-visit state machine
src/v1/services.py   reference snapshot operation
src/v1/workers.py    ingest, process and reference jobs
src/v1/adapters/     Digitraffic, Kafka, PostgreSQL, S3 and migrations
src/v2/             AWS wrappers reusing v1
deploy/v1/          Compose and integration-test profile
deploy/v2/          AWS Compose, Terraform and bootstrap
.env.example        grouped, commented configuration template
migrations/         checksummed SQL migrations
tests/              unit, configuration and real dependency tests
```

The S3 adapter uses SeaweedFS in V1 and Amazon S3 in V2. Endpoint, addressing style
and credential configuration change; business logic does not. Kafka and the
TimescaleDB/PostGIS image remain self-hosted in AWS to control cost. V1 owns the application. V2 reuses its modules and adapters with AWS execution wrappers.

## Verification

```sh
uv sync --frozen
uv run ruff check src tests tools
uv run pytest -q
docker compose --env-file .env -f deploy/v1/compose.yaml \
  -f deploy/v1/compose.test.yaml --profile test run --build --rm tests
```

Host tests intentionally skip dependency contracts unless `INTEGRATION=1` is set.
The Compose test runner enables them against actual PostgreSQL, Kafka and S3.
The geospatial contract uses clearly synthetic geometry/identifiers and cleans up
its records. Test observations sent to the shared Kafka topic may be quarantined
by the live processor; do not run development contracts against an operational host.

Data: [Fintraffic Digitraffic](https://www.digitraffic.fi/en/marine-traffic/), CC BY 4.0.
Adapted outputs include source attribution. See [architecture](docs/architecture.md)
and [operations](docs/operations.md).

## OpenTelemetry

The application sends traces, metrics and logs to the Compose OpenTelemetry Collector. Root traces use 1% sampling. The local collector prints signals for inspection; the AWS collector configuration exports to CloudWatch and X-Ray. See [telemetry](docs/telemetry.md) for signal names, privacy rules and verification. AWS provisioning follows in v2.
