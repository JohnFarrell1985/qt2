"""测试轮动引擎"""
from datetime import date

import pandas as pd

from src.strategy.base import HoldingPosition
from src.strategy.etf_rotation.rotator import ETFRotator


class TestRankAndSelect:
    def test_basic_top_k(self):
        scores = pd.Series({"A": 0.5, "B": 0.3, "C": 0.8, "D": 0.1})
        result = ETFRotator.rank_and_select(scores, top_k=2)
        assert result == ["C", "A"]

    def test_score_bounds(self):
        scores = pd.Series({"A": 0.5, "B": -0.1, "C": 6.0, "D": 0.3})
        result = ETFRotator.rank_and_select(scores, top_k=3, score_min=0.0, score_max=5.0)
        assert "B" not in result, "负分应被过滤"
        assert "C" not in result, "超高分应被过滤"
        assert result == ["A", "D"]

    def test_empty_scores(self):
        assert ETFRotator.rank_and_select(pd.Series(dtype=float), top_k=2) == []

    def test_all_filtered(self):
        scores = pd.Series({"A": -1.0, "B": -0.5})
        assert ETFRotator.rank_and_select(scores, top_k=2, score_min=0.0) == []

    def test_fewer_than_top_k(self):
        scores = pd.Series({"A": 0.5})
        result = ETFRotator.rank_and_select(scores, top_k=3)
        assert result == ["A"]


class TestAntiWhipsaw:
    def test_no_holdings(self):
        result = ETFRotator.anti_whipsaw_filter(
            ["A", "B"], None, pd.Series({"A": 1, "B": 0.5}), 5, 0.10,
        )
        assert result == ["A", "B"]

    def test_hold_days_retention(self):
        holdings = [
            HoldingPosition(code="OLD", buy_date=date(2025, 1, 1), buy_price=10, quantity=100, hold_days=3),
        ]
        scores = pd.Series({"A": 1.0, "B": 0.5, "OLD": 0.3})
        result = ETFRotator.anti_whipsaw_filter(["A", "B"], holdings, scores, min_hold_days=5, rank_threshold=0.10)
        assert "OLD" in result, "未满持有天数的标的应保留"

    def test_rank_close_retention(self):
        holdings = [
            HoldingPosition(code="CLOSE", buy_date=date(2025, 1, 1), buy_price=10, quantity=100, hold_days=20),
        ]
        scores = pd.Series({"A": 1.0, "B": 0.5, "CLOSE": 0.95})
        result = ETFRotator.anti_whipsaw_filter(["A", "B"], holdings, scores, min_hold_days=5, rank_threshold=0.10)
        assert "CLOSE" in result, "分差 5% < 10% 阈值, 应保留"

    def test_rank_far_not_retained(self):
        holdings = [
            HoldingPosition(code="FAR", buy_date=date(2025, 1, 1), buy_price=10, quantity=100, hold_days=20),
        ]
        scores = pd.Series({"A": 1.0, "B": 0.5, "FAR": 0.1})
        result = ETFRotator.anti_whipsaw_filter(["A", "B"], holdings, scores, min_hold_days=5, rank_threshold=0.10)
        assert "FAR" not in result, "分差过大, 不应保留"


class TestCheckStopLoss:
    def test_daily_stop_loss(self):
        holdings = [
            HoldingPosition(
                code="DROP", buy_date=date(2025, 1, 1), buy_price=10.0,
                quantity=100, current_price=9.4, can_sell=True,
            ),
        ]
        result = ETFRotator.check_stop_loss(holdings, stop_loss_daily=0.05, stop_loss_3d=0.08)
        assert "DROP" in result, "单日跌 6% > 5% 阈值"

    def test_no_trigger(self):
        holdings = [
            HoldingPosition(
                code="OK", buy_date=date(2025, 1, 1), buy_price=10.0,
                quantity=100, current_price=9.7, can_sell=True,
            ),
        ]
        result = ETFRotator.check_stop_loss(holdings, stop_loss_daily=0.05, stop_loss_3d=0.08)
        assert result == []

    def test_3d_stop_loss(self):
        holdings = [
            HoldingPosition(
                code="SLOW", buy_date=date(2025, 1, 1), buy_price=10.0,
                quantity=100, current_price=9.7, can_sell=True,
            ),
        ]
        dates = pd.bdate_range("2025-01-01", periods=5)
        prices = pd.DataFrame({"SLOW": [10.0, 9.8, 9.5, 9.0, 8.8]}, index=dates)
        result = ETFRotator.check_stop_loss(holdings, stop_loss_daily=0.05, stop_loss_3d=0.05, prices=prices)
        assert "SLOW" in result, "3 日跌幅超阈值"

    def test_cannot_sell(self):
        holdings = [
            HoldingPosition(
                code="LOCK", buy_date=date(2025, 1, 1), buy_price=10.0,
                quantity=100, current_price=8.0, can_sell=False,
            ),
        ]
        result = ETFRotator.check_stop_loss(holdings, stop_loss_daily=0.05, stop_loss_3d=0.08)
        assert result == [], "T+1 当日不可卖"

    def test_empty_holdings(self):
        assert ETFRotator.check_stop_loss([], stop_loss_daily=0.05, stop_loss_3d=0.08) == []


class TestIsRebalanceDay:
    def test_first_time(self):
        assert ETFRotator.is_rebalance_day(None, date(2025, 6, 1), 20) is True

    def test_within_interval(self):
        assert ETFRotator.is_rebalance_day(date(2025, 5, 25), date(2025, 6, 1), 20) is False

    def test_past_interval(self):
        assert ETFRotator.is_rebalance_day(date(2025, 4, 1), date(2025, 6, 1), 20) is True
