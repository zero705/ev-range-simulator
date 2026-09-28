"""The safety rules of the tools that fetch and read source documents, tested without a network."""

from __future__ import annotations

import gzip
import hashlib
import importlib
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

TOOLS = Path(__file__).resolve().parent.parent / "tools"


@pytest.fixture
def tools(monkeypatch: pytest.MonkeyPatch) -> Any:
    """The tools/ folder on the import path, as the scripts expect when they are run."""
    monkeypatch.syspath_prepend(str(TOOLS))
    return importlib


def _downloads(tools: Any) -> ModuleType:
    module: ModuleType = tools.import_module("downloads")
    return module


class FakeResponse:
    """What urllib.request.urlopen returns, reduced to what downloads.py uses."""

    def __init__(self, body: bytes, url: str = "https://example.org/doc", gzip_body: bool = False):
        self.body = body
        self.url = url
        self.headers = {"Content-Encoding": "gzip"} if gzip_body else {}

    def read(self, size: int = -1) -> bytes:
        return self.body if size < 0 else self.body[:size]

    def geturl(self) -> str:
        return self.url

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _serve(monkeypatch: pytest.MonkeyPatch, downloads: ModuleType, response: FakeResponse) -> None:
    monkeypatch.setattr(downloads.urllib.request, "urlopen", lambda request, timeout: response)


@pytest.mark.parametrize(
    "url", ["http://www.epa.gov/", "file:///etc/passwd", "ftp://example.org/doc", "example.org"]
)
def test_only_https_is_fetched(tools: Any, url: str) -> None:
    downloads = _downloads(tools)
    with pytest.raises(downloads.DownloadError, match="not HTTPS"):
        downloads.download(url)


def test_a_redirect_away_from_https_is_refused(tools: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    downloads = _downloads(tools)
    _serve(monkeypatch, downloads, FakeResponse(b"body", url="http://example.org/doc"))
    with pytest.raises(downloads.DownloadError, match="redirected"):
        downloads.download("https://example.org/doc")


def test_the_body_is_returned_and_decompressed(tools: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    downloads = _downloads(tools)
    _serve(monkeypatch, downloads, FakeResponse(b"plain"))
    assert downloads.download("https://example.org/doc") == b"plain"
    _serve(monkeypatch, downloads, FakeResponse(gzip.compress(b"packed"), gzip_body=True))
    assert downloads.download("https://example.org/doc") == b"packed"


def test_oversized_downloads_and_decompression_bombs_are_refused(
    tools: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    downloads = _downloads(tools)
    monkeypatch.setattr(downloads, "MAX_BYTES", 100)
    _serve(monkeypatch, downloads, FakeResponse(b"x" * 101))
    with pytest.raises(downloads.DownloadError, match="larger than"):
        downloads.download("https://example.org/doc")
    bomb = gzip.compress(b"\0" * 10_000)  # a few dozen bytes that unpack to 10 kB
    assert len(bomb) <= 100
    _serve(monkeypatch, downloads, FakeResponse(bomb, gzip_body=True))
    with pytest.raises(downloads.DownloadError, match="decompresses to more than"):
        downloads.download("https://example.org/doc")


def test_a_matching_download_takes_its_place(tools: Any, tmp_path: Path) -> None:
    downloads = _downloads(tools)
    path = tmp_path / "sources" / "report.pdf"
    data = b"the document"
    assert downloads.store(path, data, hashlib.sha256(data).hexdigest())
    assert path.read_bytes() == data
    assert sorted(p.name for p in path.parent.iterdir()) == ["report.pdf"]  # no leftovers


def test_a_different_download_never_replaces_the_verified_copy(tools: Any, tmp_path: Path) -> None:
    downloads = _downloads(tools)
    path = tmp_path / "report.pdf"
    path.write_bytes(b"verified")
    assert not downloads.store(path, b"something else", hashlib.sha256(b"verified").hexdigest())
    assert path.read_bytes() == b"verified"
    assert (tmp_path / "report.pdf.rejected").read_bytes() == b"something else"


def test_road_load_files_are_read_only_when_verified(
    tools: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    openpyxl_xml = pytest.importorskip("openpyxl.xml")
    pytest.importorskip("defusedxml")
    roadload = tools.import_module("epa_roadload")
    unknown = tmp_path / "unknown.xlsx"
    unknown.write_bytes(b"PK")
    with pytest.raises(ValueError, match="no recorded fingerprint"):
        roadload.verified(unknown)
    known_name = next(iter(roadload.EPA_FILES))
    tampered = tmp_path / known_name
    tampered.write_bytes(b"PK tampered")
    with pytest.raises(ValueError, match="does not match"):
        roadload.verified(tampered)
    monkeypatch.setattr(openpyxl_xml, "DEFUSEDXML", False)
    with pytest.raises(RuntimeError, match="defusedxml"):
        roadload.verified(tampered)
