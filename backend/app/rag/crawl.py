"""Pure URL/SSRF validation and HTML extraction for the website crawler.

No network I/O except DNS resolution (resolve_host), so every guard here is
unit-testable. The fetching service (app/services/crawler.py) re-validates
every redirect hop and pins the resolved IP for the actual connection.
"""

import ipaddress
import socket
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import SplitResult, urldefrag, urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

from app.core.config import Settings

_ALLOWED_SCHEMES = ("http", "https")
_CGNAT = ipaddress.ip_network("100.64.0.0/10")


class CrawlError(ValueError):
    """Crawl refusal/failure; the message tells the user how to fix it."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _rebuild(parts: SplitResult) -> str:
    host = (parts.hostname or "").lower()
    netloc = f"[{host}]" if ":" in host else host
    if parts.port is not None:
        netloc += f":{parts.port}"
    return urlunsplit((parts.scheme.lower(), netloc, parts.path or "/", parts.query, ""))


def validate_url(url: str) -> SplitResult:
    """Return urlsplit parts for a crawlable http(s) URL, or raise CrawlError."""
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise CrawlError(
            f"Invalid URL '{url}': {exc}. Use a full URL like https://example.com/policies."
        ) from exc
    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        raise CrawlError(
            f"Only http and https URLs can be crawled (got '{parts.scheme or 'no scheme'}'). "
            "Use a full URL like https://example.com/policies."
        )
    if not parts.hostname:
        raise CrawlError(
            f"URL '{url}' has no hostname. Use a full URL like https://example.com/policies."
        )
    if parts.username is not None or parts.password is not None:
        raise CrawlError(
            "URLs with embedded credentials (user:pass@host) are not allowed. "
            "Remove them and retry."
        )
    try:
        _ = parts.port
    except ValueError as exc:
        raise CrawlError(f"Invalid port in URL '{url}'. Use a number between 1 and 65535.") from exc
    return parts


def canonical_url(url: str) -> str:
    """Validate + normalize a seed URL (lowercase host, no fragment, path '/')."""
    return _rebuild(validate_url(url))


def is_blocked_ip(ip: str) -> bool:
    """True for private/local/reserved addresses that must never be crawled."""
    try:
        addr = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return True
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return (
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_multicast
        or addr.is_unspecified
        or not addr.is_global
        or addr in _CGNAT
    )


def resolve_host(host: str) -> list[str]:
    """All DNS answers for a host (module-level so tests can monkeypatch it)."""
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise CrawlError(
            f"Could not resolve '{host}': {exc}. Check the URL spelling and that the "
            "site is publicly reachable from this server."
        ) from exc
    return sorted({info[4][0].split("%", 1)[0] for info in infos})


def resolve_and_validate(host: str, settings: Settings) -> list[str]:
    """Resolve a host and refuse if ANY answer is a private/local address."""
    ips = resolve_host(host)
    if not ips:
        raise CrawlError(f"'{host}' resolved to no addresses. Check the URL and retry.")
    blocked = [ip for ip in ips if is_blocked_ip(ip)]
    if blocked and not settings.crawl_allow_private:
        raise CrawlError(
            f"'{host}' resolves to a private/local address ({', '.join(blocked)}). "
            "Crawling internal networks is blocked (SSRF protection). Use a public "
            "website URL; for local development only, set CRAWL_ALLOW_PRIVATE=true in .env."
        )
    return ips


def _normalize_host(host: str) -> str:
    host = host.lower().strip(".")
    return host[4:] if host.startswith("www.") else host


def same_domain(root_host: str, host: str) -> bool:
    """Equal domains or subdomains of each other, ignoring a leading 'www.'."""
    a, b = _normalize_host(root_host), _normalize_host(host)
    if not a or not b:
        return False
    return a == b or a.endswith("." + b) or b.endswith("." + a)


def normalize_link(base_url: str, href: str) -> str | None:
    """Absolute, defragmented http(s) link, or None for non-crawlable hrefs."""
    href = href.strip()
    if not href or href.startswith("#"):
        return None
    try:
        parts = urlsplit(urldefrag(urljoin(base_url, href))[0])
        _ = parts.port
    except ValueError:
        return None
    if parts.scheme.lower() not in _ALLOWED_SCHEMES or not parts.hostname:
        return None
    if parts.username is not None or parts.password is not None:
        return None
    return _rebuild(parts)


@dataclass
class ExtractedPage:
    title: str = ""
    text: str = ""
    links: list[str] = field(default_factory=list)


_SKIP_TAGS = {"script", "style", "noscript", "template"}
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BLOCK_TAGS = _HEADING_TAGS | {
    "p", "div", "section", "article", "header", "footer", "main", "aside", "nav",
    "ul", "ol", "li", "dl", "dt", "dd", "table", "tr", "blockquote", "pre",
    "figure", "figcaption", "form", "fieldset", "address", "hr",
}


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.pieces: list[str] = []
        self.title_parts: list[str] = []
        self.links: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = True
        elif tag == "a":
            for name, value in attrs:
                if name == "href" and value:
                    self.links.append(value)
        elif tag == "br":
            self.pieces.append("\n")
        elif tag in _HEADING_TAGS:
            self.pieces.append("\n\n# ")
        elif tag == "li":
            self.pieces.append("\n- ")
        elif tag in _BLOCK_TAGS:
            self.pieces.append("\n")

    def handle_endtag(self, tag) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth:
            return
        if tag == "title":
            self._in_title = False
        elif tag in _BLOCK_TAGS:
            self.pieces.append("\n")

    def handle_data(self, data) -> None:
        if self._skip_depth:
            return
        if self._in_title:
            self.title_parts.append(data)
        else:
            self.pieces.append(data)


def extract_page(html: str) -> ExtractedPage:
    """Visible text as lightweight markdown (headings '# ', list items '- ')."""
    parser = _PageParser()
    parser.feed(html)
    parser.close()
    lines = [" ".join(line.split()) for line in "".join(parser.pieces).splitlines()]
    return ExtractedPage(
        title=" ".join("".join(parser.title_parts).split()),
        text="\n".join(line for line in lines if line),
        links=parser.links,
    )


def parse_robots(text: str, base_url: str = "") -> RobotFileParser:
    """Empty text (e.g. robots.txt returned 404) means 'allow everything'."""
    parser = RobotFileParser(url=base_url)
    parser.parse(text.splitlines())
    return parser