"""测试 ETF 轮动主策略 — 集成测试 (mock DB)"""
from datetime import date
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from src.strategy.base import HoldingPosition, Signal


def _make_price_matrix(
    n_days: int = 280,
    codes: list[str] | None = None,
    trends: list[float] | None = None,
) -> pd.DataFrame:
    codes = codes or [
        "510300.SH", "159915.SZ", "510500.SH", "510880.SH",
        "513100.SH", "511260.SH", "511010.SH",
    ]
    trends = trends or [0.002, 0.003, 0.001, 0.0005, 0.0015, 0.0002, 0.0001]
    dates = pd.bdate_range("2024-01-01", periods=n_days)
    rng = np.random.RandomState(42)
    data = {}
    for code, trend in zip(codes, trends):
        daily = 1 + trend + rng.normal(0, 0.005, n_days)
        data[code] = 100.0 * np.cumprod(daily)
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def mock_prices():
    return _make_price_matrix()


@pytest.fixture
def strategy_instance(mock_prices):
    """创建策略实例, mock DB 加载"""
    with patch("src.strategy.etf_rotation.universe.get_session") as mock_sess:
        mock_ctx = MagicMock()
        mock_sess.return_value.__enter__ = MagicMock(return_value=mock_ctx)
        mock_sess.return_value.__exit__ = MagicMock(return_value=False)

        rows = []
        for col in mock_prices.columns:
            for dt, val in mock_prices[col].items():
                rows.append((dt.date(), col, val))
        mock_ctx.execute.return_value.all.return_value = rows

        from src.strategy.etf_rotation.etf_rotation_strategy import ETFRotationStrategy
        strat = ETFRotationStrategy()
        return strat, mock_sess, mock_ctx, rows


class TestETFRotationStrategy:
    def test_class_attributes(self):
        from src.strategy.etf_rotation.etf_rotation_strategy import ETFRotationStrategy
        assert ETFRotationStrategy.tier == "rule"
        assert ETFRotationStrategy.name == "etf_rotation"

    def test_registered(self):
        import src.strategy.etf_rotation.etf_rotation_strategy  # noqa: F401
        from src.strategy.registry import registry
        cls = registry.get("etf_rotation")
        assert cls is not None
        assert cls.name == "etf_rotation"

    def test_generate_signals_first_rebalance(self, strategy_instance, mock_prices):
        strat, mock_sess, mock_ctx, rows = strategy_instance

        with patch("src.strategy.etf_rotation.universe.get_session") as ms:
            ctx = MagicMock()
            ms.return_value.__enter__ = MagicMock(return_value=ctx)
            ms.return_value.__exit__ = MagicMock(return_value=False)
            ctx.execute.return_value.all.return_value = rows

            signals = strat.generate_signals(
                trade_date=date(2025, 2, 1),
                universe=list(mock_prices.columns),
                holdings=None,
            )

        assert isinstance(signals, list)
        for s in signals:
            assert isinstance(s, Signal)
            assert s.strategy_name == "etf_rotation"

    def test_generate_signals_no_data(self, strategy_instance):
        strat, *_ = strategy_instance

        with patch("src.strategy.etf_rotation.universe.get_session") as ms:
            ctx = MagicMock()
            ms.return_value.__enter__ = MagicMock(return_value=ctx)
            ms.return_value.__exit__ = MagicMock(return_value=False)
            ctx.execute.return_value.all.return_value = []

            signals = strat.generate_signals(
                trade_date=date(2025, 2, 1),
                universe=["510300.SH"],
            )

        assert signals == []

    def test_generate_signals_with_holdings(self, strategy_instance, mock_prices):
        strat, mock_sess, mock_ctx, rows = strategy_instance

        holdings = [
            HoldingPosition(
                code="510300.SH", buy_date=date(2025, 1, 1), buy_price=100.0,
                quantity=1000, current_price=110.0, hold_days=20, can_sell=True,
            ),
        ]

        with patch("src.strategy.etf_rotation.universe.get_session") as ms:
            ctx = MagicMock()
            ms.return_value.__enter__ = MagicMock(return_value=ctx)
            ms.return_value.__exit__ = MagicMock(return_value=False)
            ctx.execute.return_value.all.return_value = rows

            signals = strat.generate_signals(
                trade_date=date(2025, 2, 1),
                universe=list(mock_prices.columns),
                holdings=holdings,
            )

        assert isinstance(signals, list)

    def test_disabled_returns_empty(self):
        with patch("src.strategy.etf_rotation.etf_rotation_strategy.settings") as ms:
            ms.etf_rotation.enabled = False
            from src.strategy.etf_rotation.etf_rotation_strategy import ETFRotationStrategy
            strat = ETFRotationStrategy.__new__(ETFRotationStrategy)
            strat.config = {}
            strat._cfg = ms.etf_rotation
            strat._universe = MagicMock()
            strat._rotator = MagicMock()
            strat._crash_guard = MagicMock()
            strat._last_rebalance_date = None

            signals = strat.generate_signals(date(2025, 2, 1), ["A"])
            assert signals == []
