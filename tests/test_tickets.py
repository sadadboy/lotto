import pytest

import dh_history
import tickets

WIN = [1, 2, 3, 4, 5, 6]
BONUS = 7


@pytest.mark.parametrize("numbers, rank", [
    ([1, 2, 3, 4, 5, 6], 1),
    ([1, 2, 3, 4, 5, 7], 2),
    ([1, 2, 3, 4, 5, 8], 3),
    ([1, 2, 3, 4, 8, 9], 4),
    ([1, 2, 3, 8, 9, 10], 5),
    ([1, 2, 7, 8, 9, 10], 0),   # 2개 + 보너스는 낙첨
])
def test_rank_of(numbers, rank):
    assert tickets.rank_of(numbers, WIN, BONUS) == rank


def _record(games, drawn=True, amount=None, win_total=0, round_no=1200, mode=None):
    return {
        "barcode": f"b{round_no}", "round": round_no, "sold_at": f"2026-01-{round_no % 28 + 1:02d}T10:00:00",
        "draw_date": "2026-01-01", "amount": amount if amount is not None else 1000 * len(games),
        "drawn": drawn, "win_num": WIN if drawn else None, "bonus": BONUS if drawn else None,
        "win_total": win_total, "claim_expiry": "", "games": [
            {"idx": "A", "type": 3, "num": g, "site_rank": tickets.rank_of(g, WIN, BONUS) if drawn else 0,
             "amt": 5000 if drawn and tickets.rank_of(g, WIN, BONUS) == 5 else 0, **({"mode": mode} if mode else {})}
            for g in games],
    }


def test_stats_counts_spent_won_and_pending():
    data = {
        "a": _record([[1, 2, 3, 10, 11, 12], [20, 21, 22, 23, 24, 25]], win_total=5000, round_no=1200, mode="ai"),
        "b": _record([[1, 2, 3, 4, 5, 6]], drawn=False, round_no=1201),
    }
    s = tickets.stats(data)
    assert s["spent"] == 3000
    assert s["pending_spent"] == 1000
    assert s["won"] == 5000
    assert s["games"] == 2
    assert s["by_rank"]["5"] == 1
    assert s["return_rate"] == 250.0
    assert s["by_mode"]["AI 추천"]["wins"] == 1


def test_analyze_round_reports_win():
    rec = _record([[1, 2, 3, 10, 11, 12]])
    msg, summary, best = dh_history.analyze_round(1200, [rec])
    assert best == 5
    assert "5등 당첨" in summary
    assert "축하합니다" in msg


def test_analyze_round_refuses_when_sources_disagree():
    """사이트 영수증과 당첨번호 API가 다르면 당첨이라고 단정하지 않는다."""
    rec = _record([[1, 2, 3, 4, 5, 6]])
    draw = {f"num{i}": n for i, n in enumerate([10, 11, 12, 13, 14, 15], 1)} | {"bonus": 16}
    msg, summary, best = dh_history.analyze_round(1200, [rec], draw)
    assert best == 0
    assert summary == "확인 필요"


def test_analyze_round_before_draw():
    rec = _record([[1, 2, 3, 4, 5, 6]], drawn=False)
    msg, summary, best = dh_history.analyze_round(1200, [rec], None)
    assert msg is None and summary == "미추첨"
