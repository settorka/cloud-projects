"""Real dependency contracts. Enabled explicitly, never silently replaced by mocks."""

import json
import os
import time
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from v1.settings import Settings

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("INTEGRATION") != "1", reason="Run the Compose test profile for real dependencies"
    ),
]


def test_postgres_deduplication_latest_and_geofencing():
    from v1.adapters.postgres import PostgresRepository
    from v1.models import Observation

    repo = PostgresRepository(Settings.load())
    at = datetime.now(UTC) - timedelta(minutes=9)
    mmsi = "999" + str(uuid.uuid4().int % 1000000).zfill(6)
    port = "test-" + uuid.uuid4().hex
    with repo.connect() as conn:
        conn.execute(
            "INSERT INTO port_areas(id,version,name,provenance,boundary)\n            VALUES (%s,1,'Synthetic test area','integration-test',\n            ST_Multi(ST_GeomFromText('POLYGON((24 60,25 60,25 61,24 61,24 60))',4326)))",
            (port,),
        )
    try:
        for minute in [0, 2, 5]:
            o = Observation(
                "test", mmsi, at + timedelta(minutes=minute), datetime.now(UTC), 24.5, 60.5
            )
            assert repo.save(o, {})
            assert not repo.save(o, {})
        delayed = Observation(
            "test", mmsi, at - timedelta(minutes=1), datetime.now(UTC), 24.4, 60.4
        )
        repo.save(delayed, {})
        assert repo.latest(mmsi)["event_time"] == at + timedelta(minutes=5)
        assert len(repo.visits(port, 10)) == 1
        for minute in [6, 8]:
            repo.save(
                Observation(
                    "test", mmsi, at + timedelta(minutes=minute), datetime.now(UTC), 26, 62
                ),
                {},
            )
        visit = repo.visits(port, 10)[0]
        assert visit["quality"] == "complete"
        assert visit["departure_at"] == at + timedelta(minutes=6)
        rows = repo.history(mmsi, at - timedelta(minutes=2), datetime.now(UTC), 100)
        assert len(rows) == 6
        assert (
            repo.history(
                mmsi,
                at - timedelta(minutes=2),
                datetime.now(UTC),
                100,
                (rows[0]["event_time"], rows[0]["event_id"]),
            )
            == rows[1:]
        )
    finally:
        with repo.connect() as conn:
            for table in ("positions", "latest_positions", "visit_states", "port_visits"):
                conn.execute(f"DELETE FROM {table} WHERE mmsi=%s", (mmsi,))
            conn.execute("DELETE FROM port_areas WHERE id=%s", (port,))


def test_s3_same_adapter_roundtrip_listing_and_missing_key():
    from v1.adapters.s3 import S3ObjectStore

    store = S3ObjectStore(Settings.load())
    key = "contracts/" + uuid.uuid4().hex + ".json"
    try:
        store.put(key, b'{"real_storage":true}')
        assert store.get(key) == b'{"real_storage":true}'
        assert key in list(store.keys("contracts/"))
        with pytest.raises(KeyError):
            store.get(key + ".missing")
    finally:
        store.client.delete_object(Bucket=store.bucket, Key=key)


def test_kafka_key_and_manual_offset_redelivery():
    from confluent_kafka import Consumer

    from v1.adapters.kafka import KafkaPublisher

    settings = Settings.load()
    servers = settings.kafka_servers
    topic = settings.kafka_topic
    group = "contract-" + uuid.uuid4().hex
    consumer = Consumer(
        {
            "bootstrap.servers": servers,
            "group.id": group,
            "enable.auto.commit": False,
            "auto.offset.reset": "latest",
        }
    )
    consumer.subscribe([topic])
    deadline = time.monotonic() + 30
    try:
        while not consumer.assignment() and time.monotonic() < deadline:
            consumer.poll(0.2)
        assert consumer.assignment(), "Kafka consumer assignment timed out"
        key = "contract-" + uuid.uuid4().hex
        KafkaPublisher(settings).publish(key, {"contract": key})
        message = None
        while time.monotonic() < deadline:
            candidate = consumer.poll(1)
            if candidate and (not candidate.error()) and (candidate.key() == key.encode()):
                message = candidate
                break
        assert message is not None
        assert json.loads(message.value())["contract"] == key
        from confluent_kafka import TopicPartition

        consumer.seek(TopicPartition(topic, message.partition(), message.offset()))
        repeated = None
        replay_deadline = time.monotonic() + 15
        while time.monotonic() < replay_deadline:
            candidate = consumer.poll(1)
            if (
                candidate
                and (not candidate.error())
                and (candidate.key() == key.encode())
                and (candidate.partition() == message.partition())
                and (candidate.offset() == message.offset())
            ):
                repeated = candidate
                break
        assert repeated is not None and repeated.value() == message.value()
        consumer.commit(message=repeated, asynchronous=False)
    finally:
        consumer.close()


def test_reference_import_is_idempotent_and_cannot_regress():
    from v1.adapters.postgres import PostgresRepository
    from v1.services import store_reference

    class Store:
        def put(self, key, body):
            self.body = body

    store = Store()
    repo = PostgresRepository(Settings.load())
    identity = str(uuid.uuid4())
    now = datetime.now(UTC)
    key = store_reference(store, {"portCalls": [{"portCallId": identity, "name": "new"}]}, 900, now)
    try:
        assert repo.import_reference(key, store.body)
        assert not repo.import_reference(key, store.body)
        old = store_reference(
            store,
            {"portCalls": [{"portCallId": identity, "name": "old"}]},
            900,
            now - timedelta(hours=1),
        )
        assert repo.import_reference(old, store.body)
        with repo.connect() as conn:
            assert (
                conn.execute(
                    "SELECT payload FROM reported_port_calls WHERE provider_id=%s", (identity,)
                ).fetchone()["payload"]["name"]
                == "new"
            )
    finally:
        with repo.connect() as conn:
            conn.execute("DELETE FROM reported_port_calls WHERE provider_id=%s", (identity,))
            conn.execute("DELETE FROM reference_imports WHERE object_key IN (%s,%s)", (key, old))
