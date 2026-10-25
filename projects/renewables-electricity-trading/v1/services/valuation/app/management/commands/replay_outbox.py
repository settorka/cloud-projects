from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_datetime
from app.models import Outbox


class Command(BaseCommand):
    help = "Explicit bounded replay of published outbox deliveries after local broker loss"

    def add_arguments(self, p):
        p.add_argument("--destination", required=True)
        p.add_argument("--since", required=True)
        p.add_argument("--limit", type=int, default=100)
        p.add_argument("--confirm", action="store_true")

    def handle(self, *args, **o):
        since = parse_datetime(o["since"])
        if not since or not since.tzinfo or not 1 <= o["limit"] <= 10000:
            raise CommandError("Aware --since and limit 1..10000 required")
        if not o["confirm"]:
            raise CommandError("Requires --confirm; duplicates will be redelivered")
        with transaction.atomic():
            rows = list(
                Outbox.objects.select_for_update()
                .filter(
                    destination=o["destination"], created_at__gte=since, published_at__isnull=False
                )
                .order_by("created_at")[: o["limit"]]
            )
            for row in rows:
                row.published_at = None
                row.last_error = "operator_replay"
                row.save(update_fields=["published_at", "last_error"])
        self.stdout.write(
            f"Requeued {len(rows)} outbox deliveries; inspect queue progress and reconcile"
        )
