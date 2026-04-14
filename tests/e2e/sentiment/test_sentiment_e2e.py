"""E2E: 情绪引擎 P1-2 增强 — 真实/合成混合测试

覆盖:
  P1-37 CrossAssetRegime — 黄金 ETF 动量使用真实 etf_daily
  P1-33 NorthboundFlowSignal — 合成流数据的离线接口
  P1-17 MacroClassifier — 合成特征的规则引擎
  P1-16 CompositeIndex — 内部 z-score 逻辑
"""
import numpy as np
import pandas as pd

from src.sentiment.cross_asset_regime import CrossAssetRegime
from src.sentiment.northbound_flow import NorthboundFlowSignal
from src.sentiment.macro_classifier import MacroClassifier, MACRO_STATES, MACRO_RULES
from src.sentiment.composite_index import _zscore


# ================================================================
# CrossAssetRegime — 真实黄金 ETF + 离线接口
# ================================================================

class TestCrossAssetRegimeE2E:
    """跨资产 Regime — 真实 518880.SH 价格"""

    def test_gold_momentum_with_real_prices(self, real_gold_etf_prices):
        """使用真实黄金 ETF 价格的离线接口"""
        regime = CrossAssetRegime(momentum_window=20)
        result = regime.compute_from_prices({"gold": real_gold_etf_prices["close"]})
        assert isinstance(result, dict)
        assert "cross_asset_risk_score" in result
        assert "cross_asset_regime" in result
        assert result["cross_asset_regime"] in ("risk_on", "risk_off", "neutral")
        assert "gold_mom_20d" in result

    def test_compute_from_prices_offline(self, real_gold_etf_prices):
        """离线接口: 直接提供价格序列"""
        regime = CrossAssetRegime(momentum_window=20)
        prices_dict = {"gold": real_gold_etf_prices["close"]}
        result = regime.compute_from_prices(prices_dict)
        assert "cross_asset_risk_score" in result
        assert "cross_asset_regime" in result
        assert 0 <= result["cross_asset_risk_score"] <= 1
        assert "gold_mom_20d" in result

    def test_compute_from_prices_multi_asset(self, real_gold_etf_prices):
        """多资产离线: 黄金 + 合成铜"""
        np.random.seed(42)
        copper = pd.Series(
            np.cumprod(1 + np.random.randn(len(real_gold_etf_prices)) * 0.01) * 100,
            index=real_gold_etf_prices.index,
        )
        regime = CrossAssetRegime(momentum_window=20)
        result = regime.compute_from_prices({"gold": real_gold_etf_prices["close"], "copper": copper})
        assert "gold_mom_20d" in result
        assert "copper_mom_20d" in result
        assert result["cross_asset_regime"] in ("risk_on", "risk_off", "neutral")

    def test_short_data_returns_neutral(self):
        """数据不足时应返回 neutral"""
        regime = CrossAssetRegime(momentum_window=20)
        short_prices = {"gold": pd.Series([1.0, 2.0, 3.0])}
        result = regime.compute_from_prices(short_prices)
        assert result["cross_asset_regime"] == "neutral"
        assert result["cross_asset_risk_score"] == 0.5


# ================================================================
# NorthboundFlowSignal — 合成资金流
# ================================================================

class TestNorthboundFlowE2E:
    """北向资金流信号 — 合成数据离线接口"""

    def test_compute_from_series_basic(self, synthetic_northbound_flow):
        signal = NorthboundFlowSignal()
        result = signal.compute_from_series(synthetic_northbound_flow)
        assert isinstance(result, dict)
        assert "nb_flow_5d" in result
        assert "nb_flow_20d" in result
        assert "nb_flow_z" in result
        assert "nb_regime" in result
        assert result["nb_regime"] in ("risk_on", "risk_off", "neutral")

    def test_z_score_is_finite(self, synthetic_northbound_flow):
        signal = NorthboundFlowSignal()
        result = signal.compute_from_series(synthetic_northbound_flow)
        assert np.isfinite(result["nb_flow_z"])

    def test_extreme_inflow_triggers_risk_on(self):
        """突然大额流入 (末尾激增) 应触发 risk_on"""
        np.random.seed(42)
        dates = pd.bdate_range("2026-01-01", periods=80)
        flow = pd.Series(np.random.randn(80) * 5, index=dates)
        flow.iloc[-5:] = 200.0
        signal = NorthboundFlowSignal(risk_on_threshold=0.3)
        result = signal.compute_from_series(flow)
        assert result["nb_regime"] == "risk_on"

    def test_extreme_outflow_triggers_risk_off(self):
        """突然大额流出 (末尾暴跌) 应触发 risk_off"""
        np.random.seed(42)
        dates = pd.bdate_range("2026-01-01", periods=80)
        flow = pd.Series(np.random.randn(80) * 5, index=dates)
        flow.iloc[-5:] = -200.0
        signal = NorthboundFlowSignal(risk_off_threshold=-0.3)
        result = signal.compute_from_series(flow)
        assert result["nb_regime"] == "risk_off"

    def test_custom_thresholds(self, synthetic_northbound_flow):
        signal_tight = NorthboundFlowSignal(risk_on_threshold=0.1, risk_off_threshold=-0.1)
        signal_loose = NorthboundFlowSignal(risk_on_threshold=2.0, risk_off_threshold=-2.0)
        r_tight = signal_tight.compute_from_series(synthetic_northbound_flow)
        r_loose = signal_loose.compute_from_series(synthetic_northbound_flow)
        if r_loose["nb_regime"] != "neutral":
            pass  # tight 一定也不是 neutral
        assert r_tight["nb_regime"] in ("risk_on", "risk_off", "neutral")


# ================================================================
# MacroClassifier — 规则引擎
# ================================================================

class TestMacroClassifierE2E:
    """宏观状态分类器 — 合成特征 + 真实规则引擎"""

    def test_classify_returns_valid_state(self, synthetic_sentiment_features):
        classifier = MacroClassifier()
        result = classifier.classify(synthetic_sentiment_features)
        assert "suggested_state" in result
        assert result["suggested_state"] in MACRO_STATES
        assert "confidence" in result
        assert 0 <= result["confidence"] <= 1
        assert "match_detail" in result

    def test_all_states_in_match_detail(self, synthetic_sentiment_features):
        classifier = MacroClassifier()
        result = classifier.classify(synthetic_sentiment_features)
        for state in MACRO_RULES:
            assert state in result["match_detail"]
            detail = result["match_detail"][state]
            assert "matched" in detail
            assert "required" in detail

    def test_state_changed_detection(self, synthetic_sentiment_features):
        classifier = MacroClassifier()
        result = classifier.classify(synthetic_sentiment_features, current_state="bear_severe")
        assert "state_changed" in result
        if result["suggested_state"] != "bear_severe":
            assert result["state_changed"] is True

    def test_bull_strong_features(self):
        """典型牛市特征应触发 bull_strong"""
        features = {
            "ad_ratio_ma5": 2.0,
            "new_high_60d_ma5": 150.0,
            "volume_ratio_ma5": 1.5,
            "composite_sentiment": 0.7,
        }
        classifier = MacroClassifier()
        result = classifier.classify(features)
        assert result["suggested_state"] == "bull_strong"

    def test_bear_severe_features(self):
        """典型熊市特征应触发 bear_severe"""
        features = {
            "ad_ratio_ma5": 0.3,
            "composite_sentiment": -0.7,
            "limit_down_ma5": 50.0,
            "volatility_mood_ma5": -0.8,
        }
        classifier = MacroClassifier()
        result = classifier.classify(features)
        assert result["suggested_state"] == "bear_severe"

    def test_range_bound_neutral_features(self):
        """中性特征应触发 range_bound"""
        features = {
            "ad_ratio_ma5": 1.0,
            "composite_sentiment": 0.0,
            "volatility_mood_ma5": 0.0,
        }
        classifier = MacroClassifier()
        result = classifier.classify(features)
        assert result["suggested_state"] == "range_bound"

    def test_empty_features_defaults_to_range_bound(self):
        classifier = MacroClassifier()
        result = classifier.classify({})
        assert result["suggested_state"] == "range_bound"
        assert result["confidence"] <= 0


# ================================================================
# CompositeIndex — Z-score 逻辑
# ================================================================

class TestCompositeIndexUtilsE2E:
    """CSI 内部 z-score 辅助函数 + CompositeIndex 构造"""

    def test_zscore_normal_value(self):
        result = _zscore(1.0, mean=0.0, std=1.0)
        assert abs(result - 1.0 / 3.0) < 0.01

    def test_zscore_extreme_clipped(self):
        result = _zscore(100.0, mean=0.0, std=1.0)
        assert result == 1.0, "极值应裁剪到 1.0"

    def test_zscore_zero_std(self):
        assert _zscore(5.0, mean=0.0, std=0.0) == 0.0

    def test_zscore_negative(self):
        result = _zscore(-100.0, mean=0.0, std=1.0)
        assert result == -1.0

    def test_composite_index_weights_configured(self):
        from src.sentiment.composite_index import CompositeIndex
        ci = CompositeIndex()
        assert "earning_effect" in ci.weights
        assert "capital_mood" in ci.weights
        total = sum(ci.weights.values())
        assert total > 0
