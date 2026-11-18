"""동행복권 접속 확인(터널 끊김 감지)."""
import socket
from datetime import datetime, timedelta

import bot_watchdog
import reachability

DOWN = {"ok": False, "results": [
    {"host": "www.dhlottery.co.kr", "ips": ["183.110.231.3"], "error": "연결 시간 초과"}]}
UP = {"ok": True, "results": [
    {"host": "www.dhlottery.co.kr", "ips": ["183.110.231.3"], "error": None}]}


class _FakeBot:
    pid_file = "/nonexistent/bot.pid"

    def is_running(self):
        return True


def _setup(monkeypatch, data_dir):
    import ledger
    monkeypatch.setattr(bot_watchdog, "_load_config",
                        lambda: {"schedule": {"buy_day": "Friday", "buy_time": "19:30"}})
    monkeypatch.setattr(bot_watchdog, "_read_status", lambda: {})
    with ledger.edit() as d:
        d["watchdog"] = {"since": "2026-11-18T00:00:00", "sched_key": "Friday 19:30"}


def _tick(now):
    bot_watchdog.tick(_FakeBot(), lambda m: None, "/nonexistent.log", now=now)


def test_alerts_after_two_failures_once_then_recovery(data_dir, monkeypatch, no_discord):
    _setup(monkeypatch, data_dir)
    state = {"r": DOWN}
    monkeypatch.setattr(reachability, "check", lambda *a, **k: state["r"])
    t = datetime(2026, 11, 18, 12, 0)

    _tick(t)                                   # 1회 실패: 아직 알리지 않음
    assert not any("접속할 수 없습니다" in m for m in no_discord)
    _tick(t + timedelta(minutes=5))            # 10분 안 됨: 확인 안 함
    assert not any("접속할 수 없습니다" in m for m in no_discord)
    _tick(t + timedelta(minutes=10))           # 2회 연속 실패: 알림
    _tick(t + timedelta(minutes=20))           # 계속 실패해도 반복 알림 없음
    down_msgs = [m for m in no_discord if "접속할 수 없습니다" in m]
    assert len(down_msgs) == 1
    assert "183.110.231.3" in down_msgs[0] and "11/20(금) 19:30" in down_msgs[0]

    state["r"] = UP
    _tick(t + timedelta(minutes=30))
    _tick(t + timedelta(minutes=40))
    assert sum("다시 됩니다" in m for m in no_discord) == 1


def test_single_blip_is_not_alerted(data_dir, monkeypatch, no_discord):
    _setup(monkeypatch, data_dir)
    seq = iter([DOWN, UP, DOWN, UP])
    monkeypatch.setattr(reachability, "check", lambda *a, **k: next(seq))
    t = datetime(2026, 11, 18, 12, 0)
    for i in range(4):
        _tick(t + timedelta(minutes=10 * i))
    assert not no_discord


def test_check_reports_timeout_per_host(monkeypatch):
    # 위 conftest 패치를 걷어내고 실제 check()를 소켓만 가짜로 돌린다.
    import importlib
    real = importlib.reload(reachability)
    monkeypatch.setattr(real, "_resolve", lambda host: ["183.110.231.3"])

    def connect(addr, timeout):
        raise socket.timeout()
    monkeypatch.setattr(real.socket, "create_connection", connect)
    r = real.check()
    assert r["ok"] is False
    assert all(x["error"] == "연결 시간 초과" for x in r["results"])
    assert "183.110.231.3" in real.describe(r)


def test_buy_job_warns_when_site_down(monkeypatch, no_discord):
    import main
    monkeypatch.setattr(reachability, "check", lambda *a, **k: DOWN)
    main._warn_if_site_down("구매")
    assert any("구매 전에 확인해 보니" in m for m in no_discord)
