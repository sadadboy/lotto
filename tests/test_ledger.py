from datetime import datetime

import ledger


def test_week_starts_on_sunday():
    sat = datetime(2026, 11, 14, 10, 0)   # 토
    sun = datetime(2026, 11, 15, 9, 0)    # 일
    assert ledger.week_start(sat) == datetime(2026, 11, 8)
    assert ledger.week_start(sun) == datetime(2026, 11, 15)


def test_spent_counts_ok_and_uncertain_only(data_dir):
    ledger.record_purchase('ok', games=5, amount=5000)
    ledger.record_purchase('uncertain', games=1, amount=1000)
    ledger.record_purchase('failed', games=5, amount=5000)
    ledger.record_purchase('skipped', games=5)
    assert ledger.spent('purchases', ledger.week_start()) == 6000


def test_check_limit_blocks_second_purchase_in_week(data_dir):
    config = {"limits": {"weekly_buy": 5000}}
    assert ledger.check_limit('buy', 5000, config) == (True, "")
    ledger.record_purchase('ok', games=5, amount=5000)
    allowed, reason = ledger.check_limit('buy', 5000, config)
    assert not allowed
    assert "이번 주 구매" in reason


def test_zero_limit_means_unlimited(data_dir):
    config = {"limits": {"weekly_buy": 0, "monthly_buy": 0}}
    ledger.record_purchase('ok', amount=100000)
    assert ledger.check_limit('buy', 5000, config)[0]


def test_skip_next_buy_is_consumed_once(data_dir):
    ledger.set_skip_next_buy(True)
    assert ledger.consume_skip_next_buy() is True
    assert ledger.consume_skip_next_buy() is False
