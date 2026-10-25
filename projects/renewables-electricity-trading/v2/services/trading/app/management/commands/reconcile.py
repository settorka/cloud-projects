from django.core.management.base import BaseCommand, CommandError
from app.domain import reconcile


class Command(BaseCommand):
    help = "Independently recompute contracted positions; mismatches block portfolio writes"

    def add_arguments(self, p):
        p.add_argument("portfolio")
        p.add_argument("--repair", action="store_true")

    def handle(self, *args, **o):
        result = reconcile(o["portfolio"], o["repair"])
        self.stdout.write(
            f"Checked {result.checked} positions; mismatches={len(result.mismatches)}"
        )
        if result.mismatches and not o["repair"]:
            raise CommandError("Mismatch: portfolio writes blocked")
