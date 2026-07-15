"""熊市五日偏离策略注册与配置合并。"""
from src.selection.strategies.bear_five_dev import build_configs
from src.selection.strategy import get_strategy, strategy_catalog


class TestBearFiveDevRegistry:
    def test_registered(self):
        cls = get_strategy("bear_five_dev")
        assert cls.strategy_id() == "bear_five_dev"

    def test_in_catalog(self):
        ids = {e["id"] for e in strategy_catalog()}
        assert "bear_five_dev" in ids

    def test_build_configs_defaults(self):
        cfg, rank_cfg, meta = build_configs()
        assert meta["id"] == "bear_five_dev"
        assert cfg.require_ma5_below_long is True
        assert cfg.ma5_below_groups == [[30]]
        assert cfg.require_close_below_ma5 is True
        assert cfg.ma5_below_pct == 5.0
        assert rank_cfg.export_top_n == 50

    def test_build_configs_override_groups(self):
        cfg, _, _ = build_configs({"ma5_below_groups": "20,30|40"})
        assert cfg.ma5_below_groups == [[20, 30], [40]]

    def test_build_configs_override_below_pct(self):
        cfg, _, _ = build_configs({"ma5_below_pct": 8})
        assert cfg.ma5_below_pct == 8.0
