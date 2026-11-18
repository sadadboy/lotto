from datetime import datetime

import pytest

import bot_watchdog


def test_last_and_next_slot():
    now = datetime(2026, 11, 17, 12, 0)  # 화
    assert bot_watchdog.last_slot("Saturday", "10:00", now) == datetime(2026, 11, 14, 10, 0)
    assert bot_watchdog.next_slot("Saturday", "10:00", now) == datetime(2026, 11, 21, 10, 0)
    # 같은 요일, 아직 시각 전이면 지난주
    assert bot_watchdog.last_slot("Tuesday", "13:00", now) == datetime(2026, 11, 10, 13, 0)
    assert bot_watchdog.last_slot("Nopeday", "10:00", now) is None


@pytest.mark.parametrize("sched, n_errors", [
    ({}, 0),                                                     # 전부 기본값
    ({"buy_day": "saturday", "buy_time": "06:30"}, 0),
    ({"buy_time": ""}, 1),                                       # 시간 칸을 비움
    ({"buy_time": "25:00"}, 1),
    ({"check_time": "9:00"}, 1),                                 # schedule 라이브러리는 HH:MM만 받는다
    ({"deposit_day": "금요일"}, 1),
    ({"buy_day": "x", "buy_time": "x"}, 2),
])
def test_schedule_errors(sched, n_errors):
    assert len(bot_watchdog.schedule_errors(sched)) == n_errors


class _FakeBot:
    pid_file = "/nonexistent/bot.pid"

    def is_running(self):
        return True


def test_watchdog_alerts_missed_purchase_once(data_dir, monkeypatch, no_discord):
    import ledger
    monkeypatch.setattr(bot_watchdog, "_load_config",
                        lambda: {"schedule": {"buy_day": "Saturday", "buy_time": "10:00"}})
    monkeypatch.setattr(bot_watchdog, "_read_status", lambda: {})
    with ledger.edit() as d:
        d["watchdog"] = {"since": "2026-11-01T00:00:00", "sched_key": "Saturday 10:00"}

    late = datetime(2026, 11, 14, 12, 0)  # 토 10:00 + 2시간, 구매 기록 없음
    bot_watchdog.tick(_FakeBot(), lambda m: None, "/nonexistent.log", now=late)
    bot_watchdog.tick(_FakeBot(), lambda m: None, "/nonexistent.log", now=late)
    assert sum("예약 구매가 실행되지 않았습니다" in m for m in no_discord) == 1


def test_watchdog_quiet_when_purchase_recorded(data_dir, monkeypatch, no_discord):
    import ledger
    monkeypatch.setattr(bot_watchdog, "_load_config",
                        lambda: {"schedule": {"buy_day": "Saturday", "buy_time": "10:00"}})
    monkeypatch.setattr(bot_watchdog, "_read_status", lambda: {})
    with ledger.edit() as d:
        d["watchdog"] = {"since": "2026-11-01T00:00:00", "sched_key": "Saturday 10:00"}
        d["purchases"].append({"at": "2026-11-14T10:05:00", "status": "ok", "amount": 5000})

    bot_watchdog.tick(_FakeBot(), lambda m: None, "/nonexistent.log", now=datetime(2026, 11, 14, 12, 0))
    assert not no_discord
