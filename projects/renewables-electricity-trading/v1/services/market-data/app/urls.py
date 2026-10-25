from django.urls import path
from .views import sources, source_records

urlpatterns = [path("sources", sources), path("source-records", source_records)]
