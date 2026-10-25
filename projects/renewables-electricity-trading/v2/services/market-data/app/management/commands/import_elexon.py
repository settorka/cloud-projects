from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from app.elexon import import_live, ENDPOINTS


class Command(BaseCommand):
    def add_arguments(self, p):
        p.add_argument("--dataset", choices=list(ENDPOINTS), action="append")
        p.add_argument("--start")
        p.add_argument("--end")

    def handle(self, *args, **o):
        end = parse_datetime(o["end"]) if o["end"] else timezone.now()
        start = parse_datetime(o["start"]) if o["start"] else end - timedelta(hours=24)
        run = import_live(o["dataset"] or ["wind"], start, end)
        self.stdout.write(f"run={run.pk} inserted={run.records}")
