import io
import zipfile

import pytest

from scripts.run_windows import bundle


def test_bundle_is_stable_and_contains_only_explicit_assets(tmp_path):
    first, second = tmp_path / "a.py", tmp_path / "b.py"
    first.write_text("print('a')\n")
    second.write_text("print('b')\n")
    expected = bundle([("pipeline/a.py", first), ("b.py", second)])
    assert bundle([("b.py", second), ("pipeline/a.py", first)]) == expected
    with zipfile.ZipFile(io.BytesIO(expected)) as archive:
        assert archive.namelist() == ["b.py", "pipeline/a.py"]
        assert archive.read("pipeline/a.py") == first.read_bytes()


@pytest.mark.parametrize(
    "destination", ["../outside", "/absolute", "C:/outside", "a\\outside", "a'quote"]
)
def test_bundle_rejects_unsafe_destinations(tmp_path, destination):
    path = tmp_path / "file"
    path.write_text("source")
    with pytest.raises(ValueError, match="safe relative"):
        bundle([(destination, path)])


def test_bundle_rejects_duplicate_destinations(tmp_path):
    path = tmp_path / "file"
    path.write_text("source")
    with pytest.raises(ValueError, match="Duplicate"):
        bundle([("same", path), ("same", path)])
