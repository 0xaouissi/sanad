"""SSRF-safe website crawler: fetch -> extract -> sanitize -> ingest.

Every hop (including redirects) is re-validated: http/https only, same
domain, all DNS answers checked against private/local ranges. The connection
then pins the validated IP (Host header + TLS SNI keep the original name), so
a second DNS lookup cannot rebind to an internal address. Crawled text passes
the same injection sanitizer as retrieved chunks before it is stored.
"""

import asyncio
import hashlib
import re
import time
from collections import deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import SplitResult, urlsplit, urlunsplit
from uuid import UUID

import httpx
import structlog
from sqlalchemy import func, select

from app.core.config import Settings, get_settings
from app.db.models import CrawlSource, CrawlStatus, Document, DocumentStatus
from app.db.session import get_session_factory
from app.providers.kv import get_kv_store
from app.rag.crawl import (
    CrawlError,
    canonical_url,
    extract_page,
    normalize_link,
    parse_robots,
    resolve_and_validate,
    same_domain,
    validate_url,
)
from app.rag.injection import sanitize_source
from app.services.answer_cache import bump_doc_epoch
from app.services.ingestion import document_path, ingest_document

log = structlog.get_logger()

_MAX_REDIRECTS = 5
_ALLOWED_CONTENT_TYPES = {"text/html", "application/xhtml+xml", "text/plain"}
# A crawl left "crawling" by a crashed process must not block new runs forever.
_STALE_CRAWL = timedelta(minutes=30)


@dataclass
class CrawledPage:
    url: str
    title: str
    text: str
    links: list[str]


def check_source_url(url: str, settings: Settings) -> str:
    """Synchronous pre-flight for the API: validate + DNS-check a seed URL."""
    canonical = canonical_url(url)
    resolve_and_validate(urlsplit(canonical).hostname, settings)
    return canonical


def crawl_in_progress(source: CrawlSource) -> bool:
    if source.status is not CrawlStatus.CRAWLING:
        return False
    return datetime.now(UTC) - source.updated_at < _STALE_CRAWL


async def safe_fetch(
    url: str,
    settings: Settings,
    client: httpx.AsyncClient,
    root_host: str,
    deadline: float,
) -> tuple[str, str, str]:
    """Fetch one URL with all SSRF guards. Returns (final_url, type, text)."""
    current = url
    budget = f"CRAWL_MAX_SECONDS={settings.crawl_max_seconds:g}s"
    for hop in range(_MAX_REDIRECTS + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise CrawlError(
                f"Crawl time budget ({budget}) exceeded before fetching '{current}'. "
                "Raise CRAWL_MAX_SECONDS in .env or crawl a smaller site."
            )
        parts = validate_url(current)
        host = parts.hostname
        if not same_domain(root_host, host):
            raise CrawlError(
                f"Refusing to leave the source domain: '{current}' is outside '{root_host}'. "
                "Only same-domain pages are crawled."
            )
        ips = await asyncio.to_thread(resolve_and_validate, host, settings)
        # Pin the validated IP for the connection: no second DNS lookup means
        # no rebinding window between validation and connect.
        ip = ips[0]
        netloc = f"[{ip}]" if ":" in ip else ip
        host_header = f"[{host}]" if ":" in host else host
        if parts.port is not None:
            netloc += f":{parts.port}"
            host_header += f":{parts.port}"
        pinned = urlunsplit((parts.scheme, netloc, parts.path or "/", parts.query, ""))
        headers = {
            "Host": host_header,
            "User-Agent": settings.crawl_user_agent,
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
        }
        extensions = {"sni_hostname": host} if parts.scheme == "https" else {}
        timeout = httpx.Timeout(min(settings.crawl_timeout_seconds, remaining))
        try:
            async with client.stream(
                "GET", pinned, headers=headers, extensions=extensions,
                timeout=timeout, follow_redirects=False,
            ) as response:
                if response.status_code in (301, 302, 303, 307, 308):
                    location = response.headers.get("location", "")
                    target = normalize_link(current, location)
                    if target is None:
                        raise CrawlError(
                            f"Redirect from '{current}' points to a non-http(s) or empty "
                            f"location ('{location}')."
                        )
                    if hop == _MAX_REDIRECTS:
                        raise CrawlError(
                            f"Too many redirects (more than {_MAX_REDIRECTS}) starting at '{url}'."
                        )
                    current = target
                    continue
                if response.status_code != 200:
                    raise CrawlError(
                        f"Site returned HTTP {response.status_code} for '{current}'.",
                        status_code=response.status_code,
                    )
                content_type = (
                    response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                )
                if content_type not in _ALLOWED_CONTENT_TYPES:
                    raise CrawlError(
                        f"Unsupported content type '{content_type or 'unknown'}' at '{current}'. "
                        "Only HTML and plain-text pages are crawled."
                    )
                encoding = response.charset_encoding or "utf-8"
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > settings.crawl_max_page_bytes:
                        raise CrawlError(
                            f"Page '{current}' is larger than "
                            f"CRAWL_MAX_PAGE_BYTES={settings.crawl_max_page_bytes}. "
                            "Raise the limit in .env or crawl a lighter page."
                        )
                    if time.monotonic() > deadline:
                        raise CrawlError(
                            f"Crawl time budget ({budget}) exceeded while "
                            f"downloading '{current}'."
                        )
                return current, content_type, bytes(body).decode(encoding, errors="replace")
        except httpx.HTTPError as exc:
            raise CrawlError(
                f"Could not fetch '{current}': {exc}. Check that the site is reachable "
                "from this server and retry."
            ) from exc
    raise CrawlError(f"Too many redirects (more than {_MAX_REDIRECTS}) starting at '{url}'.")


async def _fetch_robots(
    client: httpx.AsyncClient,
    parts: SplitResult,
    root_host: str,
    settings: Settings,
    deadline: float,
):
    robots_url = urlunsplit((parts.scheme, parts.netloc, "/robots.txt", "", ""))
    try:
        _, _, text = await safe_fetch(robots_url, settings, client, root_host, deadline)
    except CrawlError as exc:
        if exc.status_code == 404:
            return parse_robots("", robots_url)
        # Fail conservatively: an unreadable robots.txt is not a free pass.
        raise CrawlError(
            f"Could not read robots.txt at '{robots_url}': {exc} "
            "Crawling is refused until robots.txt is reachable or returns 404."
        ) from exc
    return parse_robots(text, robots_url)


def _make_page(url: str, content_type: str, text: str) -> CrawledPage:
    if content_type == "text/plain":
        return CrawledPage(url=url, title="", text=text.strip(), links=[])
    extracted = extract_page(text)
    return CrawledPage(url=url, title=extracted.title, text=extracted.text, links=extracted.links)


def _enqueue_links(
    links: list[str], base: str, root_host: str, visited: set[str], queue: deque[str]
) -> None:
    for href in links:
        link = normalize_link(base, href)
        if link and link not in visited and same_domain(root_host, urlsplit(link).hostname):
            queue.append(link)


async def _crawl_pages(url: str, settings: Settings) -> list[CrawledPage]:
    parts = validate_url(url)
    root_host = parts.hostname
    seed = canonical_url(url)
    deadline = time.monotonic() + settings.crawl_max_seconds
    pages: list[CrawledPage] = []
    async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
        robots = await _fetch_robots(client, parts, root_host, settings, deadline)
        if not robots.can_fetch(settings.crawl_user_agent, seed):
            raise CrawlError(
                f"robots.txt at '{root_host}' disallows crawling '{seed}'. "
                "Remove the Disallow rule or pick a different start URL."
            )
        final_url, content_type, text = await safe_fetch(
            seed, settings, client, root_host, deadline
        )
        page = _make_page(final_url, content_type, text)
        pages.append(page)
        visited = {seed, final_url}
        queue: deque[str] = deque()
        _enqueue_links(page.links, final_url, root_host, visited, queue)
        while queue and len(pages) < settings.crawl_max_pages:
            if time.monotonic() > deadline:
                log.warning("crawl_time_budget_reached", source=url, pages=len(pages))
                break
            current = queue.popleft()
            if current in visited:
                continue
            visited.add(current)
            if not robots.can_fetch(settings.crawl_user_agent, current):
                continue
            try:
                final_url, content_type, text = await safe_fetch(
                    current, settings, client, root_host, deadline
                )
            except CrawlError as exc:
                log.warning("crawl_page_skipped", url=current, error=str(exc))
                continue
            visited.add(final_url)
            page = _make_page(final_url, content_type, text)
            pages.append(page)
            _enqueue_links(page.links, final_url, root_host, visited, queue)
    return pages


def _page_filename(url: str) -> str:
    path = urlsplit(url).path.strip("/")
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", path).strip("-.")[:60] or "page"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{digest}.md"


async def _store_pages(
    company_id: UUID, source_id: UUID, pages: list[CrawledPage]
) -> tuple[set[UUID], set[UUID], list[UUID]]:
    """Create documents for new/changed pages. Returns (old_ids, keep_ids, new_ids).

    Old documents are NOT deleted here: re-sync must keep the previous content
    until the replacement is ingested (see _finalize).
    """
    old_ids: set[UUID] = set()
    keep_ids: set[UUID] = set()
    new_ids: list[UUID] = []
    to_write: list[tuple[Path, bytes]] = []
    async with get_session_factory()() as session:
        old_docs = list(
            await session.scalars(select(Document).where(Document.crawl_source_id == source_id))
        )
        old_by_sha = {d.sha256: d for d in old_docs}
        old_ids = {d.id for d in old_docs}
        for page in pages:
            text = sanitize_source(page.text).strip()
            if not text:
                continue
            title = sanitize_source(page.title).strip()
            header = f"# {title}\n\n" if title else ""
            markdown = f"{header}> Source: {page.url}\n\n{text}\n"
            data = markdown.encode("utf-8")
            digest = hashlib.sha256(data).hexdigest()
            if digest in old_by_sha:
                keep_ids.add(old_by_sha[digest].id)
                continue
            existing = await session.scalar(
                select(Document).where(
                    Document.company_id == company_id, Document.sha256 == digest
                )
            )
            if existing is not None:
                # Identical content already uploaded or crawled elsewhere.
                continue
            filename = _page_filename(page.url)
            doc = Document(
                company_id=company_id,
                filename=filename,
                sha256=digest,
                size_bytes=len(data),
                status=DocumentStatus.PENDING,
                crawl_source_id=source_id,
            )
            session.add(doc)
            await session.flush()
            new_ids.append(doc.id)
            to_write.append((document_path(company_id, doc.id, filename), data))
        await session.commit()
    for path, data in to_write:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    if new_ids or keep_ids:
        await bump_doc_epoch(get_kv_store(), company_id)
    return old_ids, keep_ids, new_ids


async def _finish(source_id: UUID, status: CrawlStatus, error: str | None = None) -> None:
    async with get_session_factory()() as session:
        source = await session.get(CrawlSource, source_id)
        if source is None:
            return
        source.status = status
        source.error = error
        await session.commit()


async def _finalize(
    source_id: UUID,
    company_id: UUID,
    pages: list[CrawledPage],
    old_ids: set[UUID],
    keep_ids: set[UUID],
    new_ids: list[UUID],
) -> None:
    """Drop outdated pages, then record the sync result on the source."""
    async with get_session_factory()() as session:
        source = await session.get(CrawlSource, source_id)
        if source is None:
            return
        new_docs = []
        if new_ids:
            new_docs = list(await session.scalars(select(Document).where(Document.id.in_(new_ids))))
        new_by_name = {d.filename: d for d in new_docs}
        for old_id in old_ids - keep_ids:
            old = await session.get(Document, old_id)
            if old is None:
                continue
            replacement = new_by_name.get(old.filename)
            if replacement is not None and replacement.status is not DocumentStatus.READY:
                # Replacement failed to ingest: keep the old working copy.
                continue
            path = document_path(company_id, old.id, old.filename)
            await session.delete(old)
            await session.commit()
            path.unlink(missing_ok=True)
        ready = await session.scalar(
            select(func.count())
            .select_from(Document)
            .where(
                Document.crawl_source_id == source_id,
                Document.status == DocumentStatus.READY,
            )
        )
        source.pages_crawled = len(pages)
        if ready:
            source.status = CrawlStatus.READY
            source.error = None
            source.last_synced_at = datetime.now(UTC)
        else:
            source.status = CrawlStatus.FAILED
            source.error = (
                "Crawled pages produced no usable documents. Check the site content "
                "and the document errors on the Documents page."
            )
        await session.commit()
    await bump_doc_epoch(get_kv_store(), company_id)


async def crawl_source(source_id: UUID) -> None:
    """Background task: crawl a source and (re-)index its pages as documents."""
    settings = get_settings()
    async with get_session_factory()() as session:
        source = await session.get(CrawlSource, source_id)
        if source is None:
            return
        if crawl_in_progress(source):
            return
        source.status = CrawlStatus.CRAWLING
        source.error = None
        await session.commit()
        company_id = source.company_id
        url = source.url

    try:
        pages = await _crawl_pages(url, settings)
    except CrawlError as exc:
        log.warning("crawl_failed", source_id=str(source_id), error=str(exc))
        await _finish(source_id, CrawlStatus.FAILED, str(exc))
        return
    except Exception as exc:
        log.exception("crawl_unexpected_error", source_id=str(source_id))
        await _finish(source_id, CrawlStatus.FAILED, f"Unexpected crawl error: {exc}")
        return

    if not pages:
        await _finish(
            source_id,
            CrawlStatus.FAILED,
            "No pages could be crawled. Check robots.txt rules and that the "
            "start URL returns content.",
        )
        return

    try:
        old_ids, keep_ids, new_ids = await _store_pages(company_id, source_id, pages)
    except Exception as exc:
        log.exception("crawl_store_failed", source_id=str(source_id))
        await _finish(source_id, CrawlStatus.FAILED, f"Could not store crawled pages: {exc}")
        return

    if not new_ids and not keep_ids:
        await _finish(
            source_id,
            CrawlStatus.FAILED,
            "Crawled pages contained no usable text (empty or injection-only). "
            "Previous documents were kept.",
        )
        return

    for doc_id in new_ids:
        await ingest_document(doc_id)
    try:
        await _finalize(source_id, company_id, pages, old_ids, keep_ids, new_ids)
    except Exception as exc:
        log.exception("crawl_finalize_failed", source_id=str(source_id))
        await _finish(source_id, CrawlStatus.FAILED, f"Could not finalize crawl: {exc}")
        return
    log.info("crawl_done", source_id=str(source_id), pages=len(pages), new_documents=len(new_ids))


async def sync_due_sources() -> list[UUID]:
    """Re-crawl sources whose last sync (or last attempt) is older than the interval."""
    settings = get_settings()
    if settings.crawl_resync_hours <= 0:
        return []
    cutoff = datetime.now(UTC) - timedelta(hours=settings.crawl_resync_hours)
    stale_cutoff = datetime.now(UTC) - _STALE_CRAWL
    async with get_session_factory()() as session:
        due = await session.scalars(
            select(CrawlSource).where(
                func.coalesce(CrawlSource.last_synced_at, CrawlSource.updated_at) < cutoff,
                (CrawlSource.status != CrawlStatus.CRAWLING)
                | (CrawlSource.updated_at < stale_cutoff),
            )
        )
        ids = [s.id for s in due]
    for source_id in ids:
        await crawl_source(source_id)
    return ids


async def resync_loop() -> None:
    """Lifespan task: periodically re-sync due sources. 0 hours disables it."""
    settings = get_settings()
    if settings.crawl_resync_hours <= 0:
        return
    tick = min(settings.crawl_resync_hours * 3600, 300)
    while True:
        await asyncio.sleep(tick)
        try:
            synced = await sync_due_sources()
            if synced:
                log.info("crawl_resync_tick", sources=len(synced))
        except Exception:
            log.exception("crawl_resync_tick_failed")