from datetime import timedelta
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from app.domain import write_value, scenario_start


class Command(BaseCommand):
    help = "Publish an explicitly synthetic four-interval portfolio scenario"

    def add_arguments(self, p):
        p.add_argument("--forecast", default="100")
        p.add_argument("--price", default="80")
        p.add_argument("--meter")
        p.add_argument("--start")
        p.add_argument("--portfolio", default="demo")

    def handle(self, *args, **o):
        start = parse_datetime(o["start"]) if o["start"] else scenario_start()
        now = timezone.now()
        for index in range(4):
            interval = start + timedelta(minutes=30 * index)
            write_value(
                "forecast", o["portfolio"], interval, o["forecast"], now, now + timedelta(hours=48)
            )
            write_value("price", "", interval, o["price"], now, now + timedelta(hours=48))
            if o["meter"] is not None:
                write_value(
                    "meter", o["portfolio"], interval, o["meter"], now, now + timedelta(hours=48)
                )
        self.stdout.write(start.isoformat())
