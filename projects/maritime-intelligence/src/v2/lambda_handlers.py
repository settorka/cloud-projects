"""Thin Lambda entry point. Runtime supplies boto3; no database/network attachment."""

from v1.adapters.references import fetch_port_calls
from v1.adapters.s3 import S3ObjectStore
from v1.services import store_reference
from v1.settings import ReferenceSettings


def fetch_references(event, context):
    settings = ReferenceSettings.load()
    store = S3ObjectStore(settings)
    key = store_reference(store, fetch_port_calls(settings), settings.reference_interval_seconds)
    return {"object_key": key}
