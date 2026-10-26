import json
import os
import boto3
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from app.models import JobStatus, Outbox


class Command(BaseCommand):
    help = "Bounded worker/outbox operational metrics; no financial payloads"

    def add_arguments(self, p):
        p.add_argument("--cloudwatch", action="store_true")

    def handle(self, *args, **options):
        now = timezone.now()
        job = JobStatus.objects.filter(name="worker").first()
        healthy = int(
            bool(
                job
                and job.last_success
                and not job.last_error
                and (now - job.last_success).total_seconds() < 120
            )
        )
        oldest = Outbox.objects.filter(published_at__isnull=True).order_by("created_at").first()
        age = (now - oldest.created_at).total_seconds() if oldest else 0
        result = {"service": settings.SERVICE, "worker_healthy": healthy, "outbox_age_seconds": age}
        if options["cloudwatch"]:
            boto3.client(
                "cloudwatch", region_name=os.environ["AWS_DEFAULT_REGION"]
            ).put_metric_data(
                Namespace="Renewables/V2",
                MetricData=[
                    {
                        "MetricName": name,
                        "Value": value,
                        "Dimensions": [{"Name": "Service", "Value": settings.SERVICE}],
                    }
                    for name, value in [("WorkerHealthy", healthy), ("OutboxAgeSeconds", age)]
                ],
            )
        self.stdout.write(json.dumps(result))
