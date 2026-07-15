"""Tests for JSON config loading and strategy presets."""

import json

import pytest

from src.common.config import (
    APP_JSON_PATH,
    MaFilterConfig,
    apply_strategy,
    get_strategy_meta,
    list_strategies,
    load_json_config,
    load_strategy,
    settings,
)


class TestLoadJsonConfig:
    def test_load_valid_json(self, tmp_path):
        path = tmp_path / "test.json"
        path.write_text(json.dumps({"section": {"key": "value"}}), encoding="utf-8")
        result = load_json_config(path)
        assert result["section"]["key"] == "value"

    def test_missing_file_returns_empty(self, tmp_path):
        assert load_json_config(tmp_path / "missing.json") == {}


class TestStrategyPresets:
    def test_list_strategies(self):
        names = list_strategies()
        assert "bull_launch" in names
        assert "bear_rebound" in names
        assert "bear_five_dev" in names
        assert "bear_five_dev" in names

    def test_load_bull_launch(self):
        data = load_strategy("bull_launch")
        assert data["id"] == "bull_launch"
        assert data["ma_filter"]["anchor_ma_period"] == 5

    def test_apply_bull_launch(self):
        apply_strategy("bull_launch")
        mf = settings.selection.ma_filter
        assert mf.filter_periods == [5, 10, 20, 50]
        assert mf.ma5_proximity_pct == 3.0
        meta = get_strategy_meta()
        assert meta["id"] == "bull_launch"
        assert meta["label"] == "牛市启动突破"

    def test_apply_bear_rebound(self):
        apply_strategy("bear_rebound")
        mf = settings.selection.ma_filter
        assert mf.filter_periods == [20, 30, 40, 50, 60]
        assert mf.anchor_ma_period == 20
        assert mf.ma5_proximity_pct == 5.0
        assert mf.require_spreading is False
        assert mf.max_gain_total_pct == 35.0
        meta = get_strategy_meta()
        assert meta["id"] == "bear_rebound"

    def test_app_json_exists(self):
        assert APP_JSON_PATH.exists()
        app = load_json_config(APP_JSON_PATH)
        assert app["selection"]["active_strategy"] in list_strategies()

    def test_ma_filter_override(self):
        cfg = MaFilterConfig(filter_periods=[5, 10, 15], _env_file=None)
        assert cfg.filter_periods == [5, 10, 15]

    def test_unknown_strategy_raises(self):
        with pytest.raises(FileNotFoundError):
            load_strategy("nonexistent_strategy")
