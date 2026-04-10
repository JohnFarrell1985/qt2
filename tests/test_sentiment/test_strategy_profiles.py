"""Tests for src/sentiment/strategy_profiles.py"""
import json
from unittest.mock import patch

from src.sentiment.strategy_profiles import (
    load_profiles,
    get_strategy_config,
    is_strategy_disabled,
    list_active_strategies,
)


SAMPLE_PROFILES = {
    "momentum": {
        "bull_strong": {"top_n": 5, "hold_days": 3},
        "bear_strong": None,
        "shock": {"top_n": 3},
    },
    "mean_revert": {
        "bull_strong": {"zscore_threshold": -2.0},
        "bear_strong": {"zscore_threshold": -1.5},
    },
    "_comment": "this should be filtered out",
}


class TestLoadProfiles:
    def test_load_from_tmp_file(self, tmp_path):
        filepath = tmp_path / "strategy_profiles.json"
        filepath.write_text(json.dumps(SAMPLE_PROFILES), encoding="utf-8")

        result = load_profiles(path=filepath)
        assert "momentum" in result
        assert "mean_revert" in result
        assert "_comment" not in result

    def test_returns_empty_when_file_missing(self, tmp_path):
        filepath = tmp_path / "nonexistent.json"
        result = load_profiles(path=filepath)
        assert result == {}


class TestGetStrategyConfig:
    def test_known_strategy_and_state(self):
        profiles = {k: v for k, v in SAMPLE_PROFILES.items() if not k.startswith("_")}
        result = get_strategy_config("momentum", "bull_strong", profiles=profiles)
        assert result == {"top_n": 5, "hold_days": 3}

    def test_returns_empty_for_unknown_strategy(self):
        profiles = {k: v for k, v in SAMPLE_PROFILES.items() if not k.startswith("_")}
        result = get_strategy_config("nonexistent", "bull_strong", profiles=profiles)
        assert result == {}

    def test_returns_empty_for_unknown_state(self):
        profiles = {k: v for k, v in SAMPLE_PROFILES.items() if not k.startswith("_")}
        result = get_strategy_config("momentum", "unknown_state", profiles=profiles)
        assert result == {}

    def test_returns_empty_for_null_entry(self):
        profiles = {k: v for k, v in SAMPLE_PROFILES.items() if not k.startswith("_")}
        result = get_strategy_config("momentum", "bear_strong", profiles=profiles)
        assert result == {}


class TestIsStrategyDisabled:
    def test_disabled_when_null(self):
        profiles = {k: v for k, v in SAMPLE_PROFILES.items() if not k.startswith("_")}
        assert is_strategy_disabled("momentum", "bear_strong", profiles=profiles) is True

    def test_not_disabled_when_config_exists(self):
        profiles = {k: v for k, v in SAMPLE_PROFILES.items() if not k.startswith("_")}
        assert is_strategy_disabled("momentum", "bull_strong", profiles=profiles) is False

    def test_not_disabled_when_strategy_unknown(self):
        profiles = {k: v for k, v in SAMPLE_PROFILES.items() if not k.startswith("_")}
        assert is_strategy_disabled("nonexistent", "bull_strong", profiles=profiles) is False

    def test_not_disabled_when_state_missing(self):
        profiles = {k: v for k, v in SAMPLE_PROFILES.items() if not k.startswith("_")}
        assert is_strategy_disabled("momentum", "unknown_state", profiles=profiles) is False


class TestListActiveStrategies:
    @patch("src.sentiment.strategy_profiles.load_profiles")
    def test_lists_active(self, mock_load):
        mock_load.return_value = {
            "momentum": {
                "bull_strong": {"top_n": 5},
                "bear_strong": None,
            },
            "mean_revert": {
                "bull_strong": {"zscore": -2.0},
            },
        }
        active = list_active_strategies("bull_strong")
        assert "momentum" in active
        assert "mean_revert" in active

    @patch("src.sentiment.strategy_profiles.load_profiles")
    def test_excludes_disabled(self, mock_load):
        mock_load.return_value = {
            "momentum": {
                "bear_strong": None,
            },
            "mean_revert": {
                "bear_strong": {"zscore": -1.5},
            },
        }
        active = list_active_strategies("bear_strong")
        assert "momentum" not in active
        assert "mean_revert" in active

    @patch("src.sentiment.strategy_profiles.load_profiles")
    def test_includes_strategy_without_state_key(self, mock_load):
        mock_load.return_value = {
            "momentum": {"bull_strong": {"top_n": 5}},
            "value": {},
        }
        active = list_active_strategies("shock")
        assert "momentum" in active
        assert "value" in active
