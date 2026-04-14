"""Tests for src/strategy/trading_rules.py"""
import pytest

from src.strategy.trading_rules import (
    AssetType,
    TRADING_RULES,
    infer_asset_type,
    get_trading_rule,
    _classify_etf,
)


class TestAssetType:
    def test_enum_values(self):
        assert AssetType.A_STOCK_MAIN == "a_stock_main"
        assert AssetType.CONVERTIBLE_BOND == "cb"
        assert len(AssetType) == 10

    def test_is_str_enum(self):
        assert isinstance(AssetType.A_STOCK_MAIN, str)


class TestTradingRules:
    def test_all_asset_types_have_rules(self):
        for at in AssetType:
            assert at in TRADING_RULES, f"Missing rule for {at}"

    def test_frozen_dataclass(self):
        rule = TRADING_RULES[AssetType.A_STOCK_MAIN]
        with pytest.raises(AttributeError):
            rule.t_plus_n = 0

    def test_a_stock_main_rule(self):
        r = TRADING_RULES[AssetType.A_STOCK_MAIN]
        assert r.t_plus_n == 1
        assert r.price_limit_pct == 0.10
        assert r.stamp_tax_rate == 0.0005
        assert r.min_lot_size == 100
        assert r.can_short is False

    def test_star_board_rule(self):
        r = TRADING_RULES[AssetType.A_STOCK_STAR]
        assert r.t_plus_n == 1
        assert r.price_limit_pct == 0.20
        assert r.min_lot_size == 200

    def test_gem_board_rule(self):
        r = TRADING_RULES[AssetType.A_STOCK_GEM]
        assert r.price_limit_pct == 0.20
        assert r.min_lot_size == 100

    def test_bse_board_rule(self):
        r = TRADING_RULES[AssetType.A_STOCK_BSE]
        assert r.price_limit_pct == 0.30

    def test_hk_connect_t0(self):
        r = TRADING_RULES[AssetType.HK_CONNECT]
        assert r.t_plus_n == 0
        assert r.price_limit_pct is None

    def test_cb_t0(self):
        r = TRADING_RULES[AssetType.CONVERTIBLE_BOND]
        assert r.t_plus_n == 0
        assert r.stamp_tax_rate == 0.0
        assert r.min_lot_size == 10

    def test_etf_cross_border_t0(self):
        r = TRADING_RULES[AssetType.ETF_CROSS_BORDER]
        assert r.t_plus_n == 0

    def test_etf_domestic_t1(self):
        r = TRADING_RULES[AssetType.ETF_DOMESTIC]
        assert r.t_plus_n == 1

    def test_margin_short_can_short(self):
        r = TRADING_RULES[AssetType.MARGIN_SHORT]
        assert r.can_short is True
        assert r.margin_ratio is not None


class TestInferAssetType:
    @pytest.mark.parametrize("code,expected", [
        ("000001.SZ", AssetType.A_STOCK_MAIN),
        ("600000.SH", AssetType.A_STOCK_MAIN),
        ("601398.SH", AssetType.A_STOCK_MAIN),
        ("002230.SZ", AssetType.A_STOCK_MAIN),
    ])
    def test_main_board(self, code, expected):
        assert infer_asset_type(code) == expected

    @pytest.mark.parametrize("code,expected", [
        ("688001.SH", AssetType.A_STOCK_STAR),
        ("689009.SH", AssetType.A_STOCK_STAR),
    ])
    def test_star_board(self, code, expected):
        assert infer_asset_type(code) == expected

    @pytest.mark.parametrize("code,expected", [
        ("300001.SZ", AssetType.A_STOCK_GEM),
        ("301001.SZ", AssetType.A_STOCK_GEM),
    ])
    def test_gem_board(self, code, expected):
        assert infer_asset_type(code) == expected

    @pytest.mark.parametrize("code,expected", [
        ("830001.BJ", AssetType.A_STOCK_BSE),
        ("430001.BJ", AssetType.A_STOCK_BSE),
    ])
    def test_bse_board(self, code, expected):
        assert infer_asset_type(code) == expected

    def test_hk_connect(self):
        assert infer_asset_type("00700.HK") == AssetType.HK_CONNECT

    @pytest.mark.parametrize("code,expected", [
        ("110001.SH", AssetType.CONVERTIBLE_BOND),
        ("123456.SZ", AssetType.CONVERTIBLE_BOND),
    ])
    def test_convertible_bond(self, code, expected):
        assert infer_asset_type(code) == expected

    def test_etf_domestic(self):
        assert infer_asset_type("510300.SH") == AssetType.ETF_DOMESTIC

    def test_etf_cross_border(self):
        assert infer_asset_type("513100.SH") == AssetType.ETF_CROSS_BORDER

    def test_588_etf(self):
        result = infer_asset_type("588000.SH")
        assert result in (AssetType.ETF_DOMESTIC, AssetType.ETF_CROSS_BORDER)


class TestGetTradingRule:
    def test_returns_correct_rule(self):
        rule = get_trading_rule("688001.SH")
        assert rule.asset_type == AssetType.A_STOCK_STAR
        assert rule.min_lot_size == 200

    def test_cb_rule(self):
        rule = get_trading_rule("110001.SH")
        assert rule.t_plus_n == 0


class TestClassifyEtf:
    def test_cross_border_513(self):
        assert _classify_etf("513100.SH") == AssetType.ETF_CROSS_BORDER

    def test_domestic_510(self):
        assert _classify_etf("510300.SH") == AssetType.ETF_DOMESTIC
