from django.core.management.base import BaseCommand
from app.domain import calculate


class Command(BaseCommand):
    def add_arguments(self, p):
        p.add_argument("portfolio")

    def handle(self, *args, **o):
        r = calculate(o["portfolio"])
        self.stdout.write(f"{r.pk} {r.state} total={r.total}")
