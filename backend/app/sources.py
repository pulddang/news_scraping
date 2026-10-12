from pathlib import Path

import yaml
from pydantic import BaseModel, HttpUrl
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Source

CATEGORIES = {
    "general": "종합",
    "politics": "정치",
    "economy": "경제",
    "society": "사회",
    "world": "국제",
    "tech": "IT·기술",
    "science": "과학",
    "culture": "문화",
}


class SourceSpec(BaseModel):
    key: str
    name: str
    feed_url: HttpUrl
    homepage: HttpUrl | None = None
    country: str
    lang: str
    category: str
    title_suffix: str | None = None
    enabled: bool = True

    def model_post_init(self, _ctx) -> None:
        if self.category not in CATEGORIES:
            raise ValueError(f"{self.key}: unknown category {self.category!r}")


def load_specs(path: Path) -> list[SourceSpec]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    specs = [SourceSpec(**item) for item in data.get("sources", [])]
    keys = [s.key for s in specs]
    dupes = {k for k in keys if keys.count(k) > 1}
    if dupes:
        raise ValueError(f"duplicate source keys: {sorted(dupes)}")
    return specs


def sync_sources(session: Session, specs: list[SourceSpec]) -> dict[str, int]:
    """YAML 목록을 DB에 반영해요. 목록에서 빠진 언론사는 지우지 않고 비활성화해요."""
    existing = {s.key: s for s in session.scalars(select(Source))}
    added = updated = disabled = 0

    for spec in specs:
        fields = {
            "name": spec.name,
            "feed_url": str(spec.feed_url),
            "homepage": str(spec.homepage) if spec.homepage else None,
            "country": spec.country.upper(),
            "lang": spec.lang,
            "category": spec.category,
            "title_suffix": spec.title_suffix,
            "enabled": spec.enabled,
        }
        source = existing.pop(spec.key, None)
        if source is None:
            session.add(Source(key=spec.key, consecutive_failures=0, **fields))
            added += 1
            continue
        if source.feed_url != fields["feed_url"]:
            source.etag = source.last_modified = None
        changed = False
        for name, value in fields.items():
            if getattr(source, name) != value:
                setattr(source, name, value)
                changed = True
        updated += changed

    for source in existing.values():
        if source.enabled:
            source.enabled = False
            disabled += 1

    session.commit()
    return {"added": added, "updated": updated, "disabled": disabled}
