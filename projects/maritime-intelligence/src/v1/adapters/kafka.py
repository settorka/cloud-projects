import json

from confluent_kafka import KafkaException, Producer


class KafkaPublisher:
    def __init__(self, settings):
        self.topic = settings.kafka_topic
        self.flush_timeout = settings.kafka_delivery_timeout_ms / 1000 + 5
        self.producer = Producer(
            {
                "bootstrap.servers": settings.kafka_servers,
                "enable.idempotence": True,
                "acks": "all",
                "delivery.timeout.ms": settings.kafka_delivery_timeout_ms,
                "queue.buffering.max.messages": settings.kafka_queue_max_messages,
            }
        )

    def publish(self, key, event):
        errors = []
        self.producer.produce(
            self.topic,
            key=key.encode(),
            value=json.dumps(event).encode(),
            on_delivery=lambda error, message: errors.append(error) if error else None,
        )
        if self.producer.flush(self.flush_timeout) or errors:
            raise KafkaException(errors[0] if errors else "Kafka delivery timed out")
