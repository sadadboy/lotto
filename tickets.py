"""구매한 로또 영수증 저장소와 당첨 판정·통계 (data/tickets.json).

동행복권 구매내역 API에서 받은 영수증을 바코드별로 저장한다. 사이트는 최근 3개월만
조회되므로 여기 쌓아 두어야 누적 통계를 낼 수 있다.

게임별 'mode'(ai, max_first ...)는 봇이 구매할 때만 알 수 있다. 사이트는 자동/수동/반자동만
구분하므로, 이 기능 이전에 산 영수증은 mode가 없다(전략 미기록).
"""
import json
import os
from contextlib import contextmanager

import ledger  # 같은 data/ 디렉터리와 잠금을 쓴다

TICKETS_PATH = os.path.join(ledger.DATA_DIR, 'tickets.json')

# 영수증 game_dtl.type
TYPE_KO = {1: "수동", 2: "반자동", 3: "자동"}
MODE_KO = {"auto": "자동", "semi_auto": "반자동", "manual": "수동", "ai": "AI 추천", "max_first": "1등 최다 번호"}


def _read():
    try:
        with open(TICKETS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def load():
    with ledger._locked():
        return _read()


@contextmanager
def edit():
    with ledger._locked():
        data = _read()
        yield data
        tmp = TICKETS_PATH + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=1, ensure_ascii=False)
        os.replace(tmp, TICKETS_PATH)


# ── 당첨 판정 ────────────────────────────────────────────────────────────

def rank_of(numbers, win6, bonus):
    """로또 6/45 등수. 0이면 낙첨."""
    hit = len(set(numbers) & set(win6))
    if hit == 6:
        return 1
    if hit == 5:
        return 2 if bonus in numbers else 3
    return {4: 4, 3: 5}.get(hit, 0)


def mode_label(game):
    mode = game.get('mode')
    if mode:
        return MODE_KO.get(mode, mode)
    return f"{TYPE_KO.get(game.get('type'), '?')}(전략 미기록)"


# ── 사이트 데이터 → 저장 형식 ────────────────────────────────────────────

def from_site(row, ticket):
    """구매내역 행(row) + 영수증 상세(ticket) → 저장용 dict."""
    win = ticket.get('win_num') or []
    drawn = bool(ticket.get('drawed')) and any(win)
    return {
        "barcode": ticket.get('barcode') or row.get('gmInfo'),
        "order_no": row.get('ntslOrdrNo'),
        "round": int(ticket.get('game_round') or row.get('ltEpsd')),
        "sold_at": _sold_at(ticket),
        "draw_date": (ticket.get('draw_date') or row.get('epsdRflDt') or '').replace('/', '-'),
        "amount": int(ticket.get('ticket_amt') or (row.get('prchsQty') or 0) * 1000),
        "drawn": drawn,
        "win_num": win[:6] if drawn else None,
        "bonus": win[6] if drawn and len(win) > 6 else None,
        "win_total": int(ticket.get('win_total_amt') or row.get('ltWnAmt') or 0),
        "site_result": row.get('ltWnResult'),
        "claim_expiry": row.get('wngsGiveExpryYmd') or (ticket.get('pay_end_date') or '').replace('/', ''),
        "claimed": row.get('wngsGiveYn'),
        "games": [{"idx": g.get('idx'), "type": g.get('type'), "num": sorted(g.get('num') or []),
                   "site_rank": int(g.get('rank') or 0), "amt": int(g.get('amt') or 0)}
                  for g in ticket.get('game_dtl') or []],
    }


def from_row_only(row):
    """영수증 상세를 못 받은 오래된 표 — 목록 행 정보만. games가 비어 있어 게임별 통계에서는 빠진다."""
    result = row.get('ltWnResult')
    return {
        "barcode": row.get('gmInfo'),
        "order_no": row.get('ntslOrdrNo'),
        "round": int(row.get('ltEpsd')),
        "sold_at": row.get('eltOrdrDt') or '',
        "draw_date": row.get('epsdRflDt') or '',
        "amount": int(row.get('prchsQty') or 0) * 1000,
        "drawn": result not in (None, '미추첨'),
        "win_num": None,
        "bonus": None,
        "win_total": int(row.get('ltWnAmt') or 0),
        "site_result": result,
        "claim_expiry": row.get('wngsGiveExpryYmd') or '',
        "claimed": row.get('wngsGiveYn'),
        "games": [],
        "detail": False,
    }


def _sold_at(ticket):
    s = str(ticket.get('svr_ntss_dttm') or '')
    if len(s) == 14:
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}T{s[8:10]}:{s[10:12]}:{s[12:14]}"
    return (ticket.get('sale_date') or '')[:10].replace('/', '-')


def assign_modes(record, prepared):
    """봇이 준비한 게임(prepared)의 mode를 영수증 게임에 붙인다.

    번호를 지정한 게임은 번호 집합이 같은 것끼리, 나머지(사이트 자동선택)는 순서대로 맞춘다.
    """
    remaining = list(prepared or [])
    games = record['games']
    for g in games:
        for p in remaining:
            if p.get('numbers') and sorted(p['numbers']) == g['num']:
                g['mode'] = p['mode']
                remaining.remove(p)
                break
    for g in games:
        if 'mode' not in g and remaining:
            g['mode'] = remaining.pop(0)['mode']
    return record


def upsert(record):
    """저장. 이미 있으면 사이트 값만 갱신하고 봇이 붙인 mode는 유지한다."""
    with edit() as data:
        old = data.get(record['barcode'])
        if old:
            modes = {g['idx']: g.get('mode') for g in old.get('games', [])}
            for g in record['games']:
                if modes.get(g['idx']) and not g.get('mode'):
                    g['mode'] = modes[g['idx']]
        data[record['barcode']] = record


# ── 통계 ────────────────────────────────────────────────────────────────

def evaluate(record):
    """게임별 일치 개수와 등수를 직접 계산한다 (추첨 전이거나 번호를 모르면 None)."""
    if not record.get('drawn') or not record.get('win_num'):
        return None
    win6, bonus = record['win_num'], record['bonus']
    return [{"hit": len(set(g['num']) & set(win6)), "bonus_hit": bonus in g['num'],
             "rank": rank_of(g['num'], win6, bonus)} for g in record['games']]


def stats(data=None):
    data = load() if data is None else data
    records = sorted(data.values(), key=lambda r: r.get('sold_at', ''))
    out = {
        "tickets": len(records), "games": 0, "spent": 0, "won": 0,
        "pending_spent": 0, "by_rank": {str(r): 0 for r in range(1, 6)},
        "hits": {str(h): 0 for h in range(7)}, "by_mode": {},
        "first": records[0]['sold_at'][:10] if records else None,
        "last": records[-1]['sold_at'][:10] if records else None,
    }
    out['no_detail'] = 0
    for rec in records:
        out['spent'] += rec['amount']
        if not rec.get('drawn'):
            out['pending_spent'] += rec['amount']
            continue
        out['won'] += rec.get('win_total') or 0
        ev = evaluate(rec)
        if ev is None:
            # 번호를 모르는 오래된 표: 금액·당첨금만 반영하고 게임별 통계에서는 뺀다.
            out['no_detail'] += 1
            continue
        for g, e in zip(rec['games'], ev):
            out['games'] += 1
            out['hits'][str(e['hit'])] += 1
            if e['rank']:
                out['by_rank'][str(e['rank'])] += 1
            m = out['by_mode'].setdefault(mode_label(g), {"games": 0, "wins": 0, "won": 0, "hit_sum": 0})
            m['games'] += 1
            m['hit_sum'] += e['hit']
            if e['rank']:
                m['wins'] += 1
                m['won'] += g.get('amt') or 0
    drawn_spent = out['spent'] - out['pending_spent']
    out['return_rate'] = round(out['won'] / drawn_spent * 100, 1) if drawn_spent else None
    for m in out['by_mode'].values():
        m['avg_hit'] = round(m['hit_sum'] / m['games'], 2) if m['games'] else 0
    return out


def stats_text(s=None):
    s = s or stats()
    if not s['tickets']:
        return "아직 저장된 구매 기록이 없습니다."
    drawn_spent = s['spent'] - s['pending_spent']
    lines = [
        f"📈 **누적 통계** ({s['first']} ~ {s['last']}, 영수증 {s['tickets']}장)",
        f"구매 {s['spent']:,}원 (추첨 전 {s['pending_spent']:,}원) / 당첨금 {s['won']:,}원"
        + (f" / 회수율 {s['return_rate']}%" if s['return_rate'] is not None else ""),
        f"손익 {s['won'] - drawn_spent:+,}원 (추첨 끝난 {s['games']}게임 기준)",
        "등수: " + " · ".join(f"{r}등 {s['by_rank'][r]}" for r in ('1', '2', '3', '4', '5')),
        "일치 개수: " + " · ".join(f"{h}개 {s['hits'][h]}" for h in ('0', '1', '2', '3', '4', '5', '6') if s['hits'][h]),
        *([f"(번호 정보가 없는 오래된 영수증 {s['no_detail']}장은 금액·당첨금만 반영)"] if s.get('no_detail') else []),
        "",
        "**전략별** (게임 수 · 평균 일치 · 당첨)",
    ]
    for name, m in sorted(s['by_mode'].items(), key=lambda kv: -kv[1]['games']):
        lines.append(f"{name}: {m['games']}게임 · {m['avg_hit']}개 · {m['wins']}회" + (f" ({m['won']:,}원)" if m['won'] else ""))
    lines.append("※ 무작위 번호의 기대 평균 일치는 0.8개입니다.")
    return "\n".join(lines)
