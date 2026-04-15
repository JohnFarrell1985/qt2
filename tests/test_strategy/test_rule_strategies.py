"""测试 Tier 1 规则策略

全部通过 mock QMTClient 来隔离 xtquant 依赖。
"""
from datetime import date
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np


def _make_price_df(n=30, base=10.0, trend=0.01):
    """生成模拟日线 DataFrame"""
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    closes = [base * (1 + trend) ** i for i in range(n)]
    return pd.DataFrame({
        "open": [c * 0.99 for c in closes],
        "high": [c * 1.01 for c in closes],
        "low": [c * 0.98 for c in closes],
        "close": closes,
        "volume": [1000000] * n,
        "amount": [c * 1000000 for c in closes],
        "turnoverRate": [2.0] * n,
    }, index=dates)


class TestMomentumStrategy:
    @patch("src.data.qmt_client.QMTClient")
    def test_basic(self, MockClient):
        from src.strategy.rules.momentum import MomentumStrategy

        mock_client = MockClient.return_value
        mock_client.get_market_data_ex.return_value = {
            "000001.SZ": _make_price_df(30, 10.0, 0.02),
            "000002.SZ": _make_price_df(30, 20.0, -0.01),
            "000003.SZ": _make_price_df(30, 15.0, 0.005),
        }

        strat = MomentumStrategy(config={"lookback_days": 20, "top_n": 2})
        signals = strat.generate_signals(date(2025, 6, 1), ["000001.SZ", "000002.SZ", "000003.SZ"])

        assert len(signals) <= 2
        assert all(s.direction == "buy" for s in signals)
        assert signals[0].score >= signals[1].score if len(signals) == 2 else True


class TestReversalStrategy:
    @patch("src.data.qmt_client.QMTClient")
    def test_basic(self, MockClient):
        from src.strategy.rules.reversal import ReversalStrategy

        mock_client = MockClient.return_value
        mock_client.get_market_data_ex.return_value = {
            "000001.SZ": _make_price_df(20, 10.0, -0.02),
            "000002.SZ": _make_price_df(20, 20.0, 0.01),
            "000003.SZ": _make_price_df(20, 15.0, -0.01),
        }

        strat = ReversalStrategy(config={"lookback_days": 10, "top_n": 5})
        signals = strat.generate_signals(date(2025, 6, 1), ["000001.SZ", "000002.SZ", "000003.SZ"])

        # 只选跌的
        for s in signals:
            assert s.direction == "buy"


class TestMovingAverageStrategy:
    @patch("src.data.qmt_client.QMTClient")
    def test_basic(self, MockClient):
        from src.strategy.rules.moving_average import MovingAverageStrategy

        # 构造均线金叉场景: 前期低迷, 后期快速上涨
        n = 30
        dates = pd.date_range("2025-01-01", periods=n, freq="B")
        closes = [10.0] * 15 + [10.0 + 0.5 * i for i in range(15)]
        df = pd.DataFrame({
            "open": closes, "high": closes, "low": closes,
            "close": closes, "volume": [100000] * n,
        }, index=dates)

        mock_client = MockClient.return_value
        mock_client.get_market_data_ex.return_value = {"000001.SZ": df}

        strat = MovingAverageStrategy(config={"short_ma": 5, "long_ma": 20, "top_n": 5})
        signals = strat.generate_signals(date(2025, 6, 1), ["000001.SZ"])

        # 可能有买入或卖出信号
        assert isinstance(signals, list)


class TestGridTradingStrategy:
    @patch("src.data.qmt_client.QMTClient")
    def test_basic(self, MockClient):
        from src.strategy.rules.grid_trading import GridTradingStrategy

        # 价格接近低点
        n = 65
        dates = pd.date_range("2025-01-01", periods=n, freq="B")
        closes = [10 + 2 * np.sin(i / 5) for i in range(n)]
        closes[-1] = min(closes[-60:]) + 0.1
        df = pd.DataFrame({
            "open": closes, "high": [c + 0.3 for c in closes],
            "low": [c - 0.3 for c in closes], "close": closes,
            "volume": [100000] * n,
        }, index=dates)

        mock_client = MockClient.return_value
        mock_client.get_market_data_ex.return_value = {"000001.SZ": df}

        strat = GridTradingStrategy(config={"grid_pct": 5.0, "lookback_days": 60, "top_n": 5})
        signals = strat.generate_signals(date(2025, 6, 1), ["000001.SZ"])

        assert isinstance(signals, list)


class TestCBDualLowStrategy:
    @patch("src.data.qmt_client.QMTClient")
    def test_basic(self, MockClient):
        from src.strategy.rules.cb_dual_low import CBDualLowStrategy

        mock_client = MockClient.return_value
        mock_client.get_cb_info.return_value = {
            "bondName": "测试转债",
            "analConvpremiumratio": 15.0,
            "level": "AA",
        }
        df = pd.DataFrame({
            "close": [105.0],
        }, index=pd.DatetimeIndex(["2025-06-01"]))
        mock_client.get_market_data_ex.return_value = {"123001.SZ": df}

        strat = CBDualLowStrategy(config={"max_price": 130, "max_premium": 50, "top_n": 5})
        signals = strat.generate_signals(date(2025, 6, 1), ["123001.SZ"])

        assert len(signals) == 1
        assert signals[0].direction == "buy"
        assert "双低" in signals[0].reason


class TestLowVolDividendStrategy:
    @patch("src.data.qmt_client.QMTClient")
    def test_basic(self, MockClient):
        from src.strategy.rules.low_vol_dividend import LowVolDividendStrategy

        df = _make_price_df(65, 10.0, 0.001)

        mock_client = MockClient.return_value
        mock_client.get_market_data_ex.return_value = {"000001.SZ": df}

        with patch("src.common.db.get_session") as mock_sess:
            mock_stock = MagicMock()
            mock_stock.code = "000001.SZ"
            mock_stock.pe_ttm = 8.0
            mock_query = MagicMock()
            mock_query.filter.return_value.all.return_value = [mock_stock]
            mock_sess.return_value.__enter__.return_value.query.return_value = mock_query

            strat = LowVolDividendStrategy(config={
                "lookback_days": 60, "min_dividend_yield": 1.0, "top_n": 5,
            })
            signals = strat.generate_signals(date(2025, 6, 1), ["000001.SZ"])

        assert isinstance(signals, list)
