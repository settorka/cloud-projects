import hashlib
from datetime import timedelta
from pathlib import Path

import psycopg


def migrate(settings):
    directory = settings.migrations_dir
    with psycopg.connect(
        settings.database_url, connect_timeout=settings.db_connect_timeout_seconds
    ) as conn:
        conn.execute("SELECT pg_advisory_xact_lock(19042026)")
        conn.execute("""CREATE TABLE IF NOT EXISTS schema_migrations
            (name text PRIMARY KEY,checksum text NOT NULL,applied_at timestamptz DEFAULT now())""")
        paths = sorted(Path(directory).glob("*.sql"))
        if not paths:
            raise ValueError("No SQL migrations found")
        for path in paths:
            body = path.read_text()
            checksum = hashlib.sha256(body.encode()).hexdigest()
            old = conn.execute(
                "SELECT checksum FROM schema_migrations WHERE name=%s", (path.name,)
            ).fetchone()
            if old and old[0] != checksum:
                raise ValueError(f"Applied migration changed: {path.name}")
            if not old:
                conn.execute(body, prepare=False)
                conn.execute(
                    "INSERT INTO schema_migrations(name,checksum) VALUES (%s,%s)",
                    (path.name, checksum),
                )
        # Keep historical migrations immutable; configure the runtime retention policy
        # here so changing .env also updates the existing database on the next migration.
        retention = timedelta(days=settings.position_retention_days)
        matching = conn.execute(
            """SELECT 1 FROM timescaledb_information.jobs
            WHERE hypertable_name='positions' AND proc_name='policy_retention'
            AND (config->>'drop_after')::interval=%s""",
            (retention,),
        ).fetchone()
        if not matching:
            conn.execute("SELECT remove_retention_policy('positions',if_exists=>true)")
            conn.execute("SELECT add_retention_policy('positions',%s::interval)", (retention,))
