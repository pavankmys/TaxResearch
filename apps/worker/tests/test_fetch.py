"""Tests for the safe URL fetch: every refusal path, with a mocked transport (no network)."""

import httpx
import pytest
from worker.config import FetchConfig, SourceConfig
from worker.errors import PermanentError
from worker.ingest.fetch import FetchError, FetchRefused, check_url, fetch_url

PUBLIC_IP = "93.184.216.34"
PDF_BODY = b"%PDF-1.4\n" + b"x" * 100


def _source(hosts: set[str] | None = None) -> SourceConfig:
    return SourceConfig(
        code="cbic_gst_portal",
        kind="manual",
        enabled=True,
        allowed_hosts=frozenset(hosts or {"cbic-gst.gov.in", "www.cbic-gst.gov.in"}),
        user_agent="TaxResearch-Test/1.0",
    )


def _cfg(max_bytes: int = 1000) -> FetchConfig:
    return FetchConfig(
        max_bytes=max_bytes,
        timeout_seconds=5,
        allowed_content_types=frozenset({"application/pdf", "text/html"}),
    )


def _public(host: str) -> list[str]:
    return [PUBLIC_IP]


def _transport(handler: httpx.MockTransport | object) -> httpx.BaseTransport:
    return httpx.MockTransport(handler)  # type: ignore[arg-type]


def test_allowed_url_is_fetched() -> None:
    """An allowed host with an allowed type returns the bytes and the user agent is sent."""
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["user_agent"] = request.headers["user-agent"]
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf; charset=binary", "etag": '"abc"'},
            content=PDF_BODY,
        )

    result = fetch_url(
        "https://cbic-gst.gov.in/notes/ct11.pdf",
        _source(),
        _cfg(),
        transport=_transport(handler),
        resolver=_public,
    )

    assert result.data == PDF_BODY
    assert result.content_type == "application/pdf"
    assert result.final_url == "https://cbic-gst.gov.in/notes/ct11.pdf"
    assert result.etag == '"abc"'
    assert seen["user_agent"] == "TaxResearch-Test/1.0"


def test_host_not_on_allow_list_is_refused() -> None:
    """A host outside allowed_hosts is refused before any request is sent."""
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(200, content=PDF_BODY)

    with pytest.raises(FetchRefused, match="host not allowed"):
        fetch_url(
            "https://evil.example/file.pdf",
            _source(),
            _cfg(),
            transport=_transport(handler),
            resolver=_public,
        )
    assert calls == []


def test_refusal_is_permanent() -> None:
    """FetchRefused is a PermanentError, so the runner does not retry it."""
    assert issubclass(FetchRefused, PermanentError)
    assert not issubclass(FetchError, PermanentError)


@pytest.mark.parametrize(
    "url",
    ["ftp://cbic-gst.gov.in/a.pdf", "file:///etc/passwd", "javascript:alert(1)"],
)
def test_non_http_scheme_is_refused(url: str) -> None:
    """Only http and https are accepted."""
    with pytest.raises(FetchRefused, match="scheme not allowed"):
        check_url(url, _source(), _public)


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.5",
        "127.0.0.1",
        "169.254.169.254",
        "192.168.1.10",
        "0.0.0.0",
        "224.0.0.1",
        "::1",
        "fe80::1",
        "::ffff:10.0.0.1",
        "fd00::1",
    ],
)
def test_private_or_special_address_is_refused(address: str) -> None:
    """A host that resolves to a private, loopback, link-local or reserved address is refused."""
    with pytest.raises(FetchRefused, match="non-public address"):
        check_url("https://cbic-gst.gov.in/a.pdf", _source(), lambda host: [address])


def test_any_private_address_refuses_the_host() -> None:
    """If one of several resolved addresses is private, the host is refused."""

    def resolver(host: str) -> list[str]:
        return [PUBLIC_IP, "10.1.2.3"]

    with pytest.raises(FetchRefused, match="non-public address"):
        check_url("https://cbic-gst.gov.in/a.pdf", _source(), resolver)


def test_host_that_does_not_resolve_is_refused() -> None:
    """No addresses at all is a refusal."""
    with pytest.raises(FetchRefused, match="does not resolve"):
        check_url("https://cbic-gst.gov.in/a.pdf", _source(), lambda host: [])


def test_resolver_failure_is_retryable() -> None:
    """A DNS error is transient, so it is a FetchError."""

    def resolver(host: str) -> list[str]:
        raise OSError("temporary failure in name resolution")

    with pytest.raises(FetchError):
        check_url("https://cbic-gst.gov.in/a.pdf", _source(), resolver)


def test_redirect_to_disallowed_host_is_refused() -> None:
    """A redirect off the allow-list stops the fetch."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://evil.example/x.pdf"})

    with pytest.raises(FetchRefused, match="host not allowed"):
        fetch_url(
            "https://cbic-gst.gov.in/a.pdf",
            _source(),
            _cfg(),
            transport=_transport(handler),
            resolver=_public,
        )


def test_redirect_to_allowed_host_is_followed() -> None:
    """A redirect to another allowed host is followed and the final URL is reported."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "cbic-gst.gov.in":
            return httpx.Response(301, headers={"location": "https://www.cbic-gst.gov.in/a.pdf"})
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=PDF_BODY)

    result = fetch_url(
        "https://cbic-gst.gov.in/a.pdf",
        _source(),
        _cfg(),
        transport=_transport(handler),
        resolver=_public,
    )
    assert result.final_url == "https://www.cbic-gst.gov.in/a.pdf"
    assert result.data == PDF_BODY


def test_redirect_loop_is_refused() -> None:
    """More than five redirects is refused."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(302, headers={"location": "https://cbic-gst.gov.in/again.pdf"})

    with pytest.raises(FetchRefused, match="too many redirects"):
        fetch_url(
            "https://cbic-gst.gov.in/a.pdf",
            _source(),
            _cfg(),
            transport=_transport(handler),
            resolver=_public,
        )


def test_declared_size_over_cap_is_refused_early() -> None:
    """A Content-Length above the cap is refused before the body is read."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            headers={"content-type": "application/pdf", "content-length": "5000"},
            content=b"x" * 10,
        )

    with pytest.raises(FetchRefused, match="too large"):
        fetch_url(
            "https://cbic-gst.gov.in/a.pdf",
            _source(),
            _cfg(max_bytes=1000),
            transport=_transport(handler),
            resolver=_public,
        )


def test_body_over_cap_is_refused() -> None:
    """A body larger than the cap is refused even without a Content-Length."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "application/pdf"}, content=b"x" * 2000)

    with pytest.raises(FetchRefused, match="too large"):
        fetch_url(
            "https://cbic-gst.gov.in/a.pdf",
            _source(),
            _cfg(max_bytes=1000),
            transport=_transport(handler),
            resolver=_public,
        )


@pytest.mark.parametrize("content_type", ["text/plain", "application/zip", None])
def test_disallowed_content_type_is_refused(content_type: str | None) -> None:
    """Only the configured media types are accepted."""
    headers = {"content-type": content_type} if content_type else {}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers=headers, content=PDF_BODY)

    with pytest.raises(FetchRefused, match="content type not allowed"):
        fetch_url(
            "https://cbic-gst.gov.in/a.pdf",
            _source(),
            _cfg(),
            transport=_transport(handler),
            resolver=_public,
        )


def test_server_error_is_retryable() -> None:
    """A 500 is a FetchError, not a refusal, so the job is retried."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, content=b"oops")

    with pytest.raises(FetchError, match="HTTP 500"):
        fetch_url(
            "https://cbic-gst.gov.in/a.pdf",
            _source(),
            _cfg(),
            transport=_transport(handler),
            resolver=_public,
        )


def test_network_error_is_retryable() -> None:
    """A connection failure is a FetchError."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(FetchError, match="network error"):
        fetch_url(
            "https://cbic-gst.gov.in/a.pdf",
            _source(),
            _cfg(),
            transport=_transport(handler),
            resolver=_public,
        )
