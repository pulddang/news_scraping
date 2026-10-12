import asyncio
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select

from app import collector
from app.config import settings
from app.models import Article, Source
from app.sources import SourceSpec, load_specs, sync_sources


def add_sources(session_factory):
    specs = [
        SourceSpec(key="ko", name="한국 테스트", feed_url="https://feeds.test/ko.xml",
                   country="kr", lang="ko", category="general"),
        SourceSpec(key="en", name="World Test", feed_url="https://feeds.test/en.xml",
                   country="US", lang="en", category="world", title_suffix=" - Example Wire"),
        SourceSpec(key="broken", name="Broken", feed_url="https://feeds.test/broken.xml",
                   country="US", lang="en", category="world"),
    ]
    with session_factory() as session:
        sync_sources(session, specs)
    return specs


def mock_client(fixture_bytes, calls):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        path = request.url.path
        if path == "/broken.xml":
            return httpx.Response(500)
        if request.headers.get("if-none-match") == '"v1"':
            return httpx.Response(304)
        body = fixture_bytes("rss_ko.xml" if path == "/ko.xml" else "atom_en.xml")
        return httpx.Response(200, content=body, headers={"ETag": '"v1"'})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def run_collect(session_factory, client):
    return asyncio.run(collector.collect(session_factory, client=client))


def test_canonicalize_url_strips_tracking_and_fragment():
    assert (collector.canonicalize_url("https://News.Example.kr/a?id=3&utm_source=x&fbclid=y#top")
            == "https://news.example.kr/a?id=3")
    assert collector.canonicalize_url("https://x.com/a?page=2") == "https://x.com/a?page=2"


def test_clean_text_removes_tags_and_scripts():
    assert collector.clean_text("<p>Hello <b>world</b></p><script>bad()</script>&amp; more") == "Hello world & more"
    assert collector.clean_text(None) == ""


def test_collect_stores_articles_and_records_failures(session_factory, fixture_bytes):
    add_sources(session_factory)
    report = run_collect(session_factory, mock_client(fixture_bytes, []))

    assert report.sources == 3
    assert report.new_articles == 4  # 국내 2건(링크 없는 기사 제외) + 해외 2건
    assert set(report.failed) == {"broken"}

    with session_factory() as session:
        ko = session.scalar(select(Article).where(Article.guid == "news-1"))
        assert ko.url == "https://news.example.kr/article/1?id=1"
        assert ko.title == "정부, 내년 예산안 발표"
        assert ko.summary == "정부가 내년 예산안을 발표했다."
        assert ko.image_url == "https://img.example.kr/1.jpg"
        assert ko.lang == "ko" and ko.category == "general"
        assert ko.published_at.replace(tzinfo=timezone.utc) == datetime(2026, 10, 11, 16, 0, tzinfo=timezone.utc)

        second = session.scalar(select(Article).where(Article.title == "반도체 수출 증가"))
        assert second.url == "https://news.example.kr/article/2"
        assert second.summary is None  # 제목과 같은 요약은 버려요

        en = session.scalar(select(Article).where(Article.url == "https://world.example.com/2026/10/rates"))
        assert en.title == "Central bank raises rates"
        assert en.summary == "The central bank unexpectedly raised rates."
        assert en.author == "Jane Doe"

        future = session.scalar(select(Article).where(Article.url.like("%/2099/%")))
        assert future.published_at.replace(tzinfo=timezone.utc) <= datetime.now(timezone.utc)

        broken = session.scalar(select(Source).where(Source.key == "broken"))
        assert broken.consecutive_failures == 1
        assert broken.last_error == "HTTP 500"
        ok = session.scalar(select(Source).where(Source.key == "ko"))
        assert ok.etag == '"v1"' and ok.last_success_at is not None


def test_second_run_uses_etag_and_does_not_duplicate(session_factory, fixture_bytes):
    add_sources(session_factory)
    run_collect(session_factory, mock_client(fixture_bytes, []))

    calls = []
    report = run_collect(session_factory, mock_client(fixture_bytes, calls))

    assert report.new_articles == 0
    assert report.not_modified == 2
    assert all(c.headers.get("if-none-match") == '"v1"' for c in calls if c.url.path != "/broken.xml")
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Article)) == 4
        broken = session.scalar(select(Source).where(Source.key == "broken"))
        assert broken.consecutive_failures == 2


def test_same_article_refetched_without_etag_is_not_duplicated(session_factory, fixture_bytes):
    add_sources(session_factory)
    run_collect(session_factory, mock_client(fixture_bytes, []))
    with session_factory() as session:
        for s in session.scalars(select(Source)):
            s.etag = None
        session.commit()

    report = run_collect(session_factory, mock_client(fixture_bytes, []))
    assert report.new_articles == 0


def test_disabled_sources_are_skipped(session_factory, fixture_bytes):
    add_sources(session_factory)
    with session_factory() as session:
        session.scalar(select(Source).where(Source.key == "broken")).enabled = False
        session.commit()
    calls = []
    report = run_collect(session_factory, mock_client(fixture_bytes, calls))
    assert report.sources == 2 and not report.failed
    assert all(c.url.path != "/broken.xml" for c in calls)


def test_sync_sources_updates_and_disables_removed(session_factory):
    specs = add_sources(session_factory)
    with session_factory() as session:
        session.scalar(select(Source).where(Source.key == "ko")).etag = '"old"'
        session.commit()

    specs[0] = specs[0].model_copy(update={"feed_url": "https://feeds.test/ko-new.xml"})
    with session_factory() as session:
        result = sync_sources(session, specs[:2])
        assert result == {"added": 0, "updated": 1, "disabled": 1}
        ko = session.scalar(select(Source).where(Source.key == "ko"))
        assert ko.feed_url == "https://feeds.test/ko-new.xml"
        assert ko.etag is None  # 주소가 바뀌면 캐시 헤더를 비워요
        assert ko.country == "KR"
        assert not session.scalar(select(Source).where(Source.key == "broken")).enabled


def test_prune_old_articles(session_factory, fixture_bytes):
    add_sources(session_factory)
    run_collect(session_factory, mock_client(fixture_bytes, []))
    with session_factory() as session:
        old = session.scalar(select(Article).where(Article.guid == "news-1"))
        old.published_at = datetime.now(timezone.utc) - timedelta(days=200)
        session.commit()
        assert collector.prune_old_articles(session, 90) == 1
        assert collector.prune_old_articles(session, 0) == 0


def test_bundled_sources_file_is_valid():
    specs = load_specs(settings.sources_file)
    assert len(specs) >= 20
    assert {s.lang for s in specs} == {"ko", "en"}
