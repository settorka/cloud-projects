import boto3
from botocore.config import Config


class S3ObjectStore:
    def __init__(self, settings):
        self.bucket = settings.bucket
        self.max_bytes = settings.reference_max_bytes
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            region_name=settings.region,
            config=Config(
                connect_timeout=settings.http_timeout_seconds,
                read_timeout=settings.http_timeout_seconds,
                retries={"max_attempts": settings.s3_max_attempts},
                s3={"addressing_style": "path" if settings.s3_path_style else "virtual"},
            ),
        )

    def put(self, key, body):
        self.client.put_object(
            Bucket=self.bucket, Key=key, Body=body, ContentType="application/json"
        )

    def get(self, key):
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=key)
        except self.client.exceptions.NoSuchKey as exc:
            raise KeyError(key) from exc
        with response["Body"] as stream:
            body = stream.read(self.max_bytes + 1)
        if len(body) > self.max_bytes:
            raise ValueError("object exceeds configured import limit")
        return body

    def keys(self, prefix):
        pages = self.client.get_paginator("list_objects_v2")
        for page in pages.paginate(Bucket=self.bucket, Prefix=prefix):
            yield from (item["Key"] for item in page.get("Contents", []))
