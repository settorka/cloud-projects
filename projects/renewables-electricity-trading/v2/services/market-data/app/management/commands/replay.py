import json
from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_datetime
from app.domain import write_value


class Command(BaseCommand):
    help = "Replay explicit synthetic portfolio records; same timestamps deduplicate"

    def add_arguments(self, p):
        p.add_argument("path")

    def handle(self, *args, **o):
        with open(o["path"]) as f:
            rows = json.load(f)
        if len(rows) > 10000:
            raise ValueError("Maximum replay batch: 10000")
        for row in rows:
            write_value(
                row["kind"],
                row.get("portfolio", ""),
                parse_datetime(row["start"]),
                row["quantity"],
                parse_datetime(row["published_at"]),
                parse_datetime(row["valid_until"]),
            )
        self.stdout.write(f"Replayed {len(rows)} records")
