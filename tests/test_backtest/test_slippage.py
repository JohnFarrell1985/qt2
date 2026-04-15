"""Tests for SlippageConfig, SlippageModel, SlippageResult in src/backtest/fees.py"""
from unittest.mock import MagicMock

import pytest

from src.backtest.fees import SlippageConfig, SlippageModel, SlippageResult


# ---- SlippageConfig ----

class TestSlippageConfig:
    @pytest.mark.timeout(30)
    def test_defaults(self):
        cfg = SlippageConfig()
        assert cfg.enabled is False
        assert cfg.fixed_bps == 5.0
        assert cfg.impact_coeff == 0.1
        assert cfg.vol_lookback_days == 20
        assert cfg.asymmetric is True

    @pytest.mark.timeout(30)
    def test_from_settings(self):
        bt_cfg = MagicMock()
        bt_cfg.slippage_enabled = True
        bt_cfg.slippage_fixed_bps = 3.0
        bt_cfg.slippage_impact_coeff = 0.2
        bt_cfg.slippage_vol_lookback = 10
        bt_cfg.slippage_asymmetric = False

        cfg = SlippageConfig.from_settings(bt_cfg)
        assert cfg.enabled is True
        assert cfg.fixed_bps == 3.0
        assert cfg.impact_coeff == 0.2
        assert cfg.vol_lookback_days == 10
        assert cfg.asymmetric is False


# ---- SlippageResult ----

class TestSlippageResult:
    @pytest.mark.timeout(30)
    def test_total(self):
        r = SlippageResult(fixed_cost=10.0, impact_cost=5.0)
        assert r.total == 15.0

    @pytest.mark.timeout(30)
    def test_defaults_zero(self):
        r = SlippageResult()
        assert r.total == 0.0


# ---- SlippageModel disabled ----

class TestSlippageModelDisabled:
    @pytest.mark.timeout(30)
    def test_disabled_returns_zero(self):
        model = SlippageModel(SlippageConfig(enabled=False))
        result = model.estimate(order_value=100_000, daily_volume=1e8, volatility=0.3)
        assert result.fixed_cost == 0.0
        assert result.impact_cost == 0.0
        assert result.total == 0.0

    @pytest.mark.timeout(30)
    def test_zero_order_value_returns_zero(self):
        model = SlippageModel(SlippageConfig(enabled=True))
        result = model.estimate(order_value=0)
        assert result.total == 0.0

    @pytest.mark.timeout(30)
    def test_negative_order_value_returns_zero(self):
        model = SlippageModel(SlippageConfig(enabled=True))
        result = model.estimate(order_value=-100)
        assert result.total == 0.0


# ---- SlippageModel.estimate ----

class TestSlippageModelEstimate:
    @pytest.fixture
    def enabled_model(self):
        cfg = SlippageConfig(
            enabled=True, fixed_bps=5.0, impact_coeff=0.1, asymmetric=True,
        )
        return SlippageModel(cfg)

    @pytest.mark.timeout(30)
    def test_buy_fixed_and_impact(self, enabled_model):
        result = enabled_model.estimate(
            order_value=100_000,
            daily_volume=10_000_000,
            volatility=0.30,
            direction="buy",
        )
        expected_fixed = round(100_000 * 5.0 / 10_000, 2)
        assert result.fixed_cost == expected_fixed

        participation = 100_000 / 10_000_000
        expected_impact = round(0.1 * participation * 0.30 * 100_000, 2)
        assert result.impact_cost == expected_impact
        assert result.total == result.fixed_cost + result.impact_cost

    @pytest.mark.timeout(30)
    def test_sell_asymmetric_bps(self, enabled_model):
        buy_result = enabled_model.estimate(
            order_value=100_000, daily_volume=1e7, volatility=0.3, direction="buy",
        )
        sell_result = enabled_model.estimate(
            order_value=100_000, daily_volume=1e7, volatility=0.3, direction="sell",
        )
        assert sell_result.fixed_cost > buy_result.fixed_cost
        expected_sell_fixed = round(100_000 * (5.0 * 1.2) / 10_000, 2)
        assert sell_result.fixed_cost == expected_sell_fixed

    @pytest.mark.timeout(30)
    def test_no_asymmetric(self):
        cfg = SlippageConfig(enabled=True, fixed_bps=5.0, asymmetric=False)
        model = SlippageModel(cfg)
        buy = model.estimate(order_value=100_000, direction="buy")
        sell = model.estimate(order_value=100_000, direction="sell")
        assert buy.fixed_cost == sell.fixed_cost

    @pytest.mark.timeout(30)
    def test_zero_daily_volume_no_impact(self, enabled_model):
        result = enabled_model.estimate(
            order_value=100_000, daily_volume=0.0, volatility=0.3,
        )
        assert result.impact_cost == 0.0
        assert result.fixed_cost > 0

    @pytest.mark.timeout(30)
    def test_zero_volatility_no_impact(self, enabled_model):
        result = enabled_model.estimate(
            order_value=100_000, daily_volume=1e8, volatility=0.0,
        )
        assert result.impact_cost == 0.0
        assert result.fixed_cost > 0


# ---- SlippageModel.adjust_price ----

class TestSlippageModelAdjustPrice:
    @pytest.fixture
    def model(self):
        cfg = SlippageConfig(enabled=True, fixed_bps=10.0, impact_coeff=0.1, asymmetric=False)
        return SlippageModel(cfg)

    @pytest.mark.timeout(30)
    def test_buy_price_increases(self, model):
        adjusted = model.adjust_price(
            price=10.0, order_value=100_000, daily_volume=1e7, volatility=0.3, direction="buy",
        )
        assert adjusted > 10.0

    @pytest.mark.timeout(30)
    def test_sell_price_decreases(self, model):
        adjusted = model.adjust_price(
            price=10.0, order_value=100_000, daily_volume=1e7, volatility=0.3, direction="sell",
        )
        assert adjusted < 10.0

    @pytest.mark.timeout(30)
    def test_disabled_returns_original(self):
        model = SlippageModel(SlippageConfig(enabled=False))
        adjusted = model.adjust_price(price=10.0, order_value=100_000, direction="buy")
        assert adjusted == 10.0
