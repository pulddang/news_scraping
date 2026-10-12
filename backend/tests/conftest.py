import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from app.models import Base

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def session_factory():
    # TEST_DATABASE_URL이 있으면 실제 PostgreSQL로, 없으면 SQLite로 테스트해요
    url = os.environ.get("TEST_DATABASE_URL", "sqlite://")
    engine = create_engine(url)
    if engine.dialect.name == "sqlite":
        event.listen(engine, "connect", lambda conn, _: conn.execute("PRAGMA foreign_keys=ON"))
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield sessionmaker(bind=engine, expire_on_commit=False)
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def fixture_bytes():
    return lambda name: (FIXTURES / name).read_bytes()
