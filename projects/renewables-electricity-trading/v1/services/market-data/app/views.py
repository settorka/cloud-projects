from rest_framework.decorators import api_view
from rest_framework.response import Response
from .models import SourceRecord, ImportRun, MarketValue


@api_view(["GET"])
def sources(request):
    return Response(
        {
            "recent_imports": list(ImportRun.objects.order_by("-pk").values()[:20]),
            "source_records": SourceRecord.objects.count(),
            "synthetic_values": MarketValue.objects.count(),
            "attribution": "Contains BMRS data © Elexon Limited copyright and database right 2026.",
            "licence": "https://www.elexon.co.uk/bsc/data/balancing-mechanism-reporting-agent/copyright-licence-bmrs-data/",
        }
    )


@api_view(["GET"])
def source_records(request):
    from .elexon import ENDPOINTS

    dataset = request.query_params.get("dataset", "wind")
    if dataset not in ENDPOINTS:
        return Response({"detail": "Unknown dataset"}, status=400)
    try:
        limit = min(100, max(1, int(request.query_params.get("limit", 100))))
        offset = max(0, int(request.query_params.get("offset", 0)))
    except ValueError:
        return Response({"detail": "Invalid pagination"}, status=400)
    rows = SourceRecord.objects.filter(dataset=dataset).order_by("-start", "-ingested_at")
    return Response(
        {
            "dataset": dataset,
            "count": rows.count(),
            "offset": offset,
            "scope": "Published aggregate source records, not private asset forecasts",
            "results": list(
                rows.values("identity", "start", "published_at", "ingested_at", "payload")[
                    offset : offset + limit
                ]
            ),
        }
    )
