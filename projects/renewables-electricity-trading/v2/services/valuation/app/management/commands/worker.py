import os
import signal
import threading
from concurrent.futures import ThreadPoolExecutor
from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone
from app.events import sqs, queue_url, process_message, publish_once
from app.models import JobStatus


class Command(BaseCommand):
    help = "Bounded queue consumer and outbox relay; SIGTERM stops polling and drains work"

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument(
            "--concurrency", type=int, default=int(os.environ["WORKER_CONCURRENCY"])
        )

    def handle(self, *args, **options):
        if not 1 <= options["concurrency"] <= 8:
            raise ValueError("concurrency must be 1..8")
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        client = sqs()
        name = os.getenv("CONSUMER_QUEUE", "")
        queue = queue_url(client, name) if name else None
        with ThreadPoolExecutor(max_workers=options["concurrency"]) as pool:
            while not stop.is_set():
                close_old_connections()
                try:
                    publish_once(client)
                    failed = False
                    if queue:
                        messages = client.receive_message(
                            QueueUrl=queue,
                            MaxNumberOfMessages=options["concurrency"],
                            WaitTimeSeconds=int(os.environ["SQS_WAIT_SECONDS"]),
                            MessageSystemAttributeNames=["ApproximateReceiveCount"],
                            VisibilityTimeout=int(os.environ["SQS_VISIBILITY_SECONDS"]),
                        ).get("Messages", [])
                        futures = [pool.submit(process_message, m, queue, client) for m in messages]
                        for future in futures:
                            if not future.result():
                                failed = True
                    JobStatus.objects.update_or_create(
                        name="worker",
                        defaults={
                            "last_success": timezone.now(),
                            "last_error": "message_failed" if failed else "",
                        },
                    )
                except Exception as exc:
                    JobStatus.objects.update_or_create(
                        name="worker", defaults={"last_error": type(exc).__name__}
                    )
                    self.stderr.write(f"worker retry: {type(exc).__name__}")
                    stop.wait(float(os.environ["WORKER_RETRY_SECONDS"]))
                if options["once"]:
                    break
                if not queue:
                    stop.wait(float(os.environ["OUTBOX_IDLE_SECONDS"]))
