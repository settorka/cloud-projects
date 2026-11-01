from datetime import date

import pytest

import dashboard_data as data


@pytest.mark.parametrize(
    "field,value",
    [
        ("batch", "x' OR 1=1--"),
        ("currency", "GBP\"},ALL('Batch'))"),
        ("pair", "USD/GBP"),
        ("counterparty", "CP21"),
        ("direction", "receive';DROP TABLE x"),
    ],
)
def test_untrusted_filter_values_are_rejected_before_query(field, value):
    selected = {"batch": "a" * 64, "currency": "GBP"}
    selected[field] = value
    with pytest.raises(ValueError):
        data.filters(**selected)


def test_public_metrics_boundary_revalidates_scope_before_loading_windows_clients():
    with pytest.raises(ValueError):
        data.metrics({"batch": "a" * 64, "currency": 'GBP"; invalid'})


def test_reversed_due_dates_are_rejected():
    with pytest.raises(ValueError, match="due-date"):
        data.filters("a" * 64, "GBP", dates=(date(2025, 2, 1), date(2025, 1, 1)))
