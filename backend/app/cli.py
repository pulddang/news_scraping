"""명령어 모음.

  python -m app.cli init-db        테이블 만들기
  python -m app.cli sync-sources   sources.yaml을 DB에 반영
  python -m app.cli collect        한 번 수집
  python -m app.cli check-sources  피드 주소가 동작하는지 확인 (저장 안 함)
  python -m app.cli worker         주기적으로 계속 수집
"""

import argparse
import asyncio
import logging
import time

import feedparser

from app import collector
from app.config import settings
from app.db import SessionLocal, init_db
from app.sources import load_specs, sync_sources

log = logging.getLogger("app.cli")


def cmd_init_db(_args) -> None:
    init_db()
    print("tables ready")


def cmd_sync_sources(_args) -> None:
    with SessionLocal() as session:
        print(sync_sources(session, load_specs(settings.sources_file)))


def cmd_collect(_args) -> None:
    report = asyncio.run(collector.collect(SessionLocal))
    print(f"sources={report.sources} new={report.new_articles} "
          f"not_modified={report.not_modified} failed={len(report.failed)}")
    for key, error in report.failed.items():
        print(f"  FAIL {key}: {error}")


def cmd_check_sources(_args) -> None:
    specs = load_specs(settings.sources_file)

    async def check():
        async with collector.make_client() as client:
            results = await asyncio.gather(*(
                collector.fetch_feed(client, i, str(spec.feed_url), None, None)
                for i, spec in enumerate(specs)
            ))
        bad = 0
        for spec, result in zip(specs, results):
            if result.error:
                bad += 1
                print(f"FAIL  {spec.key:20s} {result.error}")
                continue
            entries = feedparser.parse(result.content).entries
            mark = "OK  " if entries else "EMPTY"
            bad += not entries
            title = entries[0].get("title", "")[:50] if entries else ""
            print(f"{mark}  {spec.key:20s} {len(entries):3d} items  {title}")
        print(f"\n{len(specs) - bad}/{len(specs)} feeds working")

    asyncio.run(check())


def cmd_worker(_args) -> None:
    init_db()
    interval = settings.collect_interval_minutes * 60
    while True:
        started = time.monotonic()
        try:
            with SessionLocal() as session:
                sync_sources(session, load_specs(settings.sources_file))
            report = asyncio.run(collector.collect(SessionLocal))
            with SessionLocal() as session:
                pruned = collector.prune_old_articles(session, settings.article_retention_days)
            log.info("collected: sources=%d new=%d failed=%d pruned=%d",
                     report.sources, report.new_articles, len(report.failed), pruned)
        except Exception:
            log.exception("collect run failed")
        time.sleep(max(0, interval - (time.monotonic() - started)))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, fn in [
        ("init-db", cmd_init_db),
        ("sync-sources", cmd_sync_sources),
        ("collect", cmd_collect),
        ("check-sources", cmd_check_sources),
        ("worker", cmd_worker),
    ]:
        sub.add_parser(name).set_defaults(func=fn)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
