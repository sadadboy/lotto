import buy_lotto


def test_prepare_games_drops_invalid_numbers_and_warns(no_discord):
    games = [
        {"id": 1, "active": True, "mode": "manual", "numbers": "1,2,3,4,5,6"},
        {"id": 2, "active": True, "mode": "semi_auto", "numbers": "1,1"},   # 중복 → 사이트 자동
        {"id": 3, "active": False, "mode": "manual", "numbers": "99"},     # 비활성은 무시
    ]
    prepared = buy_lotto.prepare_games(games)
    assert [p["id"] for p in prepared] == [1, 2]
    assert prepared[0]["numbers"] == [1, 2, 3, 4, 5, 6]
    assert prepared[1]["numbers"] is None
    assert any("Game 2 번호 설정 오류" in m for m in no_discord)


def test_prepare_games_caps_at_five():
    games = [{"id": i, "active": True, "mode": "auto"} for i in range(1, 8)]
    assert len(buy_lotto.prepare_games(games)) == buy_lotto.MAX_GAMES_PER_PURCHASE


def test_buy_games_without_games_reports_not_purchased():
    assert buy_lotto.buy_games(page=None, games_config=[], prepared_games=[]) == {
        "purchased": False, "reason": "활성 게임 없음"}
