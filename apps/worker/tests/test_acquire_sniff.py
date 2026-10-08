"""Tests for file type sniffing and the raw object key (no database)."""

import pytest
from worker.errors import PermanentError
from worker.ingest.acquire import raw_key, sniff_mime


@pytest.mark.parametrize(
    ("data", "mime"),
    [
        (b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n", "application/pdf"),
        (b"<!DOCTYPE html><html><body>x</body></html>", "text/html"),
        (b"<!doctype HTML>\n<HTML>", "text/html"),
        (b"  <html lang='en'>", "text/html"),
    ],
)
def test_sniff_accepts_pdf_and_html(data: bytes, mime: str) -> None:
    """PDF and HTML are recognised by their first bytes, whatever the case."""
    assert sniff_mime(data) == mime


@pytest.mark.parametrize("data", [b"PK\x03\x04 zip", b"\x89PNG\r\n", b"plain text", b""])
def test_sniff_refuses_other_types(data: bytes) -> None:
    """Anything else is a permanent failure."""
    with pytest.raises(PermanentError, match="unsupported file type"):
        sniff_mime(data)


def test_raw_key_is_content_addressed() -> None:
    """The object key is raw/<first two hex chars>/<full hash>."""
    digest = "ab" + "0" * 62
    assert raw_key(digest) == f"raw/ab/{digest}"
