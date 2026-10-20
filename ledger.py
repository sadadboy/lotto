"""구매/충전 기록과 자동 실행 제어 상태 (data/ledger.json).

봇(main.py)과 대시보드(dashboard/app.py)는 서로 다른 프로세스라 같은 파일을 함께 쓴다.
그래서 모든 읽기-수정-쓰기는 파일 잠금 안에서 하고, 쓰기는 임시 파일 + os.replace로 원자적으로 한다.

status.json(런타임 전용, 컨테이너를 다시 만들면 사라짐)과 달리 이 파일은 data/ 볼륨에 있어
배포 후에도 남는다. 지출 한도는 과거 기록이 사라지면 의미가 없기 때문이다.

purchases/deposits의 status:
  ok         — 실제로 돈이 나감
  uncertain  — 돈이 나갔을 수 있음 (구매 버튼 클릭 후 오류, 충전 결과 불명). 한도 계산에는 포함한다.
  failed / blocked / paused / skipped — 돈이 나가지 않음. 감시(watchdog)가 "작업이 돌았는지"를 판단하는 데만 쓴다.
"""
import json
import os
from contextlib import contextmanager
from datetime import datetime, timedelta

try:
    import fcntl
except ImportError:  # Windows — 잠금 없이 동작 (로컬 개발용)
    fcntl = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
LEDGER_PATH = os.path.join(DATA_DIR, 'ledger.json')
LOCK_PATH = os.path.join(DATA_DIR, 'ledger.lock')

SPENT_STATUSES = ('ok', 'uncertain')
KEEP_DAYS = 400

# 지출 한도 기본값 (config.json의 limits로 덮어씀, 0이면 무제한)
# 1회 구매는 최대 5게임(5,000원)이고 한 달에 토요일은 많아야 5번이다.
DEFAULT_LIMITS = {
    "weekly_buy": 5000,
    "monthly_buy": 25000,
    "weekly_deposit": 50000,
    "monthly_deposit": 100000,
}


def _empty():
    return {
        "purchases": [],
        "deposits": [],
        "paused": False,
        "skip_next_buy": False,
        "watchdog": {},
    }


@contextmanager
def _locked():
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(LOCK_PATH, 'a') as lock:
        if fcntl:
            fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl:
                fcntl.flock(lock, fcntl.LOCK_UN)


def _read():
    data = _empty()
    try:
        with open(LEDGER_PATH, 'r', encoding='utf-8') as f:
            data.update(json.load(f))
    except FileNotFoundError:
        pass
    return data


def _write(data):
    cutoff = (datetime.now() - timedelta(days=KEEP_DAYS)).isoformat(timespec='seconds')
    for key in ('purchases', 'deposits'):
        data[key] = [r for r in data[key] if r.get('at', '') >= cutoff]
    tmp = LEDGER_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, LEDGER_PATH)


def load():
    with _locked():
        return _read()


@contextmanager
def edit():
    """with ledger.edit() as data: data[...] = ... — 블록이 끝나면 저장된다."""
    with _locked():
        data = _read()
        yield data
        _write(data)


def _now():
    return datetime.now().isoformat(timespec='seconds')


# ── 기록 ────────────────────────────────────────────────────────────────

def record_purchase(status, games=0, amount=0, note=""):
    with edit() as data:
        data['purchases'].append({"at": _now(), "status": status, "games": games, "amount": amount, "note": note})


def record_deposit(status, amount=0, note=""):
    with edit() as data:
        data['deposits'].append({"at": _now(), "status": status, "amount": amount, "note": note})


# ── 기간 / 한도 ─────────────────────────────────────────────────────────

def week_start(now=None):
    """로또 판매 주간의 시작 (일요일 00:00). 추첨이 토요일이라 일~토를 한 주로 본다."""
    now = now or datetime.now()
    days_since_sunday = (now.weekday() + 1) % 7
    return (now - timedelta(days=days_since_sunday)).replace(hour=0, minute=0, second=0, microsecond=0)


def month_start(now=None):
    now = now or datetime.now()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def spent(kind, since, data=None):
    """kind: 'purchases' | 'deposits'. since 이후 실제로 나갔(을 수 있)는 금액 합계."""
    data = data or load()
    since_s = since.isoformat(timespec='seconds')
    return sum(int(r.get('amount') or 0) for r in data[kind]
               if r.get('at', '') >= since_s and r.get('status') in SPENT_STATUSES)


def get_limits(config):
    limits = dict(DEFAULT_LIMITS)
    for k, v in ((config or {}).get('limits') or {}).items():
        try:
            limits[k] = int(v)
        except (TypeError, ValueError):
            pass
    return limits


def usage(config, now=None):
    """한도별 (사용액, 한도) — 상태 표시용."""
    data = load()
    limits = get_limits(config)
    ws, ms = week_start(now), month_start(now)
    return {
        "weekly_buy": (spent('purchases', ws, data), limits['weekly_buy']),
        "monthly_buy": (spent('purchases', ms, data), limits['monthly_buy']),
        "weekly_deposit": (spent('deposits', ws, data), limits['weekly_deposit']),
        "monthly_deposit": (spent('deposits', ms, data), limits['monthly_deposit']),
    }


LIMIT_LABELS = {
    "weekly_buy": "이번 주 구매",
    "monthly_buy": "이번 달 구매",
    "weekly_deposit": "이번 주 충전",
    "monthly_deposit": "이번 달 충전",
}


def check_limit(kind, amount, config, now=None):
    """amount를 더 쓰면 한도를 넘는지 확인한다. 반환: (허용 여부, 사유)

    kind: 'buy' | 'deposit'
    """
    u = usage(config, now)
    for key in (f"weekly_{kind}", f"monthly_{kind}"):
        used, limit = u[key]
        if limit and used + amount > limit:
            return False, (f"{LIMIT_LABELS[key]} 한도 초과 — 사용 {used:,}원 + 이번 {amount:,}원 "
                           f"> 한도 {limit:,}원")
    return True, ""


# ── 자동 실행 제어 ──────────────────────────────────────────────────────

def set_paused(paused):
    with edit() as data:
        data['paused'] = bool(paused)


def set_skip_next_buy(skip):
    with edit() as data:
        data['skip_next_buy'] = bool(skip)


def consume_skip_next_buy():
    """건너뛰기가 예약돼 있으면 해제하고 True를 반환 (한 번만 적용)."""
    with edit() as data:
        if data.get('skip_next_buy'):
            data['skip_next_buy'] = False
            return True
        return False
