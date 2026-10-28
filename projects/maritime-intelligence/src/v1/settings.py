"""Validated environment configuration. Deployment values have no hidden fallbacks."""

import math
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from v1.visits import VisitRules


def required(name, *, allow_empty=False):
    value = os.environ.get(name)
    if value is None or (not allow_empty and not value.strip()):
        raise ValueError(f"Missing required environment variable: {name}")
    return value


def positive(name):
    try:
        value = int(required(name))
    except ValueError as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def boolean(name):
    value = required(name).lower()
    if value not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false")
    return value == "true"


def read_env():
    # Explicit environment wins, including Compose and AWS-injected configuration.
    path = Path(os.environ.get("ENV_FILE", ".env"))
    if path.is_file():
        from dotenv import load_dotenv

        load_dotenv(path, override=False)


@dataclass(frozen=True)
class ReferenceSettings:
    bucket: str
    region: str
    s3_endpoint: str | None
    s3_path_style: bool
    s3_max_attempts: int
    reference_url: str
    reference_interval_seconds: int
    reference_max_bytes: int
    http_timeout_seconds: int
    source_user_agent: str

    @classmethod
    def load(cls):
        read_env()
        url = required("REFERENCE_API_URL")
        if urlparse(url).scheme != "https":
            raise ValueError("REFERENCE_API_URL must use HTTPS")
        endpoint = required("S3_ENDPOINT_URL", allow_empty=True)
        if endpoint and urlparse(endpoint).scheme not in {"http", "https"}:
            raise ValueError("S3_ENDPOINT_URL must be HTTP(S) or empty for AWS")
        return cls(
            bucket=required("S3_BUCKET"),
            region=required("AWS_DEFAULT_REGION"),
            s3_endpoint=endpoint or None,
            s3_path_style=boolean("S3_PATH_STYLE"),
            s3_max_attempts=positive("S3_MAX_ATTEMPTS"),
            reference_url=url,
            reference_interval_seconds=positive("REFERENCE_INTERVAL_SECONDS"),
            reference_max_bytes=positive("REFERENCE_MAX_BYTES"),
            http_timeout_seconds=positive("HTTP_TIMEOUT_SECONDS"),
            source_user_agent=required("DIGITRAFFIC_USER"),
        )


@dataclass(frozen=True)
class Settings(ReferenceSettings):
    database_url: str = field(repr=False)
    api_token: str = field(repr=False)
    api_host: str
    api_port: int
    api_page_size: int
    api_max_page_size: int
    api_history_hours: int
    fresh_seconds: int
    expired_seconds: int
    log_level: str
    migrations_dir: str
    db_connect_timeout_seconds: int
    db_statement_timeout_ms: int
    position_retention_days: int
    kafka_servers: str
    kafka_topic: str
    kafka_group: str
    kafka_delivery_timeout_ms: int
    kafka_queue_max_messages: int
    kafka_poll_seconds: int
    mqtt_host: str
    mqtt_port: int
    mqtt_path: str
    mqtt_topic: str
    mqtt_keepalive_seconds: int
    mqtt_reconnect_min_seconds: int
    mqtt_reconnect_max_seconds: int
    bbox: tuple[float, float, float, float]
    exit_buffer_metres: int
    visit_rules: VisitRules

    @classmethod
    def load(cls):
        ref = ReferenceSettings.load()
        token = required("API_TOKEN")
        if len(token) < 24:
            raise ValueError("API_TOKEN must contain at least 24 characters")
        try:
            bbox = tuple(float(x) for x in required("AIS_BBOX").split(","))
        except ValueError as exc:
            raise ValueError("AIS_BBOX must be west,south,east,north") from exc
        if (
            len(bbox) != 4
            or not all(math.isfinite(x) for x in bbox)
            or not (-180 <= bbox[0] < bbox[2] <= 180 and -90 <= bbox[1] < bbox[3] <= 90)
        ):
            raise ValueError("AIS_BBOX must be west,south,east,north")
        mapping = {
            "api_port": "API_PORT",
            "api_page_size": "API_PAGE_SIZE",
            "api_max_page_size": "API_MAX_PAGE_SIZE",
            "api_history_hours": "API_HISTORY_HOURS",
            "fresh_seconds": "FRESH_SECONDS",
            "expired_seconds": "EXPIRED_SECONDS",
            "db_connect_timeout_seconds": "DB_CONNECT_TIMEOUT_SECONDS",
            "db_statement_timeout_ms": "DB_STATEMENT_TIMEOUT_MS",
            "position_retention_days": "POSITION_RETENTION_DAYS",
            "kafka_delivery_timeout_ms": "KAFKA_DELIVERY_TIMEOUT_MS",
            "kafka_queue_max_messages": "KAFKA_QUEUE_MAX_MESSAGES",
            "kafka_poll_seconds": "KAFKA_POLL_SECONDS",
            "mqtt_port": "AIS_MQTT_PORT",
            "mqtt_keepalive_seconds": "AIS_MQTT_KEEPALIVE_SECONDS",
            "mqtt_reconnect_min_seconds": "AIS_MQTT_RECONNECT_MIN_SECONDS",
            "mqtt_reconnect_max_seconds": "AIS_MQTT_RECONNECT_MAX_SECONDS",
            "exit_buffer_metres": "VISIT_EXIT_BUFFER_METRES",
        }
        numbers = {field: positive(env) for field, env in mapping.items()}
        for smaller, larger in [
            ("api_page_size", "api_max_page_size"),
            ("fresh_seconds", "expired_seconds"),
            ("mqtt_reconnect_min_seconds", "mqtt_reconnect_max_seconds"),
        ]:
            if numbers[smaller] > numbers[larger]:
                raise ValueError(f"{mapping[smaller]} must not exceed {mapping[larger]}")
        if numbers["api_port"] > 65535 or numbers["mqtt_port"] > 65535:
            raise ValueError("Ports must be within 1–65535")
        if numbers["api_history_hours"] > numbers["position_retention_days"] * 24:
            raise ValueError("API_HISTORY_HOURS must not exceed position retention")
        rules = VisitRules(
            arrival_observations=positive("VISIT_ARRIVAL_OBSERVATIONS"),
            arrival_seconds=positive("VISIT_ARRIVAL_SECONDS"),
            departure_observations=positive("VISIT_DEPARTURE_OBSERVATIONS"),
            departure_seconds=positive("VISIT_DEPARTURE_SECONDS"),
            gap_seconds=positive("VISIT_GAP_SECONDS"),
        )
        return cls(
            **asdict(ref),
            **numbers,
            database_url=required("DATABASE_URL"),
            api_token=token,
            api_host=required("API_HOST"),
            log_level=required("LOG_LEVEL"),
            migrations_dir=required("MIGRATIONS_DIR"),
            kafka_servers=required("KAFKA_SERVERS"),
            kafka_topic=required("KAFKA_TOPIC"),
            kafka_group=required("KAFKA_CONSUMER_GROUP"),
            mqtt_host=required("AIS_MQTT_HOST"),
            mqtt_path=required("AIS_MQTT_PATH"),
            mqtt_topic=required("AIS_MQTT_TOPIC"),
            bbox=bbox,
            visit_rules=rules,
        )
