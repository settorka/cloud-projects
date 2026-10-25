import json
from django.core.management.base import BaseCommand, CommandError
from app.events import sqs, queue_url, validate


class Command(BaseCommand):
    help = "Inspect queues or explicitly redrive valid envelopes in bounded batches"

    def add_arguments(self, p):
        commands = p.add_subparsers(dest="operation", required=True)
        inspect = commands.add_parser("inspect")
        inspect.add_argument("queue")
        inspect.add_argument("--sample", action="store_true")
        redrive = commands.add_parser("redrive")
        redrive.add_argument("source")
        redrive.add_argument("destination")
        redrive.add_argument("--max-messages", type=int, default=10)

    def handle(self, *args, **o):
        client = sqs()
        if o["operation"] == "inspect":
            url = queue_url(client, o["queue"])
            self.stdout.write(
                json.dumps(
                    client.get_queue_attributes(QueueUrl=url, AttributeNames=["All"])["Attributes"],
                    indent=2,
                )
            )
            if o["sample"]:
                messages = client.receive_message(
                    QueueUrl=url, MaxNumberOfMessages=1, VisibilityTimeout=5, WaitTimeSeconds=0
                ).get("Messages", [])
                for message in messages:
                    self.stdout.write(message["Body"])
            return
        if o["source"] == o["destination"] or not 1 <= o["max_messages"] <= 100:
            raise CommandError("Distinct queues and max 1..100 required")
        source = queue_url(client, o["source"])
        target = queue_url(client, o["destination"])
        count = 0
        while count < o["max_messages"]:
            messages = client.receive_message(
                QueueUrl=source, MaxNumberOfMessages=1, VisibilityTimeout=30, WaitTimeSeconds=0
            ).get("Messages", [])
            if not messages:
                break
            message = messages[0]
            try:
                validate(json.loads(message["Body"]))
            except Exception as exc:
                raise CommandError(
                    "Invalid envelope retained; correct producer before replay"
                ) from exc
            client.send_message(QueueUrl=target, MessageBody=message["Body"])
            client.delete_message(QueueUrl=source, ReceiptHandle=message["ReceiptHandle"])
            count += 1
        self.stdout.write(f"Redriven {count} messages")
