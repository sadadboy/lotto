"""디스코드 채널 명령 (!도움말, !상태, !일시정지 ...)

웹훅은 보내기만 가능해서 명령을 받으려면 디스코드 봇 토큰이 필요하다.
discord.py 대신 REST API를 몇 초마다 폴링한다. 이 호스트는 docker build 중 DNS가 없어
새 패키지를 이미지에 넣을 수 없고, 명령 몇 개에는 게이트웨이 연결이 필요 없다.

설정 (config.json → system, 대시보드 '시스템 설정'에서 입력):
  discord_bot_token      봇 토큰 (secret.key로 암호화 저장)
  discord_channel_id     명령을 받을 채널 ID
  discord_allowed_users  명령을 쓸 수 있는 사용자 ID 목록 (비우면 채널의 누구나)
디스코드 개발자 포털에서 봇의 'Message Content Intent'를 켜야 명령 내용을 읽을 수 있다.

봇 프로세스(main.py) 안의 별도 스레드에서 돈다. 명령은 상태 조회와 일시정지/건너뛰기만 한다.
동행복권 로그인이 필요한 명령은 일부러 두지 않았다 — 예약 작업과 동시에 로그인하면 세션이 서로 끊긴다.
"""
import json
import os
import threading
import time
from datetime import datetime

import requests
from loguru import logger

import ledger
from bot_watchdog import next_slot, fmt_slot

API = "https://discord.com/api/v10"
POLL_INTERVAL_SEC = 3
CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.json')

HELP_TEXT = """🎱 **로또 봇 명령어**
**조회**
`!상태` — 봇 상태, 예치금, 일시정지 여부, 다음 일정, 이번 주 지출을 한 번에
`!잔액` — 마지막으로 확인한 예치금
`!일정` — 다음 구매·충전·당첨확인 시각
`!이번주` — 이번 주 구매 기록과 최근 당첨 결과
`!기록` — 최근 구매·충전 기록 10건
`!한도` — 지출 한도와 이번 주/달 사용액

**제어**
`!일시정지` — 자동 구매·충전을 멈춤 (당첨확인은 계속)
`!재개` — 일시정지 해제
`!건너뛰기` — 다음 예약 구매 한 번만 건너뜀
`!건너뛰기취소` — 건너뛰기 예약 취소

`!도움말` — 이 안내
※ 실제 구매·충전은 예약 시각에만 실행됩니다. 한도·스케줄 변경은 대시보드에서 하세요."""

STATUS_KO = {"ok": "✅ 완료", "uncertain": "⚠️ 확인 필요", "failed": "❌ 실패",
             "blocked": "🛑 한도 차단", "paused": "⏸️ 일시정지", "skipped": "⏭️ 건너뜀"}


def _load_config():
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _status():
    from status_manager import status_manager
    return status_manager.load_status()


def _won(n):
    return f"{int(n):,}원"


# ── 명령 처리 ────────────────────────────────────────────────────────────

def _schedule_lines(config):
    s = config.get('schedule') or {}
    return [
        f"🛒 구매: {fmt_slot(next_slot(s.get('buy_day', 'Saturday'), s.get('buy_time', '10:00')))}",
        f"💰 충전: {fmt_slot(next_slot(s.get('deposit_day', 'Friday'), s.get('deposit_time', '18:00')))}",
        f"🏆 당첨확인: {fmt_slot(next_slot(s.get('check_day', 'Saturday'), s.get('check_time', '23:00')))}",
    ]


def _balance_line():
    st = _status()
    at = st.get('balance_updated_at')
    return f"💰 예치금: {_won(st.get('balance', 0))}" + (f" ({at} 기준)" if at else "")


def _usage_lines(config):
    lines = []
    for key, (used, limit) in ledger.usage(config).items():
        lines.append(f"{ledger.LIMIT_LABELS[key]}: {_won(used)} / " + (_won(limit) if limit else "무제한"))
    return lines


def _control_line():
    data = ledger.load()
    parts = ["⏸️ **일시정지 중**" if data.get('paused') else "▶️ 자동 실행 중"]
    if data.get('skip_next_buy'):
        parts.append("⏭️ 다음 구매 건너뛰기 예약됨")
    return " / ".join(parts)


def cmd_status(config):
    st = _status()
    return "\n".join([
        "📊 **로또 봇 상태**",
        _control_line(),
        _balance_line(),
        f"🕒 마지막 작업: {st.get('last_run', 'N/A')}",
        f"🎰 최근 결과: {st.get('latest_result', '미확인')}",
        "",
        "**다음 일정**", *_schedule_lines(config),
        "",
        "**지출**", *_usage_lines(config),
    ])


def _record_line(kind, r):
    at = r.get('at', '').replace('T', ' ')[:16]
    what = "구매" if kind == 'purchases' else "충전"
    detail = []
    if r.get('games'):
        detail.append(f"{r['games']}게임")
    if r.get('amount'):
        detail.append(_won(r['amount']))
    if r.get('note'):
        detail.append(r['note'])
    return f"{at} {what} {STATUS_KO.get(r.get('status'), r.get('status'))}" + (f" — {', '.join(detail)}" if detail else "")


def cmd_this_week(config):
    since = ledger.week_start().isoformat(timespec='seconds')
    data = ledger.load()
    rows = [_record_line('purchases', r) for r in data['purchases'] if r.get('at', '') >= since]
    return "\n".join([
        "🗓️ **이번 주 (일~토)**",
        *(rows or ["아직 구매 기록이 없습니다."]),
        f"🎰 최근 결과: {_status().get('latest_result', '미확인')}",
    ])


def cmd_history(config):
    data = ledger.load()
    rows = [('purchases', r) for r in data['purchases']] + [('deposits', r) for r in data['deposits']]
    rows.sort(key=lambda x: x[1].get('at', ''), reverse=True)
    if not rows:
        return "기록이 없습니다."
    return "📜 **최근 기록**\n" + "\n".join(_record_line(k, r) for k, r in rows[:10])


def cmd_pause(config):
    ledger.set_paused(True)
    return "⏸️ 자동 구매·충전을 일시정지했습니다. 당첨확인은 계속합니다. 다시 켜려면 `!재개`"


def cmd_resume(config):
    ledger.set_paused(False)
    s = config.get('schedule') or {}
    return f"▶️ 자동 실행을 재개했습니다. 다음 구매: {fmt_slot(next_slot(s.get('buy_day'), s.get('buy_time')))}"


def cmd_skip(config):
    ledger.set_skip_next_buy(True)
    s = config.get('schedule') or {}
    return (f"⏭️ 다음 예약 구매({fmt_slot(next_slot(s.get('buy_day'), s.get('buy_time')))}) 한 번만 건너뜁니다. "
            "취소하려면 `!건너뛰기취소`")


def cmd_unskip(config):
    ledger.set_skip_next_buy(False)
    return "↩️ 건너뛰기 예약을 취소했습니다. 다음 예약 구매는 정상 진행됩니다."


COMMANDS = {
    "도움말": lambda c: HELP_TEXT, "help": lambda c: HELP_TEXT, "명령어": lambda c: HELP_TEXT,
    "상태": cmd_status, "status": cmd_status,
    "잔액": lambda c: _balance_line(), "예치금": lambda c: _balance_line(),
    "일정": lambda c: "📅 **다음 일정**\n" + "\n".join(_schedule_lines(c)),
    "이번주": cmd_this_week,
    "기록": cmd_history,
    "한도": lambda c: "💳 **지출 한도**\n" + "\n".join(_usage_lines(c)) + "\n한도 변경은 대시보드에서 합니다.",
    "일시정지": cmd_pause, "정지": cmd_pause, "pause": cmd_pause,
    "재개": cmd_resume, "resume": cmd_resume,
    "건너뛰기": cmd_skip, "skip": cmd_skip,
    "건너뛰기취소": cmd_unskip, "unskip": cmd_unskip,
}


def handle(content, config):
    """'!명령' 문자열을 처리해 답장 내용을 돌려준다. 명령이 아니면 None."""
    if not content.startswith('!'):
        return None
    name = content[1:].strip().replace(' ', '').lower()
    if not name:
        return None
    fn = COMMANDS.get(name)
    if fn is None:
        return f"❓ 모르는 명령입니다: `{content[:30]}` — `!도움말`로 사용 가능한 명령을 확인하세요."
    return fn(config)


# ── 디스코드 폴링 ────────────────────────────────────────────────────────

class _Stop(Exception):
    pass


def _request(method, path, token, **kwargs):
    while True:
        r = requests.request(method, API + path, timeout=15,
                             headers={"Authorization": f"Bot {token}",
                                      "User-Agent": "DiscordBot (lotto-bot, 1.0)"}, **kwargs)
        if r.status_code == 429:
            time.sleep(float(r.json().get('retry_after', 5)))
            continue
        if r.status_code in (401, 403, 404):
            raise _Stop(f"{r.status_code} {r.text[:200]}")
        r.raise_for_status()
        return r.json() if r.content else None


def _credentials(config):
    system = config.get('system') or {}
    token_enc = system.get('discord_bot_token', '')
    channel = str(system.get('discord_channel_id', '') or '').strip()
    if not token_enc or not channel:
        return None, None, []
    from security import SecurityManager
    token = SecurityManager().decrypt(token_enc)
    allowed = [str(u).strip() for u in (system.get('discord_allowed_users') or []) if str(u).strip()]
    return token, channel, allowed


def _run():
    last_id = None
    active = None  # (token, channel) — 설정이 바뀌면 다시 시작
    warned_intent = False
    while True:
        try:
            config = _load_config()
            token, channel, allowed = _credentials(config)
            if not token:
                active = None
                time.sleep(30)
                continue
            if active != (token, channel):
                latest = _request("GET", f"/channels/{channel}/messages?limit=1", token)
                last_id = latest[0]['id'] if latest else '0'  # 시작 전 메시지는 처리하지 않는다
                active = (token, channel)
                logger.info(f"디스코드 명령 수신 시작 (채널 {channel})")

            msgs = _request("GET", f"/channels/{channel}/messages?after={last_id}&limit=50", token) or []
            for m in sorted(msgs, key=lambda m: int(m['id'])):
                last_id = m['id']
                author = m.get('author') or {}
                if author.get('bot'):
                    continue
                content = (m.get('content') or '').strip()
                if not content and not m.get('attachments') and not warned_intent:
                    warned_intent = True
                    logger.warning("디스코드 메시지 내용이 비어 있습니다 — 개발자 포털에서 봇의 "
                                   "'Message Content Intent'를 켜야 명령을 읽을 수 있습니다.")
                reply = handle(content, config)
                if reply is None:
                    continue
                if allowed and str(author.get('id')) not in allowed:
                    reply = "🔒 이 명령을 사용할 권한이 없습니다."
                logger.info(f"디스코드 명령: {content[:30]} (by {author.get('username')})")
                _request("POST", f"/channels/{channel}/messages", token, json={
                    "content": reply[:1990],
                    "message_reference": {"message_id": m['id']},
                    "allowed_mentions": {"parse": []},
                })
            time.sleep(POLL_INTERVAL_SEC)
        except _Stop as e:
            # 토큰이 틀렸거나 채널 권한이 없다. 설정이 바뀔 때까지 기다린다 (매번 실패 로그를 찍지 않도록 길게).
            logger.error(f"디스코드 명령 기능 중지 — 봇 토큰/채널 ID/권한을 확인하세요: {e}")
            active = None
            time.sleep(300)
        except Exception as e:
            logger.warning(f"디스코드 명령 확인 중 오류(재시도): {e}")
            time.sleep(15)


def start_in_background():
    t = threading.Thread(target=_run, name="discord-commands", daemon=True)
    t.start()
    return t
