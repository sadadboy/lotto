import pytest


@pytest.fixture
def main(monkeypatch, tmp_path):
    from loguru import logger
    import main as m
    # main은 import 시 logs/bot.log 싱크를 추가한다. 테스트 로그가 운영 로그에 섞이지 않게 뗀다.
    logger.remove()
    monkeypatch.setattr(m, "_mark_last_run", lambda: None)
    return m


def test_build_scheduler_registers_three_jobs(main):
    scheduler, errors = main._build_scheduler(
        {"buy_day": "Saturday", "buy_time": "10:00", "deposit_day": "Friday", "deposit_time": "18:00",
         "check_day": "Saturday", "check_time": "23:00"})
    assert errors == []
    assert len(scheduler.get_jobs()) == 3


def test_build_scheduler_rejects_bad_config_without_partial_jobs(main):
    scheduler, errors = main._build_scheduler({"buy_time": "", "check_day": "Funday"})
    assert len(errors) == 2
    assert scheduler.get_jobs() == []


class _Sec:
    def decrypt(self, value):
        return "pw"


def _setup_buy(main, monkeypatch, buy_result):
    monkeypatch.setattr(main, "load_config", lambda: {
        "account": {"user_id": "id", "user_pw": "enc"},
        "games": [{"id": 1, "active": True, "mode": "auto"}],
        "limits": {"weekly_buy": 5000, "monthly_buy": 25000}})
    monkeypatch.setattr(main, "SecurityManager", _Sec)
    monkeypatch.setattr(main, "login", lambda *a, **k: (None, object()))
    monkeypatch.setattr(main, "buy_games", lambda *a, **k: buy_result)


def test_buy_job_not_purchased_is_not_recorded_as_ok(main, data_dir, monkeypatch):
    """'구매하기'를 누르지 않았는데 성공으로 기록하면 한도가 깎이고 산 것처럼 보인다."""
    import ledger
    _setup_buy(main, monkeypatch, {"purchased": False, "reason": "구매 가능 수량 0"})
    main.buy_job()
    purchases = ledger.load()["purchases"]
    assert [p["status"] for p in purchases] == ["skipped"]
    assert ledger.spent("purchases", ledger.week_start()) == 0


def test_buy_job_success_is_recorded(main, data_dir, monkeypatch):
    import ledger
    _setup_buy(main, monkeypatch, {"purchased": True, "verified": True, "rounds": [1200]})
    main.buy_job()
    purchases = ledger.load()["purchases"]
    assert [(p["status"], p["amount"]) for p in purchases] == [("ok", 1000)]
    assert purchases[0]["note"] == "1200회"
