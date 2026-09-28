"""Fetch source documents and query results safely.

Every download is made over HTTPS only (redirects included), read into memory up to a size
limit, decompressed up to the same limit, and written to disk only through store(): a document
takes its place in data/sources/ only if it has the expected SHA-256 fingerprint. A download
that does not match is kept beside it with the suffix '.rejected', for inspection, and the
verified copy is left as it was. Files are written to a temporary name first and then moved,
so an interrupted download never leaves half a document behind.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import urllib.request
from pathlib import Path

MAX_BYTES = 100 * 1024 * 1024  # the largest source document is about 35 MB
TIMEOUT_S = 300
USER_AGENT = "ev-range-simulator source verification"


class DownloadError(RuntimeError):
    """A download was refused: not HTTPS, or larger than the limit."""


def download(url: str, accept: str | None = None) -> bytes:
    """The body of an HTTPS resource, at most MAX_BYTES after decompression."""
    if not url.startswith("https://"):
        raise DownloadError(f"refusing a download that is not HTTPS: {url}")
    headers = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
    if accept is not None:
        headers["Accept"] = accept
    # The scheme is checked above, and again after any redirect below.
    request = urllib.request.Request(url, headers=headers)  # noqa: S310
    with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:  # noqa: S310
        if not response.geturl().startswith("https://"):
            raise DownloadError(f"{url} redirected to {response.geturl()}, which is not HTTPS")
        data: bytes = response.read(MAX_BYTES + 1)
        compressed = response.headers.get("Content-Encoding") == "gzip"
    if len(data) > MAX_BYTES:
        raise DownloadError(f"{url} is larger than {MAX_BYTES} bytes")
    if compressed:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise DownloadError(f"{url} decompresses to more than {MAX_BYTES} bytes")
    return data


def write_atomically(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(path.name + ".part")
    partial.write_bytes(data)
    partial.replace(path)


def store(path: Path, data: bytes, sha256: str) -> bool:
    """Put a downloaded document in place if it has the expected fingerprint.

    Otherwise the verified copy is kept, the download is saved as '<name>.rejected' and the
    result is False.
    """
    ok = hashlib.sha256(data).hexdigest() == sha256
    write_atomically(path if ok else path.with_name(path.name + ".rejected"), data)
    return ok
