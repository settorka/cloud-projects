"""Durable per-attempt state machine, separate from sampled telemetry."""

import logging
from django.db import transaction
from .models import ProcessExecution, ProcessTransition
from .telemetry import identifiers

EDGES = {
    "CREATED": {"VALIDATED", "PUBLISHING", "FETCHING", "FAILED"},
    "VALIDATED": {"APPLYING", "FAILED"},
    "APPLYING": {"APPLIED", "DUPLICATE", "FAILED"},
    "APPLIED": {"ACKNOWLEDGED", "ACK_FAILED"},
    "DUPLICATE": {"ACKNOWLEDGED", "ACK_FAILED"},
    "FETCHING": {"FETCHED", "FAILED"},
    "FETCHED": {"PERSISTING", "FAILED"},
    "PERSISTING": {"SUCCEEDED", "FAILED"},
    "SUCCEEDED": set(),
    "PUBLISHING": {"PUBLISHED", "FAILED"},
    "PUBLISHED": set(),
    "ACKNOWLEDGED": set(),
    "ACK_FAILED": set(),
    "FAILED": set(),
}


def begin(kind, identity, destination="", envelope=None):
    ids = identifiers()
    event = envelope or {}
    metadata = {
        "destination": destination[:300],
        "event_type": event.get("type", ""),
        "entity_id": event.get("entity_id", ""),
        "revision": event.get("revision"),
    }
    with transaction.atomic():
        run = ProcessExecution.objects.create(
            kind=kind, identity=str(identity)[:200], **ids, **metadata
        )
        ProcessTransition.objects.create(execution=run, sequence=0, previous="", state="CREATED")
    return run


def move(run, state, error=""):
    with transaction.atomic():
        current = ProcessExecution.objects.select_for_update().get(pk=run.pk)
        if state not in EDGES[current.state]:
            raise ValueError(f"Invalid process transition: {current.state} -> {state}")
        previous = current.state
        current.state = state
        current.sequence += 1
        current.error_code = error[:100]
        current.save(update_fields=["state", "sequence", "error_code", "updated_at"])
        ProcessTransition.objects.create(
            execution=current,
            sequence=current.sequence,
            previous=previous,
            state=state,
            error_code=error[:100],
        )
        run.state, run.sequence = current.state, current.sequence
        logging.getLogger(__name__).info(
            "process_transition",
            extra={
                "process_id": str(run.pk),
                "process_kind": run.kind,
                "process_state": state,
                "event_id": run.identity,
                "error_code": error[:100],
            },
        )
