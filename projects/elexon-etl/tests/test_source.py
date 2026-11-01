from datetime import date

import httpx
import pytest

from elexon_etl.source import MAX_FILE_BYTES, Archive, SourceFile


def listing(marker="", size=2):
    return f"""<EnumerationResults><Blobs><Blob>
    <Name>data/PN/PN_202501010000_a.json</Name><Properties>
    <Content-Length>{size}</Content-Length><Etag>revision-1</Etag>
    </Properties></Blob></Blobs><NextMarker>{marker}</NextMarker></EnumerationResults>"""


def test_listing_paginates_and_deduplicates():
    markers = []

    def respond(request):
        marker = request.url.params.get("marker")
        markers.append(marker)
        return httpx.Response(200, text=listing("page2" if not marker else ""))

    archive = Archive(httpx.Client(transport=httpx.MockTransport(respond)), sleep=lambda _: None)
    files = archive.discover("PN", date(2025, 1, 1))
    assert len(files) == 1
    assert markers == [None, "page2"]


def test_throttling_retries_but_permanent_errors_do_not():
    responses = iter([429, 503, 200])
    delays = []
    archive = Archive(
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(next(responses), text=listing())
            )
        ),
        sleep=delays.append,
    )
    assert len(archive.discover("PN", date(2025, 1, 1))) == 1
    assert delays == [1, 2]
    archive.client = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(403)))
    with pytest.raises(httpx.HTTPStatusError):
        archive.discover("PN", date(2025, 1, 1))
    assert delays == [1, 2]


def test_download_checks_revision_and_size(tmp_path):
    def respond(request):
        assert request.headers["Accept-Encoding"] == "identity"
        return httpx.Response(200, content=b"[]", headers={"etag": "revision-1"})

    archive = Archive(httpx.Client(transport=httpx.MockTransport(respond)))
    with pytest.raises(ValueError, match="size changed"):
        archive.download(SourceFile("data/PN/test.json", 3, "revision-1"), tmp_path / "raw")


def test_changed_revision_never_downloads_as_the_listed_version(tmp_path):
    archive = Archive(
        httpx.Client(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, content=b"[]", headers={"etag": "revision-2"})
            )
        )
    )
    with pytest.raises(ValueError, match="revision changed"):
        archive.download(SourceFile("data/PN/test.json", 2, "revision-1"), tmp_path / "raw")


def test_empty_or_oversized_listing_fails():
    for text in ["<EnumerationResults/>", listing(size=MAX_FILE_BYTES + 1)]:
        archive = Archive(
            httpx.Client(
                transport=httpx.MockTransport(lambda _, text=text: httpx.Response(200, text=text))
            )
        )
        with pytest.raises(ValueError):
            archive.discover("PN", date(2025, 1, 1))
