CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS positions (
  event_time timestamptz NOT NULL,
  event_id text NOT NULL,
  mmsi text NOT NULL,
  source text NOT NULL,
  received_at timestamptz NOT NULL,
  location geometry(Point,4326) NOT NULL,
  sog double precision,
  cog double precision,
  raw jsonb NOT NULL,
  PRIMARY KEY (event_time,event_id)
);
SELECT create_hypertable('positions','event_time',if_not_exists=>true);
CREATE INDEX IF NOT EXISTS positions_vessel_time ON positions(mmsi,event_time DESC,event_id DESC);
CREATE INDEX IF NOT EXISTS positions_location ON positions USING gist(location);
SELECT add_retention_policy('positions',INTERVAL '7 days',if_not_exists=>true);

CREATE TABLE IF NOT EXISTS latest_positions (
  mmsi text PRIMARY KEY,
  event_time timestamptz NOT NULL,
  event_id text NOT NULL,
  source text NOT NULL,
  received_at timestamptz NOT NULL,
  location geometry(Point,4326) NOT NULL,
  sog double precision,
  cog double precision
);
CREATE TABLE IF NOT EXISTS port_areas (
  id text NOT NULL,
  version integer NOT NULL CHECK(version>0),
  name text NOT NULL,
  provenance text NOT NULL,
  boundary geometry(MultiPolygon,4326) NOT NULL,
  active boolean NOT NULL DEFAULT true,
  PRIMARY KEY(id,version),
  CHECK(ST_IsValid(boundary))
);
CREATE UNIQUE INDEX IF NOT EXISTS port_one_active_version ON port_areas(id) WHERE active;
CREATE TABLE IF NOT EXISTS visit_states (
  mmsi text NOT NULL,
  port_id text NOT NULL,
  port_version integer NOT NULL,
  phase text NOT NULL,
  since timestamptz,
  last_at timestamptz,
  count integer NOT NULL,
  arrival_at timestamptz,
  PRIMARY KEY(mmsi,port_id,port_version)
);
CREATE TABLE IF NOT EXISTS port_visits (
  mmsi text NOT NULL,
  port_id text NOT NULL,
  port_version integer NOT NULL,
  arrival_at timestamptz NOT NULL,
  confirmed_at timestamptz NOT NULL,
  departure_at timestamptz,
  last_evidence_at timestamptz NOT NULL,
  arrival_evidence text NOT NULL,
  departure_evidence text,
  algorithm_version text NOT NULL DEFAULT 'dwell-v1',
  classification text NOT NULL DEFAULT 'inferred',
  PRIMARY KEY(mmsi,port_id,port_version,arrival_at)
);
CREATE TABLE IF NOT EXISTS quarantine (
  topic text NOT NULL,
  partition_id integer NOT NULL,
  offset_id bigint NOT NULL,
  reason text NOT NULL,
  payload text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY(topic,partition_id,offset_id)
);
CREATE TABLE IF NOT EXISTS reference_imports (
  object_key text PRIMARY KEY,
  imported_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS reported_port_calls (
  provider_id text PRIMARY KEY,
  payload jsonb NOT NULL,
  object_key text NOT NULL,
  captured_at timestamptz NOT NULL,
  imported_at timestamptz NOT NULL DEFAULT now()
);
