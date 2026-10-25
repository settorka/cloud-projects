import json
import os
import time
import uuid
from django.core.management.base import BaseCommand, CommandError
from app.events import sqs


class Command(BaseCommand):
    help = "Local-only broker visibility/redrive check using disposable isolated queues"

    def handle(self, *args, **o):
        if "elasticmq" not in os.getenv("SQS_ENDPOINT_URL", ""):
            raise CommandError("This probe is local-emulator-only")
        client = sqs()
        suffix = uuid.uuid4().hex[:10]
        source = None
        dlq = None
        try:
            dlq = client.create_queue(QueueName=f"probe-dlq-{suffix}")["QueueUrl"]
            arn = client.get_queue_attributes(QueueUrl=dlq, AttributeNames=["QueueArn"])[
                "Attributes"
            ]["QueueArn"]
            source = client.create_queue(
                QueueName=f"probe-source-{suffix}",
                Attributes={
                    "VisibilityTimeout": "2",
                    "RedrivePolicy": json.dumps(
                        {"deadLetterTargetArn": arn, "maxReceiveCount": "3"}
                    ),
                },
            )["QueueUrl"]
            client.send_message(QueueUrl=source, MessageBody="poison-probe")
            first = client.receive_message(QueueUrl=source, WaitTimeSeconds=0)["Messages"][0]
            assert not client.receive_message(QueueUrl=source, WaitTimeSeconds=0).get("Messages"), (
                "Message was visible before lease expiry"
            )
            client.change_message_visibility(
                QueueUrl=source, ReceiptHandle=first["ReceiptHandle"], VisibilityTimeout=0
            )
            deadline = time.monotonic() + 10
            found = False
            while time.monotonic() < deadline:
                messages = client.receive_message(QueueUrl=source, WaitTimeSeconds=0).get(
                    "Messages", []
                )
                for message in messages:
                    client.change_message_visibility(
                        QueueUrl=source, ReceiptHandle=message["ReceiptHandle"], VisibilityTimeout=0
                    )
                if client.receive_message(QueueUrl=dlq, WaitTimeSeconds=0).get("Messages"):
                    found = True
                    break
                time.sleep(0.1)
            assert found, "Poison probe did not reach DLQ"
            self.stdout.write("Broker visibility, redelivery and DLQ check passed")
        finally:
            if source:
                client.delete_queue(QueueUrl=source)
            if dlq:
                client.delete_queue(QueueUrl=dlq)
