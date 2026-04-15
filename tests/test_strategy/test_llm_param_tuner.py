"""Tests for src/strategy/llm_param_tuner.py — LLMParamTuner."""
import pytest
from unittest.mock import MagicMock

from src.strategy.llm_param_tuner import LLMParamTuner


EXPECTED_PARAM_KEYS = {"kelly_fraction", "max_position_pct", "momentum_lookback", "stop_loss_pct"}


@pytest.fixture
def bullish_sentiment():
    return {"composite_sentiment": 0.5, "earning_effect": 0.3}


@pytest.fixture
def bearish_sentiment():
    return {"composite_sentiment": -0.5, "earning_effect": -0.2}


@pytest.fixture
def neutral_sentiment():
    return {"composite_sentiment": 0.0}


@pytest.fixture
def market_stats():
    return {"volatility_20d": 0.18}


class TestRuleSuggest:
    @pytest.mark.timeout(30)
    def test_bullish_params(self, bullish_sentiment, market_stats):
        result = LLMParamTuner._rule_suggest(bullish_sentiment, market_stats)
        assert set(result.keys()) == EXPECTED_PARAM_KEYS
        assert result["kelly_fraction"] == 0.4
        assert result["max_position_pct"] == 0.8

    @pytest.mark.timeout(30)
    def test_bearish_params(self, bearish_sentiment, market_stats):
        result = LLMParamTuner._rule_suggest(bearish_sentiment, market_stats)
        assert result["kelly_fraction"] == 0.15
        assert result["max_position_pct"] == 0.4
        assert result["stop_loss_pct"] == 0.05

    @pytest.mark.timeout(30)
    def test_neutral_params(self, neutral_sentiment, market_stats):
        result = LLMParamTuner._rule_suggest(neutral_sentiment, market_stats)
        assert result["kelly_fraction"] == 0.25
        assert result["momentum_lookback"] == 30

    @pytest.mark.timeout(30)
    def test_missing_composite_sentiment(self, market_stats):
        result = LLMParamTuner._rule_suggest({}, market_stats)
        assert result["kelly_fraction"] == 0.25


class TestSuggestParams:
    @pytest.mark.timeout(30)
    def test_no_llm_uses_rules(self, neutral_sentiment, market_stats):
        tuner = LLMParamTuner(llm_client=None)
        result = tuner.suggest_params(neutral_sentiment, market_stats)
        assert isinstance(result, dict)
        assert set(result.keys()) == EXPECTED_PARAM_KEYS

    @pytest.mark.timeout(30)
    def test_llm_success(self, neutral_sentiment, market_stats):
        mock_llm = MagicMock()
        mock_llm.extract.return_value = {
            "kelly_fraction": 0.35,
            "max_position_pct": 0.7,
            "momentum_lookback": 25,
            "stop_loss_pct": 0.06,
        }
        tuner = LLMParamTuner(llm_client=mock_llm)
        result = tuner.suggest_params(neutral_sentiment, market_stats)
        assert result["kelly_fraction"] == 0.35
        mock_llm.extract.assert_called_once()

    @pytest.mark.timeout(30)
    def test_llm_failure_falls_back(self, bullish_sentiment, market_stats):
        mock_llm = MagicMock()
        mock_llm.extract.side_effect = RuntimeError("API timeout")
        tuner = LLMParamTuner(llm_client=mock_llm)
        result = tuner.suggest_params(bullish_sentiment, market_stats)
        assert result["kelly_fraction"] == 0.4

    @pytest.mark.timeout(30)
    def test_missing_llm_client_no_crash(self, neutral_sentiment, market_stats):
        tuner = LLMParamTuner()
        result = tuner.suggest_params(neutral_sentiment, market_stats)
        assert isinstance(result, dict)
        assert len(result) == 4


class TestValidateParams:
    @pytest.mark.timeout(30)
    def test_clamps_values(self):
        raw = {
            "kelly_fraction": 0.01,
            "max_position_pct": 2.0,
            "momentum_lookback": 5,
            "stop_loss_pct": 0.20,
        }
        result = LLMParamTuner._validate_params(raw)
        assert result["kelly_fraction"] == 0.1
        assert result["max_position_pct"] == 1.0
        assert result["momentum_lookback"] == 10
        assert result["stop_loss_pct"] == 0.10

    @pytest.mark.timeout(30)
    def test_keeps_valid_values(self):
        raw = {"kelly_fraction": 0.3, "stop_loss_pct": 0.07}
        result = LLMParamTuner._validate_params(raw)
        assert result["kelly_fraction"] == 0.3
        assert result["stop_loss_pct"] == 0.07

    @pytest.mark.timeout(30)
    def test_ignores_unknown_keys(self):
        raw = {"unknown_param": 42, "kelly_fraction": 0.25}
        result = LLMParamTuner._validate_params(raw)
        assert "unknown_param" not in result
        assert result["kelly_fraction"] == 0.25
