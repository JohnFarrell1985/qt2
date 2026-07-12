"""Tests for src/trading/market_rules.py"""
import pytest

from src.trading import market_rules as mr
from src.trading.market_rules import Board, Exchange


class TestNormalizeCode:

    @pytest.mark.parametrize("raw,expected", [
        ("600519", "600519.SH"),        # 沪市主板
        ("600519.SH", "600519.SH"),
        ("sh600519", "600519.SH"),
        ("600519.XSHG", "600519.SH"),
        ("000001", "000001.SZ"),        # 深市主板
        ("000001.SZ", "000001.SZ"),
        ("sz000001", "000001.SZ"),
        ("002415", "002415.SZ"),        # 中小板
        ("300750", "300750.SZ"),        # 创业板
        ("301000", "301000.SZ"),
        ("688981", "688981.SH"),        # 科创板
        ("689009", "689009.SH"),
        ("830799", "830799.BJ"),        # 北交所
        ("430047", "430047.BJ"),
        ("920819", "920819.BJ"),        # 北交所 920 段
        ("510300", "510300.SH"),        # 沪市 ETF
        ("159915", "159915.SZ"),        # 深市 ETF
        ("113050", "113050.SH"),        # 沪市可转债
        ("128036", "128036.SZ"),        # 深市可转债
        ("00700", "00700.HK"),          # 港股通
        ("700.HK", "00700.HK"),
        ("hk00700", "00700.HK"),
        ("00700.XHKG", "00700.HK"),
    ])
    def test_normalize(self, raw, expected):
        assert mr.normalize_qmt_code(raw) == expected

    def test_unknown_passthrough(self):
        assert mr.normalize_qmt_code("ABCDEF") == "ABCDEF"


class TestExchange:

    @pytest.mark.parametrize("code,exch", [
        ("600519", Exchange.SH),
        ("688981", Exchange.SH),
        ("000001", Exchange.SZ),
        ("300750", Exchange.SZ),
        ("830799", Exchange.BJ),
        ("920819", Exchange.BJ),
        ("00700.HK", Exchange.HK),
        ("113050", Exchange.SH),
        ("128036", Exchange.SZ),
    ])
    def test_infer_exchange(self, code, exch):
        assert mr.infer_exchange(code) == exch


class TestBoard:

    @pytest.mark.parametrize("code,board", [
        ("600519.SH", Board.MAIN_SH),
        ("000001.SZ", Board.MAIN_SZ),
        ("002415.SZ", Board.SME),
        ("300750.SZ", Board.GEM),
        ("688981.SH", Board.STAR),
        ("830799.BJ", Board.BSE),
        ("00700.HK", Board.HK_CONNECT),
        ("510300.SH", Board.FUND),
        ("128036.SZ", Board.BOND),
    ])
    def test_infer_board(self, code, board):
        assert mr.infer_board(code) == board


class TestQuantityRules:

    def test_main_board_buy_multiple_of_100(self):
        assert mr.normalize_quantity("600519.SH", 150, "buy") == 100
        assert mr.normalize_quantity("600519.SH", 250, "buy") == 200
        assert mr.normalize_quantity("600519.SH", 50, "buy") == 100  # 抬升至下限

    def test_star_board_min_200(self):
        assert mr.normalize_quantity("688981.SH", 100, "buy") == 200
        assert mr.normalize_quantity("688981.SH", 250, "buy") == 250  # 1 股递增
        assert mr.normalize_quantity("688981.SH", 201, "buy") == 201

    def test_gem_board_min_100_step_1(self):
        assert mr.normalize_quantity("300750.SZ", 50, "buy") == 100
        assert mr.normalize_quantity("300750.SZ", 150, "buy") == 150

    def test_bse_board_min_100_step_1(self):
        assert mr.normalize_quantity("830799.BJ", 50, "buy") == 100
        assert mr.normalize_quantity("830799.BJ", 133, "buy") == 133

    def test_bond_min_10(self):
        assert mr.normalize_quantity("128036.SZ", 5, "buy") == 10
        assert mr.normalize_quantity("128036.SZ", 25, "buy") == 20

    def test_hk_passthrough(self):
        assert mr.normalize_quantity("00700.HK", 500, "buy") == 500

    def test_sell_allows_odd_lot(self):
        assert mr.normalize_quantity("600519.SH", 150, "sell") == 150
        assert mr.normalize_quantity("688981.SH", 99, "sell") == 99

    def test_zero_or_negative(self):
        assert mr.normalize_quantity("600519.SH", 0, "buy") == 0
        assert mr.normalize_quantity("600519.SH", -10, "buy") == 0


class TestPriceRules:

    def test_stock_two_decimals(self):
        assert mr.normalize_price("600519.SH", 1800.123) == 1800.12

    def test_fund_bond_three_decimals(self):
        assert mr.normalize_price("510300.SH", 4.1234) == 4.123
        assert mr.normalize_price("128036.SZ", 120.5678) == 120.568

    def test_market_price_passthrough(self):
        assert mr.normalize_price("600519.SH", 0) == 0


class TestMarketOrderRouting:

    def test_supports_market_order(self):
        assert mr.supports_market_order("600519.SH") is True
        assert mr.supports_market_order("300750.SZ") is True
        assert mr.supports_market_order("00700.HK") is False

    def test_market_alias_a_share(self):
        assert mr.market_price_type_alias("600519.SH") == "MARKET_PEER_PRICE_FIRST"
        assert mr.market_price_type_alias("000001.SZ") == "MARKET_PEER_PRICE_FIRST"
        assert mr.market_price_type_alias("830799.BJ") == "MARKET_PEER_PRICE_FIRST"

    def test_market_alias_hk_falls_back_to_limit(self):
        assert mr.market_price_type_alias("00700.HK") == "FIX_PRICE"


class TestPriceLimitPct:

    @pytest.mark.parametrize("code,pct", [
        ("600519.SH", 10.0),
        ("300750.SZ", 20.0),
        ("688981.SH", 20.0),
        ("830799.BJ", 30.0),
        ("00700.HK", 0.0),
    ])
    def test_limit(self, code, pct):
        assert mr.price_limit_pct(code) == pct
