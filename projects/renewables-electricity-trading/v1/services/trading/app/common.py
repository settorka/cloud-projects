from django.db import OperationalError, connection
from django.http import JsonResponse, HttpResponse
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from rest_framework.decorators import api_view
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler
from .models import Outbox, JobStatus
from django.utils import timezone


class Conflict(APIException):
    status_code = 409
    default_detail = "Revision or idempotency conflict"


class Forbidden(APIException):
    status_code = 403
    default_detail = "Permission denied"


def exception_handler(exc, context):
    if isinstance(exc, OperationalError):
        response = Response(
            {"code": "retryable_database_error", "detail": "Retry with the same idempotency key"},
            status=503,
        )
        response["Retry-After"] = "2"
        return response
    return drf_exception_handler(exc, context)


def live(request):
    return JsonResponse({"status": "alive"})


def ready(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
    except OperationalError:
        return JsonResponse({"status": "unavailable"}, status=503)
    return JsonResponse({"status": "ready"})


@api_view(["GET"])
def metrics(request):
    now = timezone.now()
    first = Outbox.objects.filter(published_at__isnull=True).order_by("created_at").first()
    jobs = list(JobStatus.objects.values("name", "last_success", "last_error"))
    payload = generate_latest()
    payload += (
        f"outbox_pending {Outbox.objects.filter(published_at__isnull=True).count()}\n".encode()
    )
    payload += f"outbox_oldest_age_seconds {(now - first.created_at).total_seconds() if first else 0}\n".encode()
    for job in jobs:
        age = (now - job["last_success"]).total_seconds() if job["last_success"] else -1
        payload += f'job_success_age_seconds{{job="{job["name"]}"}} {age}\n'.encode()
    return HttpResponse(payload, content_type=CONTENT_TYPE_LATEST)


@api_view(["GET"])
def status(request):
    return Response(
        {
            "jobs": list(JobStatus.objects.values()),
            "outbox_pending": Outbox.objects.filter(published_at__isnull=True).count(),
        }
    )
