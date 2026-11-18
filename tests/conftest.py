"""공통 픽스처.

테스트는 네트워크·브라우저·디스코드에 절대 닿지 않는다. 실제 data/, logs/, config.json,
secret.key도 건드리지 않도록 경로를 전부 임시 디렉토리로 돌린다.
"""
import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "dashboard"))

# Playwright가 없는 환경에서도 buy_lotto/auth/main을 import할 수 있게 한다 (브라우저는 쓰지 않는다).
try:
    import playwright.sync_api  # noqa: F401
except ImportError:
    pw = types.ModuleType("playwright")
    api = types.ModuleType("playwright.sync_api")
    api.Page = object
    api.sync_playwright = lambda: (_ for _ in ()).throw(RuntimeError("테스트에서 브라우저 사용 금지"))
    pw.sync_api = api
    sys.modules["playwright"] = pw
    sys.modules["playwright.sync_api"] = api


@pytest.fixture(autouse=True)
def isolate(tmp_path, monkeypatch):
    """네트워크 차단 + 작업 디렉토리를 임시 폴더로 (상대경로 스크린샷 등이 저장소를 건드리지 않게)."""
    import requests

    def blocked(*a, **k):
        raise RuntimeError("테스트에서 네트워크 사용 금지")
    monkeypatch.setattr(requests, "post", blocked)
    monkeypatch.setattr(requests, "get", blocked)
    monkeypatch.setattr(requests.Session, "request", blocked)
    monkeypatch.chdir(tmp_path)
    # 동행복권 접속 확인(소켓 연결)도 기본은 '정상'으로. 실패 상황은 각 테스트가 따로 바꾼다.
    import reachability
    monkeypatch.setattr(reachability, "check", lambda *a, **k: {"ok": True, "results": []})


@pytest.fixture(autouse=True)
def no_discord(monkeypatch):
    """모든 디스코드 전송을 가로채 sent 리스트에 담는다."""
    sent = []
    import notification
    # 테스트 중에 처음 import되는 모듈은 아래 패치를 피해 가므로, 웹훅 주소 자체를 비워 둔다.
    monkeypatch.setattr(notification, "load_webhook_url", lambda: "")
    monkeypatch.setattr(notification, "send_discord_message", lambda msg, *a, **k: sent.append(msg) or True)
    monkeypatch.setattr(notification, "send_discord_file", lambda path, msg=None, *a, **k: sent.append(msg) or True)
    monkeypatch.setattr(notification, "send_debug_file", lambda *a, **k: False)
    # 이미 `from notification import send_discord_message`로 가져간 모듈들도 막는다.
    for name in ("strategies", "buy_lotto", "main", "bot_watchdog", "check_winning", "deposit"):
        mod = sys.modules.get(name)
        if mod is not None and hasattr(mod, "send_discord_message"):
            monkeypatch.setattr(mod, "send_discord_message", lambda msg, *a, **k: sent.append(msg) or True)
    return sent


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """ledger.json / tickets.json을 임시 디렉토리로."""
    import ledger
    import tickets
    d = tmp_path / "data"
    monkeypatch.setattr(ledger, "DATA_DIR", str(d))
    monkeypatch.setattr(ledger, "LEDGER_PATH", str(d / "ledger.json"))
    monkeypatch.setattr(ledger, "LOCK_PATH", str(d / "ledger.lock"))
    monkeypatch.setattr(tickets, "TICKETS_PATH", str(d / "tickets.json"))
    return d
