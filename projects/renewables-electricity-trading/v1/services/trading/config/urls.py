from django.urls import path, include
from app.common import live, ready, metrics, status

urlpatterns = [
    path("health/live", live),
    path("health/ready", ready),
    path("metrics", metrics),
    path("v1/status", status),
    path("v1/", include("app.urls")),
]
