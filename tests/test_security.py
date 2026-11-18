import json

import pytest

import security


@pytest.fixture
def paths(tmp_path, monkeypatch):
    key, cfg = tmp_path / "secret.key", tmp_path / "config.json"
    monkeypatch.setattr(security, "KEY_FILE", str(key))
    monkeypatch.setattr(security, "CONFIG_FILE", str(cfg))
    return key, cfg


def test_roundtrip_and_creates_key_on_first_setup(paths):
    key, _ = paths
    sm = security.SecurityManager()
    assert key.exists()
    assert sm.decrypt(sm.encrypt("비밀")) == "비밀"
    assert sm.decrypt("garbage") is None


def test_placeholder_config_still_allows_first_setup(paths):
    """config.example.json을 복사한 직후(평문 자리표시자)에는 키를 새로 만들어도 된다."""
    key, cfg = paths
    cfg.write_text(json.dumps({"account": {"user_pw": "YOUR_PASSWORD_HERE"}}))
    security.SecurityManager()
    assert key.exists()


def test_refuses_new_key_when_ciphertext_exists(paths):
    """암호문이 있는데 키가 없으면 새 키를 만들지 않는다 (만들면 기존 비밀번호를 영영 못 푼다)."""
    key, cfg = paths
    cfg.write_text(json.dumps({"account": {"user_pw": "gAAAAABfakeciphertext"}}))
    with pytest.raises(security.SecretKeyError):
        security.SecurityManager()
    assert not key.exists()


def test_key_mounted_as_directory(paths):
    key, _ = paths
    key.mkdir()
    with pytest.raises(security.SecretKeyError, match="디렉토리"):
        security.SecurityManager()
