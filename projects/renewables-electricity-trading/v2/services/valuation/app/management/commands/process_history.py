import json
from datetime import timedelta
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone
from app.models import ProcessExecution


class Command(BaseCommand):
    help = "Inspect bounded process lineage, or prune terminal telemetry history explicitly"

    def add_arguments(self, p):
        p.add_argument("--identity")
        p.add_argument("--limit", type=int, default=20)
        p.add_argument("--prune-days", type=int)
        p.add_argument("--confirm", action="store_true")

    def handle(self, *args, **o):
        if not 1 <= o["limit"] <= 1000:
            raise CommandError("limit must be 1..1000")
        rows = ProcessExecution.objects.order_by("created_at")
        if o["prune_days"] is not None:
            if o["prune_days"] < 7 or not o["confirm"]:
                raise CommandError("Pruning requires >=7 days and --confirm")
            with transaction.atomic():
                ids = list(
                    rows.filter(
                        state__in=[
                            "ACKNOWLEDGED",
                            "PUBLISHED",
                            "FAILED",
                            "ACK_FAILED",
                            "SUCCEEDED",
                        ],
                        updated_at__lt=timezone.now() - timedelta(days=o["prune_days"]),
                    ).values_list("pk", flat=True)[: o["limit"]]
                )
                count, _ = ProcessExecution.objects.filter(pk__in=ids).delete()
            self.stdout.write(f"Deleted {count} process/transition rows; business audit untouched")
            return
        if o["identity"]:
            rows = rows.filter(identity=o["identity"])
        for run in rows[: o["limit"]]:
            self.stdout.write(
                json.dumps(
                    {
                        "process_id": str(run.pk),
                        "identity": run.identity,
                        "destination": run.destination,
                        "event_type": run.event_type,
                        "entity_id": run.entity_id,
                        "revision": run.revision,
                        "state": run.state,
                        "trace_id": run.trace_id,
                        "error_code": run.error_code,
                        "steps": list(
                            run.transitions.order_by("sequence").values(
                                "sequence", "previous", "state", "error_code"
                            )
                        ),
                    }
                )
            )
