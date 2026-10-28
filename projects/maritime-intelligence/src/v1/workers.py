import json
import logging
import signal
import threading
from datetime import UTC, datetime, timedelta

import paho.mqtt.client as mqtt
from confluent_kafka import Consumer, KafkaException
from opentelemetry import metrics, propagate, trace

from v1.adapters.digitraffic import normalize
from v1.adapters.kafka import KafkaPublisher
from v1.adapters.postgres import PostgresRepository
from v1.adapters.references import fetch_port_calls
from v1.adapters.s3 import S3ObjectStore
from v1.services import store_reference
from v1.telemetry import operation

log = logging.getLogger(__name__)


def stop_event():
    event = threading.Event()
    for name in (signal.SIGINT, signal.SIGTERM):
        signal.signal(name, lambda *_: event.set())
    return event


def inside_bbox(o, bbox):
    west, south, east, north = bbox
    return west <= o.lon <= east and south <= o.lat <= north


def ingest(settings):
    stopped = stop_event()
    publisher = KafkaPublisher(settings)
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, transport="websockets")
    client.ws_set_options(path=settings.mqtt_path)
    client.tls_set()
    client.reconnect_delay_set(
        min_delay=settings.mqtt_reconnect_min_seconds, max_delay=settings.mqtt_reconnect_max_seconds
    )

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("mqtt_connection_rejected")
            return
        log.info("mqtt_connected")
        client.subscribe(settings.mqtt_topic, qos=0)

    def on_message(client, userdata, message):
        received = datetime.now(UTC)
        try:
            o, _ = normalize(message.topic, message.payload, received)
            if not inside_bbox(o, settings.bbox):
                return
            key = o.mmsi
        except (ValueError, KeyError, TypeError, OverflowError, OSError):
            key = "invalid"
        try:
            publisher.publish(
                key,
                {
                    "topic": message.topic,
                    "payload": message.payload.decode(errors="replace"),
                    "received_at": received.isoformat(),
                },
            )
        except Exception:
            # MQTT source has no durable replay contract. Stop rather than quietly
            # continuing after Kafka publication fails; supervisor restarts ingestion.
            log.exception("kafka_delivery_failed_collection_gap")
            stopped.set()

    client.on_connect = on_connect
    client.on_message = on_message
    client.on_disconnect = lambda *args: log.warning("mqtt_disconnected_collection_gap")
    client.connect_async(
        settings.mqtt_host, settings.mqtt_port, keepalive=settings.mqtt_keepalive_seconds
    )
    client.loop_start()
    try:
        while not stopped.wait(1):
            pass
    finally:
        client.disconnect()
        client.loop_stop()


def process(settings):
    stopped = stop_event()
    repo = PostgresRepository(settings)
    consumer = Consumer(
        {
            "bootstrap.servers": settings.kafka_servers,
            "group.id": settings.kafka_group,
            "enable.auto.commit": False,
            "enable.auto.offset.store": False,
            "auto.offset.reset": "earliest",
        }
    )
    consumer.subscribe([settings.kafka_topic])
    try:
        while not stopped.is_set():
            message = consumer.poll(settings.kafka_poll_seconds)
            if message is None:
                continue
            if message.error():
                raise KafkaException(message.error())
            process_message(repo, consumer, message, settings)

    finally:
        consumer.close()


def process_message(repo, consumer, message, settings):
    meter = metrics.get_meter("maritime")
    accepted = meter.create_counter("maritime.positions.processed")
    quarantined = meter.create_counter("maritime.positions.quarantined")
    delay = meter.create_histogram("maritime.processing.delay", unit="s")
    try:
        envelope = json.loads(message.value())
        if not isinstance(envelope, dict):
            raise ValueError("Envelope must be an object")
        carrier = envelope.get("trace_context", {})
        if not isinstance(carrier, dict):
            raise ValueError("Trace context must be an object")
    except (ValueError, TypeError) as exc:
        repo.quarantine(message, type(exc).__name__)
        quarantined.add(1)
        consumer.commit(message=message, asynchronous=False)
        return
    with operation(
        "kafka.process",
        context=propagate.extract(carrier),
        kind=trace.SpanKind.CONSUMER,
        record_exception=False,
        attributes={
            "messaging.system": "kafka",
            "messaging.destination.name": settings.kafka_topic,
        },
    ):
        try:
            observation, raw = normalize(
                envelope["topic"],
                envelope["payload"].encode(),
                datetime.fromisoformat(envelope["received_at"]),
            )
        except (ValueError, KeyError, TypeError, OverflowError, OSError) as exc:
            repo.quarantine(message, type(exc).__name__ + ": " + str(exc))
            quarantined.add(1)
            log.warning("observation_quarantined offset=%s", message.offset())
        else:
            if inside_bbox(observation, settings.bbox) and observation.event_time >= datetime.now(
                UTC
            ) - timedelta(days=settings.position_retention_days):
                repo.save(observation, raw)
                accepted.add(1)
                delay.record(max(0, (datetime.now(UTC) - observation.received_at).total_seconds()))
        consumer.commit(message=message, asynchronous=False)


def object_store(settings):
    return S3ObjectStore(settings)


def fetch(settings):
    key = store_reference(
        object_store(settings), fetch_port_calls(settings), settings.reference_interval_seconds
    )
    log.info("reference_snapshot_written key=%s", key)
    return key


def reference_cycle(settings, do_fetch):
    store = object_store(settings)
    repo = PostgresRepository(settings)
    if do_fetch:
        fetch(settings)
    prefix = datetime.now(UTC).strftime("references/%Y/%m/%d/")
    imported = repo.imported_keys(prefix)
    for key in sorted(store.keys(prefix)):
        if key not in imported:
            repo.import_reference(key, store.get(key))


def reference_loop(settings, do_fetch):
    stopped = stop_event()
    while not stopped.is_set():
        try:
            reference_cycle(settings, do_fetch)
        except Exception:
            log.exception("reference_cycle_failed")
        stopped.wait(settings.reference_interval_seconds)
