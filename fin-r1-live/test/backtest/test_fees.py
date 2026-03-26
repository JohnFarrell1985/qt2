"""
fees.py 单元测试 — A股 & 港股通费用计算全覆盖
"""
import math
import pytest

from backtest.fees import (
    FeeConfig, HKFeeConfig,
    TradeFees, HKTradeFees,
    is_sh_stock, is_hk_stock, detect_market,
    calc_buy_fees, calc_sell_fees,
    calc_hk_buy_fees, calc_hk_sell_fees,
    _hk_stamp_tax,
)


# ======== 数据类 ========

class TestFeeConfig:
    def test_defaults(self):
        c = FeeConfig()
        assert c.commission_rate == 0.0003
        assert c.commission_min == 5.0
        assert c.stamp_tax_rate == 0.001
        assert c.transfer_fee_rate == 0.00002

    def test_custom(self):
        c = FeeConfig(commission_rate=0.0005, commission_min=10.0)
        assert c.commission_rate == 0.0005
        assert c.commission_min == 10.0


class TestHKFeeConfig:
    def test_defaults(self):
        c = HKFeeConfig()
        assert c.commission_rate == 0.0003
        assert c.commission_min == 5.0
        assert c.stamp_tax_rate == 0.001
        assert c.trading_fee_rate == 0.0000565
        assert c.transaction_levy_rate == 0.000027
        assert c.frc_levy_rate == 0.0000015
        assert c.settlement_fee_rate == 0.000042
        assert c.settlement_fee_min == 2.0

    def test_custom(self):
        c = HKFeeConfig(commission_rate=0.0005, settlement_fee_min=5.0)
        assert c.commission_rate == 0.0005
        assert c.settlement_fee_min == 5.0


class TestTradeFees:
    def test_total_zero(self):
        f = TradeFees()
        assert f.total == 0.0

    def test_total_sum(self):
        f = TradeFees(commission=5.0, stamp_tax=10.0, transfer_fee=0.2)
        assert f.total == 15.2

    def test_defaults(self):
        f = TradeFees()
        assert f.commission == 0.0
        assert f.stamp_tax == 0.0
        assert f.transfer_fee == 0.0


class TestHKTradeFees:
    def test_total_zero(self):
        f = HKTradeFees()
        assert f.total == 0.0

    def test_total_all_fields(self):
        f = HKTradeFees(
            commission=10.0, stamp_tax=20.0, trading_fee=1.0,
            transaction_levy=0.5, frc_levy=0.1, settlement_fee=2.0,
        )
        assert f.total == pytest.approx(33.6)

    def test_defaults(self):
        f = HKTradeFees()
        assert f.commission == 0.0
        assert f.stamp_tax == 0.0
        assert f.trading_fee == 0.0
        assert f.transaction_levy == 0.0
        assert f.frc_levy == 0.0
        assert f.settlement_fee == 0.0


# ======== 市场判断 ========

class TestIsShStock:
    def test_sh_stocks(self):
        assert is_sh_stock("600519") is True
        assert is_sh_stock("601318") is True
        assert is_sh_stock("688001") is True

    def test_non_sh_stocks(self):
        assert is_sh_stock("000001") is False
        assert is_sh_stock("300750") is False
        assert is_sh_stock("002230") is False

    def test_edge_cases(self):
        assert is_sh_stock("6") is True
        assert is_sh_stock("") is False


class TestIsHkStock:
    def test_five_digit_codes(self):
        assert is_hk_stock("00700") is True
        assert is_hk_stock("09988") is True
        assert is_hk_stock("01810") is True

    def test_hk_prefix(self):
        assert is_hk_stock("HK00700") is True
        assert is_hk_stock("hk09988") is True
        assert is_hk_stock("HK12345") is True

    def test_a_share_codes(self):
        assert is_hk_stock("000001") is False
        assert is_hk_stock("600519") is False
        assert is_hk_stock("300750") is False

    def test_edge_cases(self):
        assert is_hk_stock("0070") is False  # 4位
        assert is_hk_stock("007000") is False  # 6位
        assert is_hk_stock("HK") is True  # 只有HK前缀
        assert is_hk_stock("") is False


class TestDetectMarket:
    def test_a_share(self):
        assert detect_market("000001") == "A"
        assert detect_market("600519") == "A"
        assert detect_market("300750") == "A"

    def test_hk_stock(self):
        assert detect_market("00700") == "HK"
        assert detect_market("HK00700") == "HK"
        assert detect_market("09988") == "HK"


# ======== A股费用计算 ========

class TestCalcBuyFees:
    def test_default_config(self):
        fees = calc_buy_fees(10.0, 1000, "000001")
        assert fees.commission == max(10.0 * 1000 * 0.0003, 5.0)
        assert fees.stamp_tax == 0.0  # 买入不收印花税
        assert fees.transfer_fee == 0.0  # 深市无过户费

    def test_sh_stock_has_transfer_fee(self):
        fees = calc_buy_fees(10.0, 1000, "600519")
        assert fees.transfer_fee == round(10.0 * 1000 * 0.00002, 2)

    def test_sz_stock_no_transfer_fee(self):
        fees = calc_buy_fees(10.0, 1000, "000001")
        assert fees.transfer_fee == 0.0

    def test_minimum_commission(self):
        fees = calc_buy_fees(1.0, 100, "000001")  # 金额100, 万三=0.03
        assert fees.commission == 5.0  # 最低佣金

    def test_custom_config(self):
        config = FeeConfig(commission_rate=0.0005, commission_min=10.0)
        fees = calc_buy_fees(10.0, 1000, "000001", config)
        assert fees.commission == max(10000 * 0.0005, 10.0)

    def test_none_config(self):
        fees = calc_buy_fees(10.0, 1000, "000001", None)
        assert fees.commission > 0

    def test_large_amount(self):
        fees = calc_buy_fees(1500.0, 100, "600519")
        amount = 1500.0 * 100
        assert fees.commission == round(amount * 0.0003, 2)
        assert fees.transfer_fee == round(amount * 0.00002, 2)


class TestCalcSellFees:
    def test_default_config(self):
        fees = calc_sell_fees(10.0, 1000, "000001")
        amount = 10.0 * 1000
        assert fees.commission == round(max(amount * 0.0003, 5.0), 2)
        assert fees.stamp_tax == round(amount * 0.001, 2)
        assert fees.transfer_fee == 0.0  # 深市

    def test_sh_stock_has_transfer_fee(self):
        fees = calc_sell_fees(10.0, 1000, "600519")
        assert fees.transfer_fee == round(10000 * 0.00002, 2)

    def test_stamp_tax_always_charged(self):
        fees = calc_sell_fees(10.0, 1000, "000001")
        assert fees.stamp_tax == 10.0  # 10000 * 0.001

    def test_minimum_commission_sell(self):
        fees = calc_sell_fees(1.0, 100, "000001")
        assert fees.commission == 5.0

    def test_custom_stamp_tax(self):
        config = FeeConfig(stamp_tax_rate=0.0005)
        fees = calc_sell_fees(10.0, 1000, "000001", config)
        assert fees.stamp_tax == round(10000 * 0.0005, 2)

    def test_none_config(self):
        fees = calc_sell_fees(10.0, 1000, "000001", None)
        assert fees.stamp_tax > 0


# ======== 港股通费用计算 ========

class TestHkStampTax:
    def test_rounds_up(self):
        assert _hk_stamp_tax(10000.0, 0.001) == 10.0  # exact
        assert _hk_stamp_tax(10001.0, 0.001) == 11.0  # rounds up

    def test_minimum_one_dollar(self):
        assert _hk_stamp_tax(1.0, 0.001) == 1.0  # 0.001 -> ceil -> 1
        assert _hk_stamp_tax(0.5, 0.001) == 1.0  # < 1 -> 1

    def test_large_amount(self):
        assert _hk_stamp_tax(1000000.0, 0.001) == 1000.0

    def test_fractional_ceil(self):
        assert _hk_stamp_tax(999.0, 0.001) == 1.0  # 0.999 -> ceil = 1


class TestCalcHkBuyFees:
    def test_default_config(self):
        fees = calc_hk_buy_fees(380.0, 200, "00700")
        amount = 380.0 * 200
        assert fees.commission == round(max(amount * 0.0003, 5.0), 2)
        assert fees.stamp_tax == math.ceil(amount * 0.001)
        assert fees.trading_fee == round(amount * 0.0000565, 2)
        assert fees.transaction_levy == round(amount * 0.000027, 2)
        assert fees.frc_levy == round(amount * 0.0000015, 2)
        assert fees.settlement_fee == max(round(amount * 0.000042, 2), 2.0)
        assert fees.total > 0

    def test_all_fees_positive(self):
        fees = calc_hk_buy_fees(100.0, 1000, "00700")
        assert fees.commission > 0
        assert fees.stamp_tax >= 1.0
        assert fees.trading_fee >= 0
        assert fees.transaction_levy >= 0
        assert fees.frc_levy >= 0
        assert fees.settlement_fee >= 2.0

    def test_minimum_commission(self):
        fees = calc_hk_buy_fees(1.0, 10, "00700")  # amount = 10
        assert fees.commission == 5.0

    def test_minimum_settlement_fee(self):
        fees = calc_hk_buy_fees(1.0, 10, "00700")  # settlement = 10*0.000042 = 0.00042
        assert fees.settlement_fee == 2.0

    def test_none_config(self):
        fees = calc_hk_buy_fees(380.0, 200, "00700", None)
        assert fees.total > 0

    def test_custom_config(self):
        config = HKFeeConfig(commission_rate=0.0005, commission_min=10.0)
        fees = calc_hk_buy_fees(380.0, 200, "00700", config)
        amount = 380.0 * 200
        assert fees.commission == round(max(amount * 0.0005, 10.0), 2)

    def test_stamp_tax_bidirectional(self):
        """港股通买入也收印花税"""
        fees = calc_hk_buy_fees(380.0, 200, "00700")
        assert fees.stamp_tax > 0


class TestCalcHkSellFees:
    def test_same_as_buy(self):
        """港股通卖出费用与买入完全一致"""
        buy = calc_hk_buy_fees(380.0, 200, "00700")
        sell = calc_hk_sell_fees(380.0, 200, "00700")
        assert buy.commission == sell.commission
        assert buy.stamp_tax == sell.stamp_tax
        assert buy.trading_fee == sell.trading_fee
        assert buy.transaction_levy == sell.transaction_levy
        assert buy.frc_levy == sell.frc_levy
        assert buy.settlement_fee == sell.settlement_fee
        assert buy.total == sell.total

    def test_sell_with_custom_config(self):
        config = HKFeeConfig(commission_rate=0.001)
        fees = calc_hk_sell_fees(100.0, 500, "00700", config)
        amount = 100.0 * 500
        assert fees.commission == round(max(amount * 0.001, 5.0), 2)

    def test_none_config(self):
        fees = calc_hk_sell_fees(380.0, 200, "00700", None)
        assert fees.total > 0


# ======== 买卖费率对比 ========

class TestAShareVsHKFeeStructure:
    def test_a_share_buy_no_stamp_tax(self):
        fees = calc_buy_fees(10.0, 1000, "000001")
        assert fees.stamp_tax == 0.0

    def test_a_share_sell_has_stamp_tax(self):
        fees = calc_sell_fees(10.0, 1000, "000001")
        assert fees.stamp_tax > 0

    def test_hk_buy_has_stamp_tax(self):
        fees = calc_hk_buy_fees(380.0, 200, "00700")
        assert fees.stamp_tax > 0

    def test_hk_sell_has_stamp_tax(self):
        fees = calc_hk_sell_fees(380.0, 200, "00700")
        assert fees.stamp_tax > 0

    def test_hk_has_more_fee_categories(self):
        hk_fees = calc_hk_buy_fees(100.0, 1000, "00700")
        a_fees = calc_buy_fees(100.0, 1000, "000001")
        # 港股通有更多费用项
        assert hk_fees.trading_fee >= 0
        assert hk_fees.transaction_levy >= 0
        assert hk_fees.frc_levy >= 0
        assert hk_fees.settlement_fee >= 0
        # A股不存在这些费用
        assert not hasattr(a_fees, 'trading_fee')
