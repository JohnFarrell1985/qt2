"""Tests for src/data/universe_provider.py"""
from datetime import date
from unittest.mock import patch, MagicMock

from src.data.universe_provider import (
    AStockUniverseProvider,
    ETFUniverseProvider,
    CBUniverseProvider,
    CompositeUniverseProvider,
    UniverseProvider,
)
from src.strategy.trading_rules import AssetType


class TestAStockUniverseProvider:
    @patch("src.data.universe_manager.UniverseManager")
    def test_get_codes_delegates(self, MockUM):
        mock_mgr = MagicMock()
        mock_mgr.get_tradable.return_value = ["000001.SZ", "600000.SH"]
        MockUM.return_value = mock_mgr

        provider = AStockUniverseProvider()
        codes = provider.get_codes(date(2025, 6, 1))
        assert codes == ["000001.SZ", "600000.SH"]
        mock_mgr.get_tradable.assert_called_once_with(date(2025, 6, 1), True, True)

    @patch("src.data.universe_manager.UniverseManager")
    def test_get_codes_passes_filters(self, MockUM):
        mock_mgr = MagicMock()
        mock_mgr.get_tradable.return_value = []
        MockUM.return_value = mock_mgr

        provider = AStockUniverseProvider()
        provider.get_codes(date(2025, 6, 1), exclude_st=False)
        mock_mgr.get_tradable.assert_called_once_with(date(2025, 6, 1), False, True)

    def test_get_asset_type(self):
        provider = AStockUniverseProvider.__new__(AStockUniverseProvider)
        assert provider.get_asset_type("688001.SH") == AssetType.A_STOCK_STAR
        assert provider.get_asset_type("000001.SZ") == AssetType.A_STOCK_MAIN


class TestETFUniverseProvider:
    @patch("src.strategy.instrument_pool.InstrumentPoolManager")
    def test_get_codes(self, MockIPM):
        mock_mgr = MagicMock()
        mock_mgr.get_pool_codes.return_value = ["510300.SH", "159919.SZ"]
        MockIPM.return_value = mock_mgr

        provider = ETFUniverseProvider()
        codes = provider.get_codes(date(2025, 6, 1))
        assert "510300.SH" in codes
        mock_mgr.get_pool_codes.assert_called_once_with("ETF基金")

    def test_get_asset_type(self):
        provider = ETFUniverseProvider.__new__(ETFUniverseProvider)
        assert provider.get_asset_type("510300.SH") == AssetType.ETF_DOMESTIC


class TestCBUniverseProvider:
    def test_get_asset_type_always_cb(self):
        provider = CBUniverseProvider.__new__(CBUniverseProvider)
        assert provider.get_asset_type("110001.SH") == AssetType.CONVERTIBLE_BOND
        assert provider.get_asset_type("anything") == AssetType.CONVERTIBLE_BOND


class TestCompositeUniverseProvider:
    def test_register_and_get_provider(self):
        comp = CompositeUniverseProvider()
        mock_provider = MagicMock(spec=UniverseProvider)
        comp.register(AssetType.A_STOCK_MAIN, mock_provider)
        assert comp.get_provider(AssetType.A_STOCK_MAIN) is mock_provider
        assert comp.get_provider(AssetType.HK_CONNECT) is None

    def test_get_codes_merges_all(self):
        comp = CompositeUniverseProvider()
        p1 = MagicMock(spec=UniverseProvider)
        p1.get_codes.return_value = ["000001.SZ", "000002.SZ"]
        p2 = MagicMock(spec=UniverseProvider)
        p2.get_codes.return_value = ["510300.SH"]

        comp.register(AssetType.A_STOCK_MAIN, p1)
        comp.register(AssetType.ETF_DOMESTIC, p2)

        codes = comp.get_codes(date(2025, 6, 1))
        assert len(codes) == 3
        assert "510300.SH" in codes

    def test_get_codes_filters_by_asset_types(self):
        comp = CompositeUniverseProvider()
        p1 = MagicMock(spec=UniverseProvider)
        p1.get_codes.return_value = ["000001.SZ"]
        p2 = MagicMock(spec=UniverseProvider)
        p2.get_codes.return_value = ["510300.SH"]

        comp.register(AssetType.A_STOCK_MAIN, p1)
        comp.register(AssetType.ETF_DOMESTIC, p2)

        codes = comp.get_codes(
            date(2025, 6, 1), asset_types=[AssetType.ETF_DOMESTIC]
        )
        assert codes == ["510300.SH"]
        p1.get_codes.assert_not_called()

    def test_get_codes_deduplicates(self):
        comp = CompositeUniverseProvider()
        p1 = MagicMock(spec=UniverseProvider)
        p1.get_codes.return_value = ["000001.SZ"]
        p2 = MagicMock(spec=UniverseProvider)
        p2.get_codes.return_value = ["000001.SZ"]

        comp.register(AssetType.A_STOCK_MAIN, p1)
        comp.register(AssetType.A_STOCK_GEM, p2)

        codes = comp.get_codes(date(2025, 6, 1))
        assert codes == ["000001.SZ"]

    def test_get_asset_type(self):
        comp = CompositeUniverseProvider()
        assert comp.get_asset_type("688001.SH") == AssetType.A_STOCK_STAR
