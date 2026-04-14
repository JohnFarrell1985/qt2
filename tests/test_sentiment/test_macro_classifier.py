"""Tests for macro state classifier (P1-17)"""
import pytest

from src.sentiment.macro_classifier import MacroClassifier, _check_condition, MACRO_RULES


class TestCheckCondition:
    def test_gte(self):
        assert _check_condition(1.5, ">=", 1.0)
        assert not _check_condition(0.5, ">=", 1.0)

    def test_lte(self):
        assert _check_condition(0.5, "<=", 1.0)
        assert not _check_condition(1.5, "<=", 1.0)

    def test_gt(self):
        assert _check_condition(1.1, ">", 1.0)
        assert not _check_condition(1.0, ">", 1.0)

    def test_between(self):
        assert _check_condition(1.0, "between", (0.5, 1.5))
        assert not _check_condition(2.0, "between", (0.5, 1.5))

    def test_none_value(self):
        assert not _check_condition(None, ">=", 1.0)

    def test_nan_value(self):
        import math
        assert not _check_condition(math.nan, ">=", 1.0)


class TestMacroClassifier:
    @pytest.fixture()
    def classifier(self):
        return MacroClassifier()

    def test_bull_strong(self, classifier):
        features = {
            "ad_ratio_ma5": 2.0,
            "new_high_60d_ma5": 100,
            "volume_ratio_ma5": 1.5,
            "composite_sentiment": 0.7,
        }
        result = classifier.classify(features)
        assert result["suggested_state"] == "bull_strong"
        assert result["confidence"] > 0

    def test_bear_severe(self, classifier):
        features = {
            "ad_ratio_ma5": 0.3,
            "composite_sentiment": -0.7,
            "limit_down_ma5": 30,
            "volatility_mood_ma5": -0.8,
        }
        result = classifier.classify(features)
        assert result["suggested_state"] == "bear_severe"

    def test_range_bound(self, classifier):
        features = {
            "ad_ratio_ma5": 1.0,
            "composite_sentiment": 0.0,
            "volatility_mood_ma5": -0.1,
        }
        result = classifier.classify(features)
        assert result["suggested_state"] == "range_bound"

    def test_state_change_detection(self, classifier):
        features = {
            "ad_ratio_ma5": 2.0,
            "new_high_60d_ma5": 100,
            "volume_ratio_ma5": 1.5,
            "composite_sentiment": 0.7,
        }
        result = classifier.classify(features, current_state="bear_severe")
        assert result["state_changed"] is True

    def test_no_state_change(self, classifier):
        features = {
            "ad_ratio_ma5": 2.0,
            "new_high_60d_ma5": 100,
            "volume_ratio_ma5": 1.5,
            "composite_sentiment": 0.7,
        }
        result = classifier.classify(features, current_state="bull_strong")
        assert result["state_changed"] is False

    def test_result_structure(self, classifier):
        result = classifier.classify({})
        assert "suggested_state" in result
        assert "confidence" in result
        assert "match_detail" in result
        assert "state_changed" in result
        assert "recommendation" in result
        for state in MACRO_RULES:
            assert state in result["match_detail"]

    def test_empty_features_defaults_to_range_bound(self, classifier):
        result = classifier.classify({})
        assert result["suggested_state"] == "range_bound"
