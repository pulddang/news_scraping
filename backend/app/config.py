from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://news:news@localhost:5432/news"
    sources_file: Path = BACKEND_DIR / "sources.yaml"

    collect_interval_minutes: int = 15
    fetch_concurrency: int = 8
    fetch_timeout_seconds: float = 20.0
    user_agent: str = "Mozilla/5.0 (compatible; PersonalNewsReader/0.1)"

    # 오래된 기사는 이 기간이 지나면 지워요 (0이면 지우지 않음)
    article_retention_days: int = 90


settings = Settings()
