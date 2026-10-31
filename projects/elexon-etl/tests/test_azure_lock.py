"""SDK-boundary regression for a conflict observed against real Azure Blob Storage."""

from unittest.mock import Mock

import pytest
from azure.core.exceptions import HttpResponseError

from elexon_etl.storage import AzureStore


def test_create_only_pointer_on_a_leased_blob_is_a_writer_conflict():
    error = HttpResponseError("Lease ID missing")
    error.status_code = 412
    error.error_code = "LeaseIdMissing"
    blob = Mock()
    blob.upload_blob.side_effect = error
    store = AzureStore.__new__(AzureStore)
    store._blob = Mock(return_value=blob)
    with pytest.raises(BlockingIOError, match="already has a writer"):
        with store.lock("dataset=PN/date=2025-01-01"):
            pytest.fail("Must never acquire a competing writer lock")
    blob.acquire_lease.assert_not_called()
