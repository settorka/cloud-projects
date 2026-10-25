from django.urls import path
from .views import runs, detail

urlpatterns = [path("valuation-runs", runs), path("valuation-runs/<uuid:run_id>", detail)]
