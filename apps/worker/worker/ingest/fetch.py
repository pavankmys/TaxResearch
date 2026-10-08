"""Safe HTTP fetch for URL loads (M2 decision 8).

URL loads are triggered by people and run on the server, so every hop is checked:
scheme, host allow-list, resolved addresses (no private, loopback, link-local, reserved or
multicast targets), content type, and a size cap. Redirects are followed by hand so that
each target is checked before it is requested.
"""

import ipaddress
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from worker.config import FetchConfig, SourceConfig
from worker.errors import PermanentError

MAX_REDIRECTS = 5
REDIRECT_CODES = frozenset({301, 302, 303, 307, 308})

Resolver = Callable[[str], Iterable[str]]


class FetchError(Exception):
    """A transient fetch failure (network error, timeout, HTTP error status). Retryable."""


class FetchRefused(PermanentError):
    """The URL was refused by a safety check. Retrying the same URL will not help."""


@dataclass(frozen=True)
class FetchResult:
    """The downloaded bytes and what the server said about them."""

    data: bytes
    content_type: str
    final_url: str
    etag: str | None


def default_resolver(host: str) -> list[str]:
    """Resolve a host name to its IP addresses with the system resolver."""
    infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def _is_forbidden_address(text: str) -> bool:
    address = ipaddress.ip_address(text.split("%", 1)[0])
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped is not None:
        address = address.ipv4_mapped
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def check_url(url: str, source: SourceConfig, resolver: Resolver) -> None:
    """Raise FetchRefused unless the URL may be fetched for this source."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise FetchRefused(f"scheme not allowed: {parts.scheme or '(none)'}")
    host = (parts.hostname or "").lower()
    if not host:
        raise FetchRefused("URL has no host")
    if host not in source.allowed_hosts:
        raise FetchRefused(f"host not allowed for source {source.code}: {host}")
    try:
        addresses = list(resolver(host))
    except OSError as exc:
        raise FetchError(f"could not resolve {host}: {exc}") from exc
    if not addresses:
        raise FetchRefused(f"host does not resolve: {host}")
    for address in addresses:
        try:
            forbidden = _is_forbidden_address(address)
        except ValueError as exc:
            raise FetchRefused(f"unparseable address for {host}: {address}") from exc
        if forbidden:
            raise FetchRefused(f"host resolves to a non-public address: {host}")


def _media_type(header: str | None) -> str:
    return (header or "").split(";", 1)[0].strip().lower()


def fetch_url(
    url: str,
    source: SourceConfig,
    cfg: FetchConfig,
    *,
    transport: httpx.BaseTransport | None = None,
    resolver: Resolver | None = None,
) -> FetchResult:
    """Download a URL for a source, with every safety check applied per hop.

    Args:
        url: The URL the person asked for.
        source: The source whose allowed_hosts and user agent apply.
        cfg: Size cap, timeout and allowed content types.
        transport: Optional httpx transport (tests inject httpx.MockTransport).
        resolver: Optional host resolver (tests inject a fake).

    Raises:
        FetchRefused: a safety check failed (permanent).
        FetchError: network failure or a non-2xx status (retryable).
    """
    resolve = resolver or default_resolver
    headers = {
        "User-Agent": source.user_agent,
        "Accept": "application/pdf,text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
    }
    timeout = httpx.Timeout(cfg.timeout_seconds)
    current = url
    with httpx.Client(
        transport=transport,
        follow_redirects=False,
        timeout=timeout,
        headers=headers,
    ) as client:
        for _hop in range(MAX_REDIRECTS + 1):
            check_url(current, source, resolve)
            try:
                with client.stream("GET", current) as response:
                    if response.status_code in REDIRECT_CODES and "location" in response.headers:
                        current = urljoin(current, response.headers["location"])
                        continue
                    if not 200 <= response.status_code < 300:
                        raise FetchError(f"HTTP {response.status_code} from {current}")
                    content_type = _media_type(response.headers.get("content-type"))
                    if content_type not in cfg.allowed_content_types:
                        raise FetchRefused(f"content type not allowed: {content_type or '(none)'}")
                    declared = response.headers.get("content-length")
                    if (
                        declared is not None
                        and declared.isdigit()
                        and int(declared) > cfg.max_bytes
                    ):
                        raise FetchRefused("too large")
                    body = bytearray()
                    for chunk in response.iter_bytes():
                        body.extend(chunk)
                        if len(body) > cfg.max_bytes:
                            raise FetchRefused("too large")
                    return FetchResult(
                        data=bytes(body),
                        content_type=content_type,
                        final_url=current,
                        etag=response.headers.get("etag"),
                    )
            except httpx.TransportError as exc:
                raise FetchError(f"network error fetching {current}: {exc}") from exc
    raise FetchRefused(f"too many redirects (more than {MAX_REDIRECTS})")
