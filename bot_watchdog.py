"""봇 감시 — 대시보드 프로세스에서 1분마다 돈다.

지금까지의 사고는 대부분 '조용한 실패'였다. (2026-09-11 SIGSEGV로 스케줄러가 통째로 죽음,
2026-10-16 구매 누락) 봇 스스로는 자기가 죽은 걸 알릴 수 없으므로, 봇과 별개 프로세스인
대시보드가 다음을 확인한다.

1. 봇 프로세스 사망 — 사용자가 멈춘 게 아닌데(bot.pid가 남아 있음) 프로세스가 없으면
   종료 원인과 함께 알리고 자동 재시작한다. (6시간에 3번까지, 넘으면 재시작을 멈추고 알림)
2. 스케줄러 멈춤 — 프로세스는 살아 있는데 하트비트가 오래 멈춰 있으면 알린다.
3. 구매 누락 — 예약 구매 시각이 지났는데 그 이후 구매 작업 기록(ledger)이 하나도 없으면 알린다.
   구매가 실패/차단/건너뜀으로 끝난 경우는 구매 작업이 이미 알렸으므로 여기서는 알리지 않는다.
"""
import json
import os
import threading
import time
from datetime import datetime, timedelta

import ledger
from notification import send_discord_message

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, 'config.json')

CHECK_INTERVAL_SEC = 60
# 구매 작업은 재시도(2분 간격 4회)와 AI 번호 생성까지 길면 30분가량 걸린다.
BUY_GRACE = timedelta(minutes=90)
# 작업 실행 중에는 스케줄러 루프(하트비트)가 멈추므로 작업 시간보다 넉넉하게 잡는다.
HANG_THRESHOLD = timedelta(minutes=120)
RESTART_WINDOW = timedelta(hours=6)
MAX_RESTARTS = 3

TAG = "감시"

DAY_INDEX = {d: i for i, d in enumerate(
    ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"])}
DAY_KO = ["월", "화", "수", "목", "금", "토", "일"]


SCHEDULE_FIELDS = (
    # (이름, 요일 키, 시간 키, 기본 요일, 기본 시간)
    ("구매", "buy_day", "buy_time", "Saturday", "10:00"),
    ("충전", "deposit_day", "deposit_time", "Friday", "18:00"),
    ("당첨확인", "check_day", "check_time", "Saturday", "23:00"),
)


def _valid_hhmm(hhmm):
    try:
        h, m = (hhmm or '').split(':')
        return len(h) == 2 and len(m) == 2 and 0 <= int(h) <= 23 and 0 <= int(m) <= 59
    except ValueError:
        return False


def schedule_errors(sched):
    """스케줄 설정 오류 목록 (없으면 빈 리스트). 대시보드 저장과 봇 핫리로드가 함께 쓴다."""
    errors = []
    for label, day_key, time_key, default_day, default_time in SCHEDULE_FIELDS:
        day = (sched or {}).get(day_key, default_day)
        hhmm = (sched or {}).get(time_key, default_time)
        if (day or '').lower() not in DAY_INDEX:
            errors.append(f"{label} 요일이 올바르지 않습니다: {day!r}")
        if not _valid_hhmm(hhmm):
            errors.append(f"{label} 시간이 올바르지 않습니다 (HH:MM): {hhmm!r}")
    return errors


def last_slot(day, hhmm, now=None):
    """매주 day hh:mm 예약의 가장 최근 실행 시각 (now 이전). 설정이 잘못됐으면 None."""
    now = now or datetime.now()
    try:
        d = DAY_INDEX[(day or '').lower()]
        h, m = map(int, (hhmm or '').split(':'))
    except (KeyError, ValueError):
        return None
    slot = (now - timedelta(days=(now.weekday() - d) % 7)).replace(hour=h, minute=m, second=0, microsecond=0)
    if slot > now:
        slot -= timedelta(days=7)
    return slot


def next_slot(day, hhmm, now=None):
    slot = last_slot(day, hhmm, now)
    return slot + timedelta(days=7) if slot else None


def fmt_slot(dt):
    return f"{dt.month}/{dt.day}({DAY_KO[dt.weekday()]}) {dt:%H:%M}" if dt else "설정 오류"


def _load_config():
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _read_status():
    try:
        from status_manager import status_manager
        return status_manager.load_status()
    except Exception:
        return {}


def _reap(pid):
    """죽은 봇(대시보드의 자식)을 거두고 종료 원인을 문자열로 돌려준다."""
    try:
        got, status = os.waitpid(pid, os.WNOHANG)
    except (ChildProcessError, OSError):
        return "종료 원인 알 수 없음"
    if got == 0:
        return "종료 원인 알 수 없음"
    if os.WIFSIGNALED(status):
        sig = os.WTERMSIG(status)
        hint = " (SIGSEGV — 네이티브 라이브러리 충돌)" if sig == 11 else " (SIGKILL — 메모리 부족 가능)" if sig == 9 else ""
        return f"시그널 {sig}로 종료{hint}"
    return f"종료 코드 {os.WEXITSTATUS(status)}"


def _tail_log(log_path, n=5):
    try:
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            return "".join(f.readlines()[-n:]).strip()[-800:]
    except Exception:
        return ""


def tick(bot_manager, log, log_path, now=None):
    now = now or datetime.now()
    config = _load_config()
    state = ledger.load().get('watchdog', {})
    updates = {}

    # 처음 돌 때와 스케줄을 바꿨을 때는 그 이전 예약을 따지지 않는다.
    # (안 그러면 배포 직후나 요일 변경 직후 '지난 예약을 놓쳤다'고 잘못 알린다.)
    sched = config.get('schedule') or {}
    sched_key = f"{sched.get('buy_day')} {sched.get('buy_time')}"
    if 'since' not in state or state.get('sched_key') != sched_key:
        updates['since'] = now.isoformat(timespec='seconds')
        updates['sched_key'] = sched_key
        state.update(updates)

    # ── 1. 봇 프로세스 사망 ──
    pid_file = bot_manager.pid_file
    if os.path.exists(pid_file) and not bot_manager.is_running():
        try:
            with open(pid_file) as f:
                pid = int(f.read().strip())
            cause = _reap(pid)
        except (ValueError, OSError):
            cause = "종료 원인 알 수 없음"
        tail = _tail_log(log_path)

        cutoff = (now - RESTART_WINDOW).isoformat(timespec='seconds')
        restarts = [t for t in state.get('restarts', []) if t >= cutoff]
        if len(restarts) < MAX_RESTARTS:
            ok, msg = bot_manager.start()
            restarts.append(now.isoformat(timespec='seconds'))
            log(f"🚨 [감시] 봇 사망 감지({cause}) → 자동 재시작: {msg}")
            send_discord_message(
                f"🚨 봇 프로세스가 죽어 있어 자동으로 다시 시작했습니다. ({cause})\n"
                f"재시작 결과: {msg} (최근 6시간 {len(restarts)}/{MAX_RESTARTS}회)\n"
                + (f"마지막 로그:\n```\n{tail}\n```" if tail else ""),
                tag=TAG,
            )
        else:
            # 계속 죽는다면 재시작으로 해결될 문제가 아니다. 사용자가 멈춘 상태로 돌려 반복 알림을 막는다.
            try:
                os.remove(pid_file)
            except OSError:
                pass
            log(f"🚨 [감시] 봇이 6시간 내 {MAX_RESTARTS}회 넘게 죽어 자동 재시작을 멈춤 ({cause})")
            send_discord_message(
                f"🚨 봇이 최근 6시간 동안 {MAX_RESTARTS}번 넘게 죽어 자동 재시작을 멈췄습니다. ({cause})\n"
                "원인을 확인한 뒤 대시보드에서 Start를 눌러 주세요. **그 전까지 구매·충전이 실행되지 않습니다.**\n"
                + (f"마지막 로그:\n```\n{tail}\n```" if tail else ""),
                tag=TAG,
            )
        updates['restarts'] = restarts

    # ── 2. 스케줄러 멈춤 ──
    elif bot_manager.is_running():
        hb = _read_status().get('heartbeat')
        try:
            hb_dt = datetime.strptime(hb, "%Y-%m-%d %H:%M:%S") if hb else None
        except ValueError:
            hb_dt = None
        if hb_dt and now - hb_dt > HANG_THRESHOLD and state.get('hang_alerted') != hb:
            minutes = int((now - hb_dt).total_seconds() // 60)
            log(f"⚠️ [감시] 스케줄러 하트비트 {minutes}분째 멈춤 (마지막 {hb})")
            send_discord_message(
                f"⚠️ 봇 프로세스는 살아 있지만 스케줄러가 {minutes}분째 응답이 없습니다. (마지막 하트비트 {hb})\n"
                "작업이 어딘가에서 멈췄을 수 있습니다. 대시보드에서 Stop → Start로 재시작해 주세요.\n"
                f"마지막 로그:\n```\n{_tail_log(log_path)}\n```",
                tag=TAG,
            )
            updates['hang_alerted'] = hb

    # ── 3. 구매 누락 ──
    slot = last_slot(sched.get('buy_day', 'Saturday'), sched.get('buy_time', '10:00'), now)
    since = datetime.fromisoformat(state['since'])
    slot_key = slot.isoformat(timespec='seconds') if slot else None
    if slot and slot >= since and now >= slot + BUY_GRACE and state.get('buy_alerted') != slot_key:
        # 예약 직전에 수동으로 돌린 경우도 인정하도록 약간 앞까지 본다.
        from_s = (slot - timedelta(minutes=5)).isoformat(timespec='seconds')
        ran = any(r.get('at', '') >= from_s for r in ledger.load()['purchases'])
        if not ran:
            bot_state = "실행 중" if bot_manager.is_running() else "중지됨"
            log(f"🚨 [감시] {fmt_slot(slot)} 예약 구매 기록 없음 (봇 {bot_state})")
            send_discord_message(
                f"🚨 {fmt_slot(slot)} 예약 구매가 실행되지 않았습니다. (봇 상태: {bot_state})\n"
                "구매 작업이 시작조차 되지 않은 것으로 보입니다. 이번 주는 직접 구매해 주세요.",
                tag=TAG,
            )
        updates['buy_alerted'] = slot_key

    if updates:
        with ledger.edit() as data:
            data.setdefault('watchdog', {}).update(updates)


def start_in_background(bot_manager, log, log_path):
    def loop():
        log("👀 [감시] 봇 감시 시작")
        while True:
            time.sleep(CHECK_INTERVAL_SEC)
            try:
                tick(bot_manager, log, log_path)
            except Exception as e:
                log(f"⚠️ [감시] 확인 중 오류: {e}")

    t = threading.Thread(target=loop, name="watchdog", daemon=True)
    t.start()
    return t
