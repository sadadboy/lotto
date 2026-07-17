# 로또 자동 구매 봇 (동행복권)

Playwright 기반 동행복권 로또 6/45 자동 구매 봇입니다. 로그인 · 자동 구매 · 당첨 확인 ·
예치금 조회 · Discord 알림 · 웹 대시보드(포트 5000)를 제공하며 Docker로 배포합니다.

> ⚠️ **보안 원칙:** `config.json`, `secret.key`, `.env` 는 계정 정보/암호화 키가 들어있어
> **절대 git에 커밋하지 않습니다** (`.gitignore` 처리됨). 서버에는 로컬 PC에서 `scp`로 직접 전달합니다.

---

## 1. 준비물

### 코드
- GitHub: `https://github.com/sadadboy/lotto` (master 브랜치)

### 비밀 파일 2개 (git에 없음 — 로컬 PC에서 준비/보관)
| 파일 | 내용 |
|------|------|
| `config.json` | 계정/게임/스케줄/Discord 웹훅 설정. `user_pw`·`pay_pw`는 `secret.key`로 암호화되어 저장 |
| `secret.key` | 위 암호문을 복호화하는 Fernet 키. **이 파일이 없으면 로그인 불가** |

> `config.json` 최초 생성은 `python setup_auth.py`(암호화 저장) 또는 `config.example.json`을 참고하세요.
> `config.json`과 `secret.key`는 **같은 키 쌍**이어야 복호화됩니다 (한 PC에서 만들어 함께 옮기세요).

---

## 2. 최초 배포 (Oracle Cloud / Ubuntu + Docker)

### 2-1. Docker 설치 (최초 1회)
```bash
bash setup_docker.sh      # Docker + Compose 설치 후 재로그인
```

### 2-2. 코드 받기 — 두 가지 경우

**A. 완전히 새로 받는 경우**
```bash
git clone https://github.com/sadadboy/lotto.git ~/lotto
cd ~/lotto
```

**B. 기존에 파일로 배포돼 있던 디렉토리를 git으로 전환하는 경우** (예: 기존 `~/lotto`)
```bash
cd ~/lotto
# (안전을 위해 비밀 파일 백업)
mkdir -p ~/lotto-backup && cp -f config.json secret.key ~/lotto-backup/ 2>/dev/null || true

git init
git remote add origin https://github.com/sadadboy/lotto.git
git fetch origin
git reset --hard origin/master
```
> `secret.key` / `config.json` / `status.json` 은 `.gitignore` 처리되어 **git이 건드리지 않습니다**
> (코드만 최신으로 교체되고 비밀·상태 파일은 그대로 보존 — 검증됨).

### 2-3. 비밀 파일 업로드 (로컬 PC → 서버)
로컬 PC(맥/윈도우)의 프로젝트 폴더에서:
```bash
scp config.json secret.key ubuntu@<서버IP>:~/lotto/
```
서버에서 존재 확인:
```bash
cd ~/lotto && ls -la config.json secret.key   # 두 개 모두 "파일"로 보여야 함
```

### 2-4. 빌드 & 실행
```bash
docker compose up -d --build
docker compose logs -f            # 로그 확인 (Ctrl+C로 빠져나오기)
```

### 2-5. 실행 확인
- 브라우저에서 **`http://<서버IP>:5000`** 접속 (Oracle 보안목록에서 5000 포트 허용 필요)
- **봇은 컨테이너가 뜨면 자동으로 시작됩니다** (`AUTOSTART=true`). 재부팅/리빌드 후에도 스케줄이 자동 실행돼요.
  - 자동 시작을 끄려면 `docker-compose.yml` 환경변수에서 `AUTOSTART=false`
  - 대시보드의 Start/Stop 버튼으로 수동 제어도 가능
- 시작 시 자동 로그인하여 현재 예치금이 대시보드에 표시됨

---

## 자동 실행 & 스케줄 변경

- **스케줄**(기본): 매주 **토요일 구매 11:44 / 당첨확인 22:40**. (충전은 `deposit_job`이 현재 비활성이라 자동 실행 안 함)
- **스케줄 시간 변경 시 봇 재시작 불필요** — `config.json`의 `schedule` 값을 바꾸면(대시보드 설정 저장 또는 파일 편집) 봇이 **5초 내에 감지하여 새 시간으로 자동 재등록**합니다.
- 계정/게임 설정 변경도 다음 작업 실행 때 자동 반영됩니다 (작업이 매번 config를 다시 읽음).

---

## 3. 업데이트 (코드 개선분 받기)

git 저장소로 세팅돼 있으면 한 줄로 받습니다.
```bash
cd ~/lotto
git pull origin master           # 코드만 갱신 (비밀·상태 파일은 보존됨)
docker compose up -d --build     # 재빌드 & 재시작
```
> 혹시 `git pull`이 로컬 변경 충돌로 막히면:
> ```bash
> git fetch origin && git reset --hard origin/master
> ```
> (비밀/상태 파일은 gitignore라 그대로 유지됩니다.)

---

## 4. 예치금(잔액) 표시

대시보드의 예치금은 `status.json`에 저장된 값을 보여줍니다. 값은 봇이 **로그인할 때** 갱신됩니다.
- **봇 Start** 시 자동 1회 갱신됨
- 봇을 켜지 않고 즉시 갱신만 하려면:
  ```bash
  docker compose exec lotto-bot python scripts/update_balance.py
  ```
> 참고: 동행복권 메인 헤더의 예치금 값은 실제 잔액과 다르게 표시될 수 있어, 봇은
> 구매 게임 페이지의 실제 보유예치금(`#moneyBalance`)을 조회합니다.

---

## 5. 보안 체크리스트

- [ ] `config.json`, `secret.key`, `.env` 는 **절대 git에 커밋하지 않는다** (`.gitignore` 확인)
- [ ] 새 서버로 옮길 때는 `scp` 로 직접 전달한다
- [ ] `secret.key`가 유출되면 새로 발급 후 자격증명을 재암호화한다
- [ ] 결제/충전 비밀번호(`pay_pw`)는 주기적으로 변경한다

---

## 6. 주요 파일

| 파일 | 역할 |
|------|------|
| `main.py` | 스케줄러 (시작 시 잔액 1회 갱신 → 예약 시각에 구매/당첨확인) |
| `auth.py` | 로그인 (데스크탑 모드 강제, 로그인 후 잔액 갱신) |
| `buy_lotto.py` | 자동 구매 (모바일 리다이렉트 방어 가드 포함) |
| `lotto.py` | 예치금 조회 (`get_reliable_balance` = 게임 프레임 `#moneyBalance`) |
| `history.py` | 당첨/영수증 확인 (티켓 팝업 캡처 + 회차/발행일 파싱) |
| `deposit.py` | 예치금 충전 (간편충전 + OCR 결제) |
| `dashboard/app.py` | 웹 대시보드 (봇 start/stop, 상태 표시) — 컨테이너 진입점 |
| `scripts/update_balance.py` | 잔액 수동 갱신 스크립트 |

---

_※ 실행 환경: Docker(`mcr.microsoft.com/playwright/python`) · `HEADLESS=true` · `TZ=Asia/Seoul`_
