"""RSS/Atom 피드를 가져와 기사로 저장하는 수집기."""

import asyncio
import calendar
import html
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import httpx
from sqlalchemy import delete, select
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings
from app.models import Article, Source

log = logging.getLogger(__name__)

TRACKING_PARAMS = {"fbclid", "gclid", "ocid", "cmpid"}
TRACKING_PREFIXES = ("utm_", "mc_")
SUMMARY_MAX_CHARS = 1000


def canonicalize_url(url: str) -> str:
    """추적용 파라미터와 #조각을 지워 같은 기사가 다른 주소로 두 번 저장되지 않게 해요."""
    parts = urlsplit(url.strip())
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith(TRACKING_PREFIXES)
    ]
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, urlencode(query), ""))


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.chunks: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in ("br", "p", "div", "li"):
            self.chunks.append(" ")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        elif tag in ("p", "div", "li"):
            self.chunks.append(" ")

    def handle_data(self, data):
        if not self._skip:
            self.chunks.append(data)


def clean_text(raw: str | None) -> str:
    if not raw:
        return ""
    parser = _TextExtractor()
    parser.feed(raw)
    parser.close()
    text = html.unescape("".join(parser.chunks))
    return re.sub(r"\s+", " ", text).strip()


def entry_time(entry, now: datetime) -> datetime:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        parsed = entry.get(key)
        if parsed:
            ts = datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)
            # 미래 시각이 찍힌 피드가 맨 위를 차지하지 않도록 막아요
            return min(ts, now)
    return now


def entry_image(entry) -> str | None:
    for media in entry.get("media_content", []) + entry.get("media_thumbnail", []):
        if media.get("url"):
            return media["url"]
    for enc in entry.get("enclosures", []):
        if enc.get("type", "").startswith("image/") and enc.get("href"):
            return enc["href"]
    return None


def parse_entry(entry, source: Source, now: datetime) -> dict | None:
    link = entry.get("link") or entry.get("id")
    title = clean_text(entry.get("title"))
    if not link or not title or not link.startswith(("http://", "https://")):
        return None
    if source.title_suffix and title.endswith(source.title_suffix):
        title = title[: -len(source.title_suffix)].rstrip()

    summary = clean_text(entry.get("summary") or entry.get("description"))
    if summary == title:
        summary = ""
    return {
        "source_id": source.id,
        "url": canonicalize_url(link),
        "guid": entry.get("id"),
        "title": title,
        "summary": summary[:SUMMARY_MAX_CHARS] or None,
        "author": clean_text(entry.get("author")) or None,
        "image_url": entry_image(entry),
        "published_at": entry_time(entry, now),
        "fetched_at": now,
        "lang": source.lang,
        "category": source.category,
    }


@dataclass
class FetchResult:
    source_id: int
    status: int | None = None
    content: bytes | None = None
    etag: str | None = None
    last_modified: str | None = None
    error: str | None = None


@dataclass
class CollectReport:
    sources: int = 0
    new_articles: int = 0
    not_modified: int = 0
    failed: dict[str, str] = field(default_factory=dict)


async def fetch_feed(client: httpx.AsyncClient, source_id: int, url: str,
                     etag: str | None, last_modified: str | None) -> FetchResult:
    headers = {}
    if etag:
        headers["If-None-Match"] = etag
    if last_modified:
        headers["If-Modified-Since"] = last_modified
    try:
        resp = await client.get(url, headers=headers)
    except httpx.HTTPError as exc:
        return FetchResult(source_id, error=f"{type(exc).__name__}: {exc}"[:500])
    if resp.status_code == 304:
        return FetchResult(source_id, status=304)
    if resp.status_code >= 400:
        return FetchResult(source_id, status=resp.status_code, error=f"HTTP {resp.status_code}")
    return FetchResult(
        source_id,
        status=resp.status_code,
        content=resp.content,
        etag=resp.headers.get("etag"),
        last_modified=resp.headers.get("last-modified"),
    )


def _insert(session: Session):
    dialect = session.get_bind().dialect.name
    return (postgresql if dialect == "postgresql" else sqlite).insert(Article)


def store_result(session: Session, source: Source, result: FetchResult, now: datetime) -> int:
    """가져온 결과를 저장하고 새로 들어온 기사 수를 돌려줘요."""
    source.last_fetched_at = now

    if result.error is None and result.content is not None:
        feed = feedparser.parse(result.content)
        if not feed.entries and feed.bozo:
            result.error = f"parse error: {feed.get('bozo_exception')}"[:500]

    if result.error:
        source.last_error = result.error
        source.consecutive_failures = (source.consecutive_failures or 0) + 1
        session.commit()
        return 0

    source.last_error = None
    source.consecutive_failures = 0
    source.last_success_at = now
    if result.status == 304:
        session.commit()
        return 0

    source.etag = result.etag
    source.last_modified = result.last_modified
    rows = {}
    for entry in feed.entries:
        row = parse_entry(entry, source, now)
        if row:
            rows[row["url"]] = row
    inserted = 0
    if rows:
        stmt = _insert(session).values(list(rows.values()))
        stmt = stmt.on_conflict_do_nothing(index_elements=["url"]).returning(Article.id)
        inserted = len(session.execute(stmt).all())
    session.commit()
    return inserted


def make_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=settings.fetch_timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": settings.user_agent},
    )


async def collect(session_factory: sessionmaker, client: httpx.AsyncClient | None = None,
                  concurrency: int | None = None) -> CollectReport:
    """활성화된 모든 언론사 피드를 한 번 수집해요."""
    with session_factory() as session:
        sources = session.scalars(select(Source).where(Source.enabled.is_(True))).all()
        jobs = [(s.id, s.feed_url, s.etag, s.last_modified) for s in sources]

    report = CollectReport(sources=len(jobs))
    if not jobs:
        return report

    sem = asyncio.Semaphore(concurrency or settings.fetch_concurrency)
    own_client = client is None
    client = client or make_client()

    async def run(job):
        async with sem:
            return await fetch_feed(client, *job)

    try:
        results = await asyncio.gather(*(run(job) for job in jobs))
    finally:
        if own_client:
            await client.aclose()

    now = datetime.now(timezone.utc)
    with session_factory() as session:
        for result in results:
            source = session.get(Source, result.source_id)
            new = store_result(session, source, result, now)
            report.new_articles += new
            if result.status == 304:
                report.not_modified += 1
            if result.error:
                report.failed[source.key] = result.error
                log.warning("feed failed: %s: %s", source.key, result.error)
            else:
                log.info("feed ok: %s: %d new", source.key, new)
    return report


def prune_old_articles(session: Session, days: int) -> int:
    if days <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    result = session.execute(delete(Article).where(Article.published_at < cutoff))
    session.commit()
    return result.rowcount or 0
