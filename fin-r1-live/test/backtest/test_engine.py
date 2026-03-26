"""
engine.py 单元测试 — 单笔交易/批量统计/边界条件全覆盖
"""
import math
from datetime import date

import pytest

from backtest.engine import (
    calc_single_trade, calc_portfolio,
    TradeResult, PortfolioSummary,
)
from backtest.fees import FeeConfig, TradeFees, HKFeeConfig


# ======== TradeResult ========

class TestTradeResult:
    def _make_result(self, **overrides):
        defaults = dict(
            code="000001", name="平安银行",
            buy_date=date(2025, 1, 2), buy_price=10.2, buy_quantity=1000,
            buy_amount=10205.0, buy_fees=TradeFees(commission=5.0),
            sell_date=date(2025, 1, 8), sell_price=10.5, sell_quantity=1000,
            sell_amount=10484.5, sell_fees=TradeFees(commission=5.0, stamp_tax=10.5),
            total_fees=20.5, net_profit=279.5, profit_pct=2.74,
            holding_days=6,
        )
        defaults.update(overrides)
        return TradeResult(**defaults)

    def test_to_dict_keys(self):
        r = self._make_result()
        d = r.to_dict()
        expected_keys = [
            "code", "name", "buy_date", "buy_price", "buy_quantity", "buy_amount",
            "buy_fees", "sell_date", "sell_price", "sell_quantity", "sell_amount",
            "sell_fees", "total_fees", "net_profit", "profit_pct", "holding_days",
            "period_high", "period_low", "max_drawdown_pct",
        ]
        for k in expected_keys:
            assert k in d

    def test_to_dict_dates_are_strings(self):
        r = self._make_result()
        d = r.to_dict()
        assert d["buy_date"] == "2025-01-02"
        assert d["sell_date"] == "2025-01-08"

    def test_to_dict_fees_nested(self):
        r = self._make_result()
        d = r.to_dict()
        assert "commission" in d["buy_fees"]
        assert "stamp_tax" in d["buy_fees"]
        assert "transfer_fee" in d["buy_fees"]
        assert "total" in d["buy_fees"]

    def test_optional_fields_default_none(self):
        r = self._make_result()
        assert r.period_high is None
        assert r.period_low is None
        assert r.max_drawdown_pct is None

    def test_optional_fields_set(self):
        r = self._make_result(period_high=11.0, period_low=9.8, max_drawdown_pct=5.0)
        assert r.period_high == 11.0
        assert r.period_low == 9.8
        assert r.max_drawdown_pct == 5.0


# ======== PortfolioSummary ========

class TestPortfolioSummary:
    def test_to_dict_keys(self):
        s = PortfolioSummary(
            start_date=date(2025, 1, 1), end_date=date(2025, 6, 30),
            total_trades=3, win_trades=2, lose_trades=1, win_rate=66.7,
            total_invested=100000, total_returned=105000, total_fees=100,
            net_profit=5000, profit_pct=5.0,
            max_single_profit=3000, max_single_loss=-500,
            avg_profit_per_trade=1666.67, avg_holding_days=30.0,
        )
        d = s.to_dict()
        assert d["total_trades"] == 3
        assert "66.7%" in d["win_rate"]
        assert "5.00%" in d["profit_pct"]


# ======== calc_single_trade A股 ========

class TestCalcSingleTradeAShare:
    def test_basic_trade_by_quantity(self):
        r = calc_single_trade("000001", date(2025, 1, 2), date(2025, 1, 8), quantity=1000)
        assert r.code == "000001"
        assert r.name == "平安银行"
        assert r.buy_price == 10.2
        assert r.sell_price == 10.5
        assert r.buy_quantity == 1000
        assert r.sell_quantity == 1000
        assert r.holding_days == 6
        assert r.net_profit > 0  # 价格涨了

    def test_trade_by_amount(self):
        r = calc_single_trade("000001", date(2025, 1, 2), date(2025, 1, 8), buy_amount=50000)
        # 50000 / 10.2 = 4901.96, 向下取整到100 = 4900
        assert r.buy_quantity == 4900

    def test_quantity_rounds_to_lot(self):
        """A股按100股整手"""
        r = calc_single_trade("000001", date(2025, 1, 2), date(2025, 1, 8), quantity=150)
        assert r.buy_quantity == 100  # 150 -> 100

    def test_quantity_less_than_lot_rounds_up(self):
        """不足100股按100股"""
        r = calc_single_trade("000001", date(2025, 1, 2), date(2025, 1, 8), quantity=50)
        assert r.buy_quantity == 100

    def test_fees_included_in_profit(self):
        r = calc_single_trade("000001", date(2025, 1, 2), date(2025, 1, 8), quantity=1000)
        assert r.total_fees > 0
        expected_gross = (r.sell_price - r.buy_price) * r.buy_quantity
        assert r.net_profit < expected_gross  # 费用扣减

    def test_custom_fee_config(self):
        config = FeeConfig(commission_rate=0.001)
        r = calc_single_trade("000001", date(2025, 1, 2), date(2025, 1, 8),
                              quantity=1000, fee_config=config)
        # 佣金比默认高
        assert r.buy_fees.commission > 5.0

    def test_sh_stock_has_transfer_fee(self):
        """沪市(600xxx)有过户费"""
        r = calc_single_trade("600519", date(2025, 2, 5), date(2025, 2, 6), quantity=100)
        assert r.buy_fees.transfer_fee > 0
        assert r.sell_fees.transfer_fee > 0

    def test_sz_stock_no_transfer_fee(self):
        """深市(000xxx)无过户费"""
        r = calc_single_trade("000001", date(2025, 1, 2), date(2025, 1, 8), quantity=1000)
        assert r.buy_fees.transfer_fee == 0.0

    def test_buy_no_stamp_tax(self):
        r = calc_single_trade("000001", date(2025, 1, 2), date(2025, 1, 8), quantity=1000)
        assert r.buy_fees.stamp_tax == 0.0

    def test_sell_has_stamp_tax(self):
        r = calc_single_trade("000001", date(2025, 1, 2), date(2025, 1, 8), quantity=1000)
        assert r.sell_fees.stamp_tax > 0

    def test_period_high_low(self):
        r = calc_single_trade("000001", date(2025, 1, 2), date(2025, 1, 8), quantity=1000)
        assert r.period_high == 11.0
        assert r.period_low == 9.8

    def test_max_drawdown(self):
        r = calc_single_trade("000001", date(2025, 1, 2), date(2025, 1, 8), quantity=1000)
        assert r.max_drawdown_pct is not None
        assert r.max_drawdown_pct > 0

    def test_profit_pct_calculation(self):
        r = calc_single_trade("000001", date(2025, 1, 2), date(2025, 1, 8), quantity=1000)
        recalc = (r.net_profit / r.buy_amount) * 100
        assert abs(r.profit_pct - round(recalc, 2)) < 0.01


class TestCalcSingleTradeValidation:
    def test_sell_before_buy_raises(self):
        with pytest.raises(ValueError, match="必须晚于"):
            calc_single_trade("000001", date(2025, 1, 8), date(2025, 1, 2), quantity=1000)

    def test_same_date_raises(self):
        with pytest.raises(ValueError, match="必须晚于"):
            calc_single_trade("000001", date(2025, 1, 2), date(2025, 1, 2), quantity=1000)

    def test_no_quantity_no_amount_raises(self):
        with pytest.raises(ValueError, match="必须指定"):
            calc_single_trade("000001", date(2025, 1, 2), date(2025, 1, 8))

    def test_no_data_buy_raises(self):
        with pytest.raises(ValueError, match="无法获取"):
            calc_single_trade("000001", date(2020, 1, 1), date(2025, 1, 8), quantity=1000)

    def test_no_data_sell_raises(self):
        with pytest.raises(ValueError, match="无法获取"):
            calc_single_trade("999999", date(2025, 1, 2), date(2025, 1, 8), quantity=1000)

    def test_amount_too_small_raises(self):
        with pytest.raises(ValueError, match="不足以买入"):
            calc_single_trade("000001", date(2025, 1, 2), date(2025, 1, 8), buy_amount=50)


# ======== calc_single_trade 港股通 ========

class TestCalcSingleTradeHK:
    def test_hk_trade_by_quantity(self):
        r = calc_single_trade("00700", date(2025, 3, 3), date(2025, 3, 5), quantity=200)
        assert r.code == "00700"
        assert r.name == "腾讯控股"
        assert r.buy_price == 385.0
        assert r.sell_price == 398.0
        assert r.buy_quantity == 200
        assert r.holding_days == 2
        assert r.net_profit > 0

    def test_hk_trade_by_amount(self):
        r = calc_single_trade("00700", date(2025, 3, 3), date(2025, 3, 5), buy_amount=100000)
        # 100000 / 385 = 259.7, int = 259 (港股不强制整手)
        assert r.buy_quantity == 259

    def test_hk_buy_has_stamp_tax(self):
        """港股通买入也收印花税"""
        r = calc_single_trade("00700", date(2025, 3, 3), date(2025, 3, 5), quantity=200)
        assert r.buy_fees.stamp_tax > 0

    def test_hk_sell_has_stamp_tax(self):
        """港股通卖出也收印花税"""
        r = calc_single_trade("00700", date(2025, 3, 3), date(2025, 3, 5), quantity=200)
        assert r.sell_fees.stamp_tax > 0

    def test_hk_has_misc_fees(self):
        """港股通有杂费（交易费+征费+交收费映射到transfer_fee）"""
        r = calc_single_trade("00700", date(2025, 3, 3), date(2025, 3, 5), quantity=200)
        assert r.buy_fees.transfer_fee > 0
        assert r.sell_fees.transfer_fee > 0

    def test_hk_quantity_no_lot_restriction(self):
        """港股不强制整手"""
        r = calc_single_trade("00700", date(2025, 3, 3), date(2025, 3, 5), quantity=1)
        assert r.buy_quantity == 1

    def test_hk_prefix_code(self):
        """HK前缀也能识别"""
        r = calc_single_trade("HK00700", date(2025, 3, 3), date(2025, 3, 5), quantity=100)
        assert r.code == "HK00700"

    def test_hk_custom_fee_config(self):
        hk_config = HKFeeConfig(commission_rate=0.001)
        r = calc_single_trade("00700", date(2025, 3, 3), date(2025, 3, 5),
                              quantity=200, hk_fee_config=hk_config)
        amount = 385.0 * 200
        assert r.buy_fees.commission == round(max(amount * 0.001, 5.0), 2)


# ======== calc_portfolio ========

class TestCalcPortfolio:
    def _make_trade(self, profit: float, buy_amount: float = 10000.0,
                    holding_days: int = 30, buy_date: date = None,
                    sell_date: date = None) -> TradeResult:
        if buy_date is None:
            buy_date = date(2025, 1, 1)
        if sell_date is None:
            sell_date = date(2025, 1, 31)
        sell_amount = buy_amount + profit
        return TradeResult(
            code="000001", name="测试",
            buy_date=buy_date, buy_price=10.0, buy_quantity=1000,
            buy_amount=buy_amount, buy_fees=TradeFees(commission=5.0),
            sell_date=sell_date, sell_price=10.5, sell_quantity=1000,
            sell_amount=sell_amount, sell_fees=TradeFees(commission=5.0, stamp_tax=10.0),
            total_fees=20.0, net_profit=profit, profit_pct=round(profit / buy_amount * 100, 2),
            holding_days=holding_days,
        )

    def test_single_winning_trade(self):
        trades = [self._make_trade(500)]
        s = calc_portfolio(trades)
        assert s.total_trades == 1
        assert s.win_trades == 1
        assert s.lose_trades == 0
        assert s.win_rate == 100.0
        assert s.net_profit > 0

    def test_single_losing_trade(self):
        trades = [self._make_trade(-300)]
        s = calc_portfolio(trades)
        assert s.win_trades == 0
        assert s.lose_trades == 1
        assert s.win_rate == 0.0

    def test_mixed_trades(self):
        trades = [
            self._make_trade(500, buy_date=date(2025, 1, 1), sell_date=date(2025, 2, 1)),
            self._make_trade(-200, buy_date=date(2025, 2, 1), sell_date=date(2025, 3, 1)),
            self._make_trade(300, buy_date=date(2025, 3, 1), sell_date=date(2025, 4, 1)),
        ]
        s = calc_portfolio(trades)
        assert s.total_trades == 3
        assert s.win_trades == 2
        assert s.lose_trades == 1
        assert s.win_rate == pytest.approx(66.666, abs=0.1)
        assert s.net_profit == pytest.approx(600, abs=1)

    def test_empty_trades_raises(self):
        with pytest.raises(ValueError, match="不能为空"):
            calc_portfolio([])

    def test_date_range(self):
        trades = [
            self._make_trade(100, buy_date=date(2025, 3, 1), sell_date=date(2025, 6, 1)),
            self._make_trade(200, buy_date=date(2025, 1, 1), sell_date=date(2025, 12, 1)),
        ]
        s = calc_portfolio(trades)
        assert s.start_date == date(2025, 1, 1)
        assert s.end_date == date(2025, 12, 1)

    def test_max_min_profit(self):
        trades = [
            self._make_trade(1000),
            self._make_trade(-500),
            self._make_trade(200),
        ]
        s = calc_portfolio(trades)
        assert s.max_single_profit == 1000
        assert s.max_single_loss == -500

    def test_avg_holding_days(self):
        trades = [
            self._make_trade(100, holding_days=10),
            self._make_trade(200, holding_days=30),
            self._make_trade(-50, holding_days=20),
        ]
        s = calc_portfolio(trades)
        assert s.avg_holding_days == 20.0

    def test_total_fees(self):
        trades = [self._make_trade(100), self._make_trade(200)]
        s = calc_portfolio(trades)
        assert s.total_fees == 40.0  # 20 per trade

    def test_profit_pct(self):
        trades = [self._make_trade(500, buy_amount=10000)]
        s = calc_portfolio(trades)
        # net_profit = sell_amount - buy_amount = 10500 - 10000 = 500
        assert s.profit_pct == pytest.approx(5.0, abs=0.1)

    def test_to_dict_has_summary_trades(self):
        trades = [self._make_trade(100)]
        s = calc_portfolio(trades)
        assert len(s.trades) == 1
        d = s.to_dict()
        assert "total_trades" in d

    def test_zero_profit_counted_as_loss(self):
        """net_profit == 0 算亏损"""
        trades = [self._make_trade(0)]
        s = calc_portfolio(trades)
        assert s.lose_trades == 1
        assert s.win_trades == 0

    def test_avg_profit_per_trade(self):
        trades = [
            self._make_trade(600),
            self._make_trade(-200),
        ]
        s = calc_portfolio(trades)
        assert s.avg_profit_per_trade == 200.0
