"""동행복권 구매내역 JSON API (2026 리뉴얼).

구매내역 페이지(/mypage/mylotteryledger)가 내부적으로 쓰는 API를 로그인된 페이지 안에서
fetch로 호출한다. 화면을 긁는 history.py보다 구조 변경에 강하고, 게임별 실제 번호
(사이트 자동선택 번호 포함)와 등수·당첨금·수령기한까지 준다.

    GET /mypage/selectMyLotteryledger.do?srchStrDt=YYYYMMDD&srchEndDt=YYYYMMDD&ltGdsCd=LO40
        &pageNum=1&recordCountPerPage=N     → data.list[] (조회 기간은 최대 3개월)
    GET /mypage/lotto645TicketDetail.do?ntslOrdrNo=...&barcd=...
        → data.ticket.game_dtl[] = {idx, type(1 수동/2 반자동/3 자동), num[6], rank, amt}
"""
import json
import time
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from loguru import logger

import tickets

LEDGER_PAGE = "https://www.dhlottery.co.kr/mypage/mylotteryledger"
MAX_RANGE_DAYS = 89      # 사이트 제한: 최대 3개월
PAGE_SIZE = 100
HISTORY_DAYS = 730       # 첫 동기화 때 거슬러 올라가는 기간

_FETCH_JS = """async (url) => {
  const r = await fetch(url, {headers: {'X-Requested-With': 'XMLHttpRequest', 'Accept': 'application/json'}});
  return {status: r.status, text: await r.text()};
}"""


class HistoryError(Exception):
    pass


def _ensure_page(page):
    # fetch는 같은 출처의 로그인 쿠키로 나가야 하므로 www.dhlottery.co.kr 페이지 위에서 호출한다.
    if not page.url.startswith("https://www.dhlottery.co.kr/"):
        page.goto(LEDGER_PAGE, timeout=60000, wait_until='domcontentloaded')


def _api(page, path, params):
    _ensure_page(page)
    res = page.evaluate(_FETCH_JS, f"{path}?{urlencode(params)}")
    try:
        body = json.loads(res['text'])
    except ValueError:
        raise HistoryError(f"{path} 응답이 JSON이 아님 (status {res['status']}): {res['text'][:120]!r}")
    return body


def fetch_purchases(page, start, end):
    """start~end(date) 로또 6/45 구매내역. 3개월이 넘으면 나눠서 조회한다. 최신순."""
    rows = []
    window_end = end
    while window_end >= start:
        window_start = max(start, window_end - timedelta(days=MAX_RANGE_DAYS))
        page_num = 1
        while True:
            body = _api(page, "/mypage/selectMyLotteryledger.do", {
                "srchStrDt": window_start.strftime("%Y%m%d"), "srchEndDt": window_end.strftime("%Y%m%d"),
                "sort": "", "ltGdsCd": "LO40", "winResult": "", "lramSmam": "",
                "pageNum": page_num, "recordCountPerPage": PAGE_SIZE, "_": int(time.time() * 1000),
            })
            data = body.get('data')
            if data is None:
                raise HistoryError(f"구매내역 조회 실패: {body.get('resultMessage')}")
            batch = data.get('list') or []
            rows.extend(batch)
            if len(batch) < PAGE_SIZE or page_num * PAGE_SIZE >= (data.get('total') or 0):
                break
            page_num += 1
        window_end = window_start - timedelta(days=1)
    return rows


def fetch_ticket(page, row):
    body = _api(page, "/mypage/lotto645TicketDetail.do", {
        "ntslOrdrNo": row['ntslOrdrNo'], "barcd": row['gmInfo'], "_": int(time.time() * 1000)})
    ticket = (body.get('data') or {}).get('ticket')
    if not ticket:
        raise HistoryError(f"영수증 조회 실패 ({row.get('ltEpsd')}회): {body.get('resultMessage') or body.get('data')}")
    return ticket


def sync(page, days=None):
    """사이트 구매내역을 tickets.json에 반영한다. 추첨 결과가 바뀐 것만 영수증을 다시 받는다.

    days가 없으면 처음엔 2년, 이후엔 3개월을 본다. 반환: 새로 받거나 갱신한 영수증 수
    """
    stored = tickets.load()
    if days is None:
        days = MAX_RANGE_DAYS if stored else HISTORY_DAYS
    today = date.today()
    rows = fetch_purchases(page, today - timedelta(days=days), today)
    changed = 0
    for row in rows:
        old = stored.get(row.get('gmInfo'))
        if old and (old['drawn'] or row.get('ltWnResult') == '미추첨') and old.get('claimed') == row.get('wngsGiveYn'):
            continue
        try:
            record = tickets.from_site(row, fetch_ticket(page, row))
        except HistoryError as e:
            # 수령 기한이 지난 오래된 표는 상세 조회가 막힌다('유효하지 않은 티켓').
            # 금액·결과·당첨금은 목록 행에 있으므로 그것만 저장한다.
            if old:
                continue
            logger.debug(f"영수증 상세 없음 — 목록 정보만 저장: {e}")
            record = tickets.from_row_only(row)
        tickets.upsert(record)
        changed += 1
    logger.info(f"구매내역 동기화: 사이트 {len(rows)}건 / 갱신 {changed}건")
    return changed


# ── 구매 검증 ────────────────────────────────────────────────────────────

def find_purchases_since(page, since):
    """since(datetime) 이후에 산 영수증들 (오늘·어제 구매내역에서)."""
    found = []
    for row in fetch_purchases(page, since.date() - timedelta(days=1), date.today()):
        if row.get('eltOrdrDt', '') < since.strftime("%Y-%m-%d"):
            continue
        record = tickets.from_site(row, fetch_ticket(page, row))
        if record['sold_at'] >= since.isoformat(timespec='seconds'):
            found.append(record)
    return found


def verify_purchase(page, prepared, since):
    """방금 한 구매가 구매내역에 실제로 있는지, 요청한 게임 수·번호와 맞는지 확인한다.

    반환: (정상 여부, 디스코드용 메시지, 영수증 목록)
    """
    found = find_purchases_since(page, since - timedelta(minutes=1))
    if not found:
        return False, ("⚠️ 구매 검증 실패 — 방금 구매가 동행복권 구매내역에 보이지 않습니다. "
                       "구매내역을 직접 확인해 주세요."), []

    for rec in found:
        tickets.upsert(tickets.assign_modes(rec, prepared))

    games = [g for rec in found for g in rec['games']]
    rounds = sorted({rec['round'] for rec in found})
    fixed = [sorted(p['numbers']) for p in prepared if p.get('numbers') and len(p['numbers']) == 6]
    bought = [g['num'] for g in games]
    matched = sum(1 for nums in fixed if nums in bought)

    problems = []
    if len(games) != len(prepared):
        problems.append(f"게임 수가 다릅니다 (요청 {len(prepared)} / 구매 {len(games)})")
    if matched != len(fixed):
        problems.append(f"지정한 번호 중 {len(fixed) - matched}게임이 영수증에 없습니다")
    if len(found) > 1:
        problems.append(f"영수증이 {len(found)}장입니다 — 중복 구매인지 확인하세요")

    lines = [f"{g['idx']} {tickets.mode_label(g):<8} {' '.join(f'{n:02d}' for n in g['num'])}" for g in games]
    head = (f"🔎 구매 검증 {'✅ 정상' if not problems else '⚠️ 확인 필요'} — {', '.join(map(str, rounds))}회 "
            f"{len(games)}게임 {sum(r['amount'] for r in found):,}원"
            + (f" · 지정 번호 {matched}/{len(fixed)} 일치" if fixed else ""))
    msg = head + "\n" + "\n".join(f"- {p}" for p in problems) + ("\n" if problems else "") + "```\n" + "\n".join(lines) + "\n```"
    return not problems, msg, found


# ── 당첨 분석 ────────────────────────────────────────────────────────────

CLAIM_GUIDE = {
    1: "1등은 농협은행 본점에 신분증을 들고 방문해 수령합니다.",
    2: "고액 당첨금은 동행복권 홈페이지 '당첨금 지급 안내'에서 수령 방법을 확인하세요.",
    3: "고액 당첨금은 동행복권 홈페이지 '당첨금 지급 안내'에서 수령 방법을 확인하세요.",
}


def _fmt_game(g, win6, bonus):
    nums = " ".join(f"[{n:02d}]" if n in win6 else ("(" + f"{n:02d}" + ")" if n == bonus else f" {n:02d} ")
                    for n in g['num'])
    return nums


def analyze_round(round_no, records, draw=None):
    """한 회차 영수증들의 결과 메시지와 요약을 만든다.

    사이트 영수증의 등수와, 당첨번호 API로 직접 계산한 등수를 교차 확인한다.
    둘이 다르면 당첨이라고 단정하지 않는다 (거짓 당첨 알림 방지).
    반환: (메시지, 요약 문자열, 최고 등수) — 추첨 전이면 메시지는 None
    """
    records = [r for r in records if r['games']]
    if not records:
        return None, "번호 정보 없음", 0
    site_win = next((r for r in records if r['drawn'] and r.get('win_num')), None)
    api_win = (draw and [draw[f"num{i}"] for i in range(1, 7)], draw and draw.get('bonus'))
    if site_win:
        win6, bonus = site_win['win_num'], site_win['bonus']
        if api_win[0] and (sorted(api_win[0]) != sorted(win6) or api_win[1] != bonus):
            return (f"⚠️ {round_no}회 당첨번호가 사이트 영수증({win6}+{bonus})과 당첨번호 API({api_win[0]}+{api_win[1]})에서 "
                    "서로 다릅니다. 사이트에서 직접 확인해 주세요.", "확인 필요", 0)
    elif api_win[0]:
        win6, bonus = api_win  # 사이트 반영 전 — 직접 계산
    else:
        return None, "미추첨", 0

    best, total_site, lines, mismatch = 0, 0, [], False
    for rec in records:
        for g in rec['games']:
            hit = len(set(g['num']) & set(win6))
            rank = tickets.rank_of(g['num'], win6, bonus)
            if rec['drawn'] and g['site_rank'] != rank:
                mismatch = True
            best = rank if rank and (not best or rank < best) else best
            total_site += g.get('amt') or 0
            result = f"{rank}등" if rank else "낙첨"
            lines.append(f"{g['idx']} {_fmt_game(g, win6, bonus)}  {hit}개 {result}  {tickets.mode_label(g)}")

    prizes = (draw or {}).get('prizes') or {}
    head = (f"🎰 **{round_no}회 당첨 확인** — 당첨번호 {' '.join(f'{n:02d}' for n in sorted(win6))}"
            + (f" + 보너스 {bonus:02d}" if bonus is not None else ""))
    body = "```\n" + "\n".join(lines) + "\n```\n[ ]=일치 ( )=보너스"
    if mismatch:
        tail = "⚠️ 사이트 영수증의 등수와 직접 계산한 등수가 다릅니다. 사이트에서 직접 확인해 주세요."
        summary = "확인 필요"
    elif best:
        amount = total_site or sum(prizes.get(tickets.rank_of(g['num'], win6, bonus)) or 0
                                   for rec in records for g in rec['games'] if tickets.rank_of(g['num'], win6, bonus))
        expiry = min((r.get('claim_expiry') or '') for r in records) or ''
        expiry_txt = f"{expiry[:4]}-{expiry[4:6]}-{expiry[6:8]}" if len(expiry) == 8 else "추첨일로부터 1년"
        tail = (f"🎉 **축하합니다! 최고 {best}등 당첨** — 당첨금 {amount:,}원"
                + ("" if total_site else " (사이트 반영 전 예상액)") + f"\n📅 수령 기한: {expiry_txt}")
        if best <= 3:
            tail += "\n💡 " + CLAIM_GUIDE[best]
        else:
            tail += "\n💡 5만원 이하 당첨금은 보통 예치금으로 자동 지급됩니다. 예치금을 확인해 보세요."
        summary = f"{best}등 당첨 ({amount:,}원)"
    else:
        top = max(len(set(g['num']) & set(win6)) for rec in records for g in rec['games'])
        tail = f"낙첨 — 최고 {top}개 일치. 다음 기회에… 😭"
        summary = f"낙첨 (최고 {top}개 일치)"
    if not site_win:
        tail += "\n(사이트 결과 반영 전이라 당첨번호로 직접 계산했습니다.)"
    return f"{head}\n{body}\n{tail}", summary, best


def claim_reminders(now=None, days=60):
    """직접 수령해야 하는 1~3등 당첨금 중 기한이 days일 이내로 남은 것.

    4·5등은 예치금으로 자동 지급된다. 사이트의 수령 여부(wngsGiveYn)는 자동 지급된 5등도
    비어 있어(1207회 확인) 믿을 수 없으므로, 4·5등은 알리지 않는다.
    """
    now = now or datetime.now()
    out = []
    for rec in tickets.load().values():
        ev = tickets.evaluate(rec)
        if not ev or not any(1 <= e['rank'] <= 3 for e in ev) or rec.get('claimed') == 'Y':
            continue
        exp = rec.get('claim_expiry') or ''
        try:
            left = (datetime.strptime(exp, "%Y%m%d") - now).days
        except ValueError:
            continue
        if 0 <= left <= days:
            best = min(e['rank'] for e in ev if e['rank'])  # 1~3 중 하나
            out.append(f"⏰ {rec['round']}회 {best}등 당첨금 수령 기한이 {left}일 남았습니다 ({exp[:4]}-{exp[4:6]}-{exp[6:]}). "
                       "이미 받았다면 무시하세요.")
    return out


if __name__ == "__main__":
    # 수동 동기화: python dh_history.py sync  (처음엔 최근 2년을 받아 통계를 채운다)
    import sys
    from auth import login, close_browser
    from security import SecurityManager
    if sys.argv[1:] != ['sync']:
        print("사용법: python dh_history.py sync")
        sys.exit(1)
    with open('config.json', encoding='utf-8') as f:
        cfg = json.load(f)
    browser, page = login(cfg['account']['user_id'], SecurityManager().decrypt(cfg['account']['user_pw']), headless=True)
    try:
        print(f"갱신 {sync(page)}건")
        print(tickets.stats_text())
    finally:
        close_browser(browser)
