# Oracle Cloud 서버에 올리기

처음 한 번만 하면 되는 작업이에요. 끝나면 수집기가 서버에서 24시간 돌아가요.

> 무료 조건과 화면 메뉴 이름은 Oracle이 종종 바꿔요. 아래와 다르게 보이면 비슷한 이름의 메뉴를 찾거나 화면을 캡처해서 보여주세요.

## 1. Oracle Cloud 가입

1. https://www.oracle.com/cloud/free/ 에서 **Start for free**를 눌러 가입해요.
2. **홈 리전(Home Region)** 을 고르는 단계가 있어요. 나중에 바꿀 수 없어요.
   - 한국이라면 **South Korea Central (Seoul)** 또는 **South Korea North (Chuncheon)** 중에서 골라요.
   - 무료 ARM 서버는 인기가 많아 서울이 자주 꽉 차 있어요. 춘천이 상대적으로 여유 있다는 이야기가 많아요.
3. 카드 인증이 있지만, 무료(Always Free) 범위 안에서만 쓰면 요금이 나가지 않아요.

## 2. 서버(VM) 만들기

1. 콘솔 왼쪽 위 메뉴 → **Compute** → **Instances** → **Create instance**
2. **Image**: Change image → **Canonical Ubuntu 24.04** (없으면 22.04)
3. **Shape**: Change shape → **Ampere** → **VM.Standard.A1.Flex**
   - OCPU **2**, 메모리 **12 GB** 로 설정해요. (무료 한도는 합쳐서 4 OCPU, 24 GB)
4. **Networking**: 기본값 그대로 두고, **Assign a public IPv4 address** 가 켜져 있는지 확인해요.
5. **Add SSH keys**: **Generate a key pair for me** → **Save private key** 를 눌러 키 파일(`.key`)을 꼭 내려받아요. 잃어버리면 접속할 수 없어요.
6. **Create** 를 누르고, 상태가 초록색 **Running** 이 되면 **Public IP address** 를 메모해요.

**"Out of capacity" 오류가 나면**: 무료 ARM 서버 재고가 없다는 뜻이에요. Placement에서 다른 Availability Domain을 고르거나, 몇 시간 뒤(새벽이 잘 된다는 말이 많아요) 다시 시도해요.

## 3. 서버 접속

내려받은 키 파일 위치에서 터미널(맥) 또는 PowerShell(윈도우)을 열어요.

```bash
# 맥/리눅스만: 키 파일 권한 설정
chmod 400 ssh-key-*.key

ssh -i ssh-key-*.key ubuntu@<Public IP>
```

처음 접속할 때 `yes` 를 입력하면 돼요. 윈도우에서 권한 오류가 나면 알려주세요.

## 4. Docker 설치

서버에 접속한 상태에서:

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
exit
```

`exit` 로 나간 뒤 3번처럼 **다시 접속**해요. 그다음 확인:

```bash
docker run --rm hello-world
```

`Hello from Docker!` 가 보이면 성공이에요.

## 5. 코드 받기와 실행

```bash
git clone https://github.com/pulddang/news_scraping.git
cd news_scraping
cp .env.example .env
nano .env
```

`nano` 화면에서 `POSTGRES_PASSWORD=change-me` 를 아무 긴 비밀번호로 바꾸고, `Ctrl+O` → `Enter` → `Ctrl+X` 로 저장해요.

> 저장소가 비공개라서 `git clone` 이 아이디/비밀번호를 물으면: GitHub → Settings → Developer settings → Personal access tokens → **Fine-grained tokens** 에서 news_scraping 저장소의 **Contents: Read-only** 권한 토큰을 만들고, 아이디는 `pulddang`, 비밀번호 자리에 토큰을 붙여넣어요.

이제 실행해요. 처음엔 이미지를 만드느라 몇 분 걸려요.

```bash
docker compose up -d --build
```

## 6. 피드 확인

```bash
docker compose run --rm collector python -m app.cli check-sources
```

각 언론사마다 `OK`, `EMPTY`, `FAIL` 중 하나가 나와요. **이 결과 전체를 복사해서 Claude에게 보내주세요.** 안 되는 피드 주소를 고쳐 드릴게요.

15분쯤 뒤에 실제로 기사가 쌓였는지도 볼 수 있어요.

```bash
docker compose logs --tail 20 collector
docker compose exec db psql -U news -c "select s.name, count(*) from articles a join sources s on s.id=a.source_id group by 1 order by 2 desc;"
```

## 나중에 코드가 바뀌면

```bash
cd ~/news_scraping
git pull
docker compose up -d --build
```

지금 단계에서는 외부에 여는 포트가 없어요. 3단계(화면)를 올릴 때 웹 접속용 포트를 여는 방법을 따로 안내할게요.
