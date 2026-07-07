"""Tests for src/common/asset_types.py — extracted from strategy.trading_rules"""

from src.common.asset_types import AssetType, infer_asset_type, _classify_etf


class TestAssetTypeEnum:
    def test_all_values_are_strings(self):
        for member in AssetType:
            assert isinstance(member.value, str)

    def test_main_board(self):
        assert infer_asset_type("600519.SH") == AssetType.A_STOCK_MAIN
        assert infer_asset_type("000001.SZ") == AssetType.A_STOCK_MAIN

    def test_star_market(self):
        assert infer_asset_type("688001.SH") == AssetType.A_STOCK_STAR
        assert infer_asset_type("689009.SH") == AssetType.A_STOCK_STAR

    def test_gem_board(self):
        assert infer_asset_type("300750.SZ") == AssetType.A_STOCK_GEM
        assert infer_asset_type("301001.SZ") == AssetType.A_STOCK_GEM

    def test_bse(self):
        assert infer_asset_type("830799.BJ") == AssetType.A_STOCK_BSE

    def test_hk_connect(self):
        assert infer_asset_type("00700.HK") == AssetType.HK_CONNECT

    def test_convertible_bond(self):
        assert infer_asset_type("113050.SH") == AssetType.CONVERTIBLE_BOND
        assert infer_asset_type("123456.SZ") == AssetType.CONVERTIBLE_BOND

    def test_etf_domestic(self):
        result = infer_asset_type("510300.SH")
        assert result in (AssetType.ETF_DOMESTIC, AssetType.ETF_CROSS_BORDER)

    def test_etf_cross_border(self):
        assert _classify_etf("513100.SH") == AssetType.ETF_CROSS_BORDER
