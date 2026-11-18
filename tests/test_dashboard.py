"""대시보드 설정 저장 API. 실제 config.json/secret.key 대신 임시 파일을 쓴다."""
import json

import pytest


@pytest.fixture
def client(tmp_path, monkeypatch):
    import security
    import access
    from werkzeug.security import generate_password_hash

    key, cfg = tmp_path / "secret.key", tmp_path / "config.json"
    pw_hash = generate_password_hash("test-password")
    cfg.write_text(json.dumps({
        "games": [{"id": 1, "active": True, "mode": "manual", "numbers": "1,2,3,4,5,6"}],
        "schedule": {"buy_day": "Saturday", "buy_time": "10:00"},
        "system": {"dashboard_password_hash": pw_hash},
    }), encoding="utf-8")
    for mod, attr, val in ((security, "KEY_FILE", key), (security, "CONFIG_FILE", cfg),
                           (access, "KEY_FILE", key), (access, "CONFIG_FILE", cfg)):
        monkeypatch.setattr(mod, attr, str(val))
    security.SecurityManager()  # 임시 키 생성 (access가 세션 서명에 쓴다)

    import app as dashboard_app
    monkeypatch.setattr(dashboard_app, "CONFIG_FILE", str(cfg))
    monkeypatch.setattr(dashboard_app, "dash_log", lambda m: None)
    dashboard_app.app.config["TESTING"] = True
    c = dashboard_app.app.test_client()
    with c.session_transaction() as s:
        s["auth"] = access._fingerprint(pw_hash)
    c.cfg = cfg
    c.module = dashboard_app
    return c


def test_requires_login(client):
    with client.session_transaction() as s:
        s.clear()
    assert client.post("/api/config", json={}).status_code == 401


def test_rejects_invalid_numbers_and_keeps_file(client):
    before = client.cfg.read_text(encoding="utf-8")
    res = client.post("/api/config", json={
        "games": [{"id": 1, "active": True, "mode": "manual", "numbers": "1,2,3,4,5,46"}]})
    assert res.status_code == 400
    assert "Game 1" in res.get_json()["message"]
    assert client.cfg.read_text(encoding="utf-8") == before


def test_rejects_empty_schedule_time(client):
    res = client.post("/api/config", json={"schedule": {"buy_day": "Saturday", "buy_time": ""}})
    assert res.status_code == 400


def test_saves_valid_config_and_keeps_unknown_keys(client):
    res = client.post("/api/config", json={"schedule": {"buy_day": "Sunday", "buy_time": "09:00"}})
    assert res.status_code == 200
    saved = json.loads(client.cfg.read_text(encoding="utf-8"))
    assert saved["schedule"]["buy_day"] == "Sunday"
    assert saved["system"]["dashboard_password_hash"]  # 화면에 없는 설정은 지워지지 않는다


def test_save_failure_is_reported(client, monkeypatch):
    def boom(config):
        raise OSError("No space left on device")
    monkeypatch.setattr(client.module, "save_config", boom)
    res = client.post("/api/config", json={"schedule": {"buy_day": "Sunday", "buy_time": "09:00"}})
    assert res.status_code == 500
    assert res.get_json()["status"] == "error"
