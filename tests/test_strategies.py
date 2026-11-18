import pytest

import strategies


@pytest.mark.parametrize("text, mode, expected", [
    ("1, 2, 3, 4, 5, 6", "manual", [1, 2, 3, 4, 5, 6]),
    ("45,1,20,3,7,9", "manual", [1, 3, 7, 9, 20, 45]),
    (" 7 , 3 ", "semi_auto", [3, 7]),
    ("", "semi_auto", []),
    ("1,2,3,4,5,6", "semi_auto", [1, 2, 3, 4, 5, 6]),
    ("아무거나", "auto", []),        # 번호를 쓰지 않는 모드는 입력을 무시
    ("99", "ai", []),
])
def test_parse_numbers_ok(text, mode, expected):
    assert strategies.parse_numbers(text, mode) == (expected, None)


@pytest.mark.parametrize("text, mode, needle", [
    ("1,2,3,4,5,46", "manual", "1~45"),
    ("0,1,2,3,4,5", "manual", "1~45"),
    ("1,1,2,3,4,5", "manual", "중복"),
    ("1,2,3,4,5", "manual", "6개"),
    ("1,2,3,4,5,6,7", "manual", "6개"),
    ("1,2,a", "semi_auto", "숫자가 아닌"),
    ("1,2,3,4,5,6,7", "semi_auto", "6개 이하"),
    ("", "manual", "6개"),
])
def test_parse_numbers_rejects(text, mode, needle):
    numbers, err = strategies.parse_numbers(text, mode)
    assert numbers is None
    assert needle in err


def test_validate_games_skips_inactive_and_reports_active():
    games = [
        {"id": 1, "active": True, "mode": "manual", "numbers": "1,2,3,4,5,46"},
        {"id": 2, "active": False, "mode": "manual", "numbers": "엉망"},
        {"id": 3, "active": True, "mode": "bogus", "numbers": ""},
        {"id": 4, "active": True, "mode": "auto", "numbers": ""},
    ]
    errors = strategies.validate_games(games)
    assert len(errors) == 2
    assert errors[0].startswith("Game 1")
    assert errors[1].startswith("Game 3")


def test_semi_auto_without_numbers_is_site_auto():
    assert strategies.generate_numbers("semi_auto", []) is None


def test_manual_fallback_is_announced(monkeypatch):
    notices = []
    monkeypatch.setattr(strategies, "_notify_fallback", lambda label, reason: notices.append(reason))
    numbers = strategies.generate_numbers("manual", [1, 2, 3])
    assert len(numbers) == 6 and len(set(numbers)) == 6
    assert notices, "수동 번호가 랜덤으로 바뀌면 반드시 알려야 한다"
