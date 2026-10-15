# news_scraping

국내외 주요 언론사 뉴스를 모아 보는 개인용 뉴스 리더예요.

## 진행 상황

1. **수집기와 언론사 목록** ← 지금 여기
2. 중복 묶기, 폴더, 검색
3. 웹과 모바일 화면 (PWA)
4. 영어 단어 주석 (Claude API)

## 구성

```
backend/
  sources.yaml     수집할 언론사 목록 (직접 고쳐도 돼요)
  app/collector.py RSS 수집, 정리, 중복 URL 제거
  app/sources.py   sources.yaml ↔ DB 동기화
  app/cli.py       명령어 (init-db, sync-sources, collect, check-sources, worker)
docker-compose.yml PostgreSQL + 수집기
```

수집기는 15분마다 모든 피드를 확인해요. 바뀌지 않은 피드는 ETag로 건너뛰고, 같은 기사 주소는 한 번만 저장해요. 90일이 지난 기사는 자동으로 지워요.

## 서버에서 실행하기 (Oracle Cloud)

처음이라면 [Oracle 서버 만들기 안내](docs/oracle-setup.md)를 먼저 따라 해주세요. 아래는 Docker가 설치된 Ubuntu 서버 기준 요약이에요.

```bash
git clone https://github.com/pulddang/news_scraping.git
cd news_scraping
cp .env.example .env
nano .env                      # POSTGRES_PASSWORD를 바꿔주세요

docker compose up -d --build   # DB와 수집기 시작
docker compose logs -f collector
```

언론사 피드가 잘 동작하는지 확인하려면:

```bash
docker compose run --rm collector python -m app.cli check-sources
```

`FAIL`이나 `EMPTY`로 나오는 피드는 `sources.yaml`에서 주소를 고치거나 `enabled: false`로 꺼주세요. 목록을 고친 뒤에는 `docker compose restart collector`만 하면 돼요.

수집된 기사 수 확인:

```bash
docker compose exec db psql -U news -c "select s.name, count(*) from articles a join sources s on s.id=a.source_id group by 1 order by 2 desc;"
```

## 개발

```bash
cd backend
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
pytest                                    # SQLite로 테스트
TEST_DATABASE_URL=postgresql+psycopg://... pytest   # PostgreSQL로 테스트
```
