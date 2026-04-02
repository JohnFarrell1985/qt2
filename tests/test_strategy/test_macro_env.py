"""Tests for src/strategy/macro_env.py

Uses a temporary JSON config file to avoid filesystem side effects.
"""
import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

SAMPLE_CONFIG = {
    "states": {
        "bull": {
            "label": "牛市",
            "description": "大盘上涨趋势",
            "position_multiplier": 1.2,
            "preferred_strategies": ["momentum", "growth"],
            "avoid_strategies": ["defensive"],
            "indicators": {"ma20_trend": "up"},
        },
        "bear": {
            "label": "熊市",
            "description": "大盘下跌趋势",
            "position_multiplier": 0.5,
            "preferred_strategies": ["defensive"],
            "avoid_strategies": ["momentum"],
            "indicators": {"ma20_trend": "down"},
        },
        "range_bound": {
            "label": "震荡市",
            "description": "横盘震荡",
            "position_multiplier": 0.8,
            "preferred_strategies": ["value"],
            "avoid_strategies": [],
            "indicators": {},
        },
    },
    "current_state": "range_bound",
}


@pytest.fixture
def config_file(tmp_path):
    """Write sample config to a temp file."""
    p = tmp_path / "macro_env.json"
    p.write_text(json.dumps(SAMPLE_CONFIG, ensure_ascii=False), encoding="utf-8")
    return str(p)


@pytest.fixture
def macro(config_file):
    with patch("src.strategy.macro_env.get_session") as mock_gs:
        session = MagicMock()
        session.__enter__ = MagicMock(return_value=session)
        session.__exit__ = MagicMock(return_value=False)
        mock_gs.return_value = session

        from src.strategy.macro_env import MacroEnvironment
        yield MacroEnvironment(config_path=config_file)


class TestInit:

    def test_loads_config(self, macro):
        assert len(macro.get_all_states()) == 3

    def test_missing_config_uses_defaults(self, tmp_path):
        with patch("src.strategy.macro_env.get_session"):
            from src.strategy.macro_env import MacroEnvironment
            env = MacroEnvironment(config_path=str(tmp_path / "nonexistent.json"))
        assert env.get_current_state() == "range_bound"
        assert env.get_all_states() == {}


class TestGetAllStates:

    def test_returns_all(self, macro):
        states = macro.get_all_states()
        assert "bull" in states
        assert "bear" in states
        assert "range_bound" in states


class TestGetCurrentState:

    def test_returns_current(self, macro):
        assert macro.get_current_state() == "range_bound"


class TestGetStateDetail:

    def test_current_state_detail(self, macro):
        detail = macro.get_state_detail()
        assert detail["label"] == "震荡市"

    def test_specific_state_detail(self, macro):
        detail = macro.get_state_detail("bull")
        assert detail["label"] == "牛市"
        assert detail["position_multiplier"] == 1.2

    def test_unknown_state_returns_empty(self, macro):
        assert macro.get_state_detail("apocalypse") == {}


class TestGetPositionMultiplier:

    def test_current(self, macro):
        assert macro.get_position_multiplier() == pytest.approx(0.8)

    def test_specific(self, macro):
        assert macro.get_position_multiplier("bull") == pytest.approx(1.2)

    def test_unknown_returns_default(self, macro):
        assert macro.get_position_multiplier("unknown") == pytest.approx(1.0)


class TestGetPreferredStrategies:

    def test_returns_list(self, macro):
        prefs = macro.get_preferred_strategies("bull")
        assert "momentum" in prefs
        assert "growth" in prefs

    def test_default_is_current_state(self, macro):
        prefs = macro.get_preferred_strategies()
        assert "value" in prefs


class TestGetAvoidStrategies:

    def test_returns_list(self, macro):
        avoid = macro.get_avoid_strategies("bull")
        assert "defensive" in avoid

    def test_empty_list(self, macro):
        avoid = macro.get_avoid_strategies("range_bound")
        assert avoid == []


class TestSetCurrentState:

    def test_valid_state(self, macro):
        macro.set_current_state("bull", determined_by="test")
        assert macro.get_current_state() == "bull"

    def test_invalid_state_raises(self, macro):
        with pytest.raises(ValueError, match="未知宏观状态"):
            macro.set_current_state("apocalypse")

    def test_config_saved(self, macro, config_file):
        macro.set_current_state("bear", determined_by="unit_test")
        reloaded = json.loads(Path(config_file).read_text(encoding="utf-8"))
        assert reloaded["current_state"] == "bear"


class TestGetStrategyMacroMapping:

    def test_mapping(self, macro):
        mapping = macro.get_strategy_macro_mapping()
        assert mapping["bull"] == ["momentum", "growth"]
        assert mapping["bear"] == ["defensive"]
        assert mapping["range_bound"] == ["value"]


class TestSummary:

    def test_summary_fields(self, macro):
        s = macro.summary()
        assert s["current_state"] == "range_bound"
        assert s["label"] == "震荡市"
        assert s["position_multiplier"] == pytest.approx(0.8)
        assert "preferred_strategies" in s
        assert "avoid_strategies" in s
        assert "indicators" in s
