import json
from datetime import UTC, datetime

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from v1.telemetry import traced
from v1.visits import VisitState, advance

PROJECTION = """mmsi,event_time,event_id,source,received_at,
                ST_X(location) AS lon,ST_Y(location) AS lat,sog,cog"""


class PostgresRepository:
    def __init__(self, settings):
        self.settings = settings
        self.dsn = settings.database_url

    def connect(self):
        return psycopg.connect(
            self.dsn,
            connect_timeout=self.settings.db_connect_timeout_seconds,
            row_factory=dict_row,
            options=f"-c statement_timeout={self.settings.db_statement_timeout_ms}",
        )

    @traced("postgres.save")
    def save(self, observation, raw):
        o = observation
        args = (
            o.event_time,
            o.event_id,
            o.mmsi,
            o.source,
            o.received_at,
            o.lon,
            o.lat,
            o.sog,
            o.cog,
        )
        with self.connect() as conn:
            inserted = conn.execute(
                """INSERT INTO positions
                VALUES (%s,%s,%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s,%s,%s)
                ON CONFLICT DO NOTHING RETURNING event_id""",
                (*args, Jsonb(raw)),
            ).fetchone()
            if not inserted:
                return False
            latest = conn.execute(
                """INSERT INTO latest_positions
                (event_time,event_id,mmsi,source,received_at,location,sog,cog)
                VALUES (%s,%s,%s,%s,%s,ST_SetSRID(ST_MakePoint(%s,%s),4326),%s,%s)
                ON CONFLICT(mmsi) DO UPDATE SET
                  event_time=excluded.event_time,event_id=excluded.event_id,
                  source=excluded.source,received_at=excluded.received_at,
                  location=excluded.location,sog=excluded.sog,cog=excluded.cog
                WHERE excluded.event_time>latest_positions.event_time
                RETURNING mmsi""",
                args,
            ).fetchone()
            if latest:
                self._advance_visits(conn, o)
        return True

    def _advance_visits(self, conn, o):
        ports = conn.execute(
            """SELECT id,version,
            ST_Covers(boundary,ST_SetSRID(ST_MakePoint(%s,%s),4326)) AS inside,
            NOT ST_DWithin(boundary::geography,
                ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography,%s) AS beyond_exit
            FROM port_areas WHERE active""",
            (o.lon, o.lat, o.lon, o.lat, self.settings.exit_buffer_metres),
        ).fetchall()
        for port in ports:
            key = (o.mmsi, port["id"], port["version"])
            record = conn.execute(
                """SELECT phase,since,last_at,count,arrival_at
                FROM visit_states WHERE mmsi=%s AND port_id=%s AND port_version=%s
                FOR UPDATE""",
                key,
            ).fetchone()
            state, transition = advance(
                VisitState(**record) if record else VisitState(),
                o.event_time,
                port["inside"],
                port["beyond_exit"],
                self.settings.visit_rules,
            )
            conn.execute(
                """INSERT INTO visit_states VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT(mmsi,port_id,port_version) DO UPDATE SET
                phase=excluded.phase,since=excluded.since,last_at=excluded.last_at,
                count=excluded.count,arrival_at=excluded.arrival_at""",
                (*key, state.phase, state.since, state.last_at, state.count, state.arrival_at),
            )
            if transition == "arrival":
                conn.execute(
                    """INSERT INTO port_visits
                    (mmsi,port_id,port_version,arrival_at,confirmed_at,last_evidence_at,
                     arrival_evidence) VALUES (%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT DO NOTHING""",
                    (*key, state.arrival_at, o.event_time, o.event_time, o.event_id),
                )
            if state.arrival_at:
                conn.execute(
                    """UPDATE port_visits SET last_evidence_at=%s,
                    departure_at=CASE WHEN %s THEN %s ELSE departure_at END,
                    departure_evidence=CASE WHEN %s THEN %s ELSE departure_evidence END
                    WHERE mmsi=%s AND port_id=%s AND port_version=%s AND arrival_at=%s""",
                    (
                        o.event_time,
                        transition == "departure",
                        state.since,
                        transition == "departure",
                        o.event_id,
                        *key,
                        state.arrival_at,
                    ),
                )

    @traced("postgres.latest")
    def latest(self, mmsi):
        with self.connect() as conn:
            return conn.execute(
                f"SELECT {PROJECTION} FROM latest_positions WHERE mmsi=%s", (mmsi,)
            ).fetchone()

    @traced("postgres.history")
    def history(self, mmsi, start, end, limit, cursor=None):
        after = " AND (event_time,event_id)<(%s,%s)" if cursor else ""
        args = (mmsi, start, end, *(cursor or ()), limit)
        with self.connect() as conn:
            return conn.execute(
                f"""SELECT {PROJECTION} FROM positions
                WHERE mmsi=%s AND event_time>=%s AND event_time<%s {after}
                ORDER BY event_time DESC,event_id DESC LIMIT %s""",
                args,
            ).fetchall()

    @traced("postgres.visits")
    def visits(self, port_id, limit):
        with self.connect() as conn:
            return conn.execute(
                """SELECT *,
                CASE WHEN departure_at IS NOT NULL THEN 'complete'
                     WHEN last_evidence_at<now()-(%s * INTERVAL '1 second') THEN 'uncertain'
                     ELSE 'observed' END AS quality
                FROM port_visits WHERE port_id=%s ORDER BY arrival_at DESC LIMIT %s""",
                (self.settings.visit_rules.gap_seconds, port_id, limit),
            ).fetchall()

    def quarantine(self, message, reason):
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO quarantine(topic,partition_id,offset_id,reason,payload)
                VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING""",
                (
                    message.topic(),
                    message.partition(),
                    message.offset(),
                    reason[:500],
                    message.value().decode(errors="replace")[:65536],
                ),
            )

    @traced("postgres.import_reference")
    def import_reference(self, key, body):
        payload = json.loads(body)
        calls = payload["data"]["portCalls"]
        captured_at = datetime.fromisoformat(payload["captured_at"])
        if captured_at.utcoffset() is None:
            raise ValueError("reference capture time must be timezone-aware")
        if not isinstance(calls, list) or any("portCallId" not in item for item in calls):
            raise ValueError("invalid port-call snapshot")
        with self.connect() as conn:
            if conn.execute(
                "SELECT 1 FROM reference_imports WHERE object_key=%s", (key,)
            ).fetchone():
                return False
            for call in calls:
                conn.execute(
                    """INSERT INTO reported_port_calls
                    (provider_id,payload,object_key,captured_at)
                    VALUES (%s,%s,%s,%s) ON CONFLICT(provider_id) DO UPDATE SET
                    payload=excluded.payload,object_key=excluded.object_key,
                    captured_at=excluded.captured_at,imported_at=now()
                    WHERE (excluded.captured_at,excluded.object_key) >
                          (reported_port_calls.captured_at,reported_port_calls.object_key)""",
                    (str(call["portCallId"]), Jsonb(call), key, captured_at),
                )
            conn.execute("INSERT INTO reference_imports(object_key) VALUES (%s)", (key,))
        return True

    def imported_keys(self, prefix):
        with self.connect() as conn:
            return {
                row["object_key"]
                for row in conn.execute(
                    "SELECT object_key FROM reference_imports WHERE object_key LIKE %s",
                    (prefix + "%",),
                ).fetchall()
            }

    def status(self):
        with self.connect() as conn:
            record = conn.execute("""SELECT max(received_at) AS last_received_at,
                max(event_time) AS last_event_time FROM latest_positions""").fetchone()
        return {"database": "ready", "checked_at": datetime.now(UTC), **record}
