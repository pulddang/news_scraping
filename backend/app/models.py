from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Source(Base):
    """언론사 피드 하나. sources.yaml과 동기화돼요."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    feed_url: Mapped[str] = mapped_column(Text)
    homepage: Mapped[str | None] = mapped_column(Text)
    country: Mapped[str] = mapped_column(String(2))
    lang: Mapped[str] = mapped_column(String(8))
    category: Mapped[str] = mapped_column(String(32))
    title_suffix: Mapped[str | None] = mapped_column(String(100))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # 조건부 요청(304)용 캐시 헤더
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)

    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)

    articles: Mapped[list["Article"]] = relationship(back_populates="source")


class Article(Base):
    __tablename__ = "articles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text, unique=True)
    guid: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(Text)
    image_url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    # 조회를 빠르게 하려고 언론사 값을 복사해 둬요
    lang: Mapped[str] = mapped_column(String(8))
    category: Mapped[str] = mapped_column(String(32))

    # 2단계(중복 묶기)에서 채워요
    cluster_id: Mapped[int | None] = mapped_column(Integer, index=True)

    source: Mapped[Source] = relationship(back_populates="articles")

    __table_args__ = (
        Index("ix_articles_published_at", "published_at"),
        Index("ix_articles_category_published", "category", "published_at"),
    )
