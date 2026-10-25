from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response
from .domain import calculate, require_access
from .models import ValuationRun


class RunRequest(serializers.Serializer):
    portfolio = serializers.SlugField()


def output(run):
    return {
        "id": run.pk,
        "portfolio": run.portfolio,
        "state": run.state,
        "total": run.total,
        "results": run.results,
        "input_versions": run.input_versions,
        "calculated_at": run.created_at,
        "scope": "Applied local inputs; consult input lag before treating as current desk-wide",
    }


@api_view(["POST"])
def runs(request):
    s = RunRequest(data=request.data)
    s.is_valid(raise_exception=True)
    portfolio = s.validated_data["portfolio"]
    require_access(request.user, portfolio)
    return Response(output(calculate(portfolio)), status=201)


@api_view(["GET"])
def detail(request, run_id):
    run = get_object_or_404(ValuationRun, pk=run_id)
    require_access(request.user, run.portfolio)
    return Response(output(run))
