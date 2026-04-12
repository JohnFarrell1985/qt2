"""Tests for src/backtest/fees.py"""
import math

import pytest

from src.backtest.fees import (
    FeeConfig,
    HKFeeConfig,
    TradeFees,
    HKTradeFees,
    is_sh_stock,
    is_hk_stock,
    detect_market,
    calc_buy_fees,
    calc_sell_fees,
    calc_hk_buy_fees,
    calc_hk_sell_fees,
    _hk_stamp_tax,
)


# ---- FeeConfig defaults ----

class TestFeeConfig:
    def test_defaults(self):
        cfg = FeeConfig()
        assert cfg.commission_rate == 0.000115  # 万1.15
        assert cfg.commission_min == 5.0
        assert cfg.stamp_tax_rate == 0.0005     # 千0.5 (2023.08.28 起)
        assert cfg.transfer_fee_rate == 0.00002

    def test_custom(self):
        cfg = FeeConfig(commission_rate=0.0005, commission_min=10.0)
        assert cfg.commission_rate == 0.0005
        assert cfg.commission_min == 10.0


class TestHKFeeConfig:
    def test_defaults(self):
        cfg = HKFeeConfig()
        assert cfg.commission_rate == 0.0003
        assert cfg.commission_min == 5.0
        assert cfg.stamp_tax_rate == 0.001
        assert cfg.trading_fee_rate == 0.0000565
        assert cfg.transaction_levy_rate == 0.000027
        assert cfg.frc_levy_rate == 0.0000015
        assert cfg.settlement_fee_rate == 0.000042
        assert cfg.settlement_fee_min == 2.0


# ---- TradeFees / HKTradeFees ----

class TestTradeFees:
    def test_total(self):
        fees = TradeFees(commission=10.0, stamp_tax=5.0, transfer_fee=0.5)
        assert fees.total == 15.5

    def test_defaults_total_zero(self):
        fees = TradeFees()
        assert fees.total == 0.0


class TestHKTradeFees:
    def test_total(self):
        fees = HKTradeFees(
            commission=10, stamp_tax=5, trading_fee=1,
            transaction_levy=0.5, frc_levy=0.1, settlement_fee=2,
        )
        assert fees.total == 18.6

    def test_defaults_total_zero(self):
        fees = HKTradeFees()
        assert fees.total == 0.0


# ---- Market detection ----

class TestIsSHStock:
    def test_sh_stock(self):
        assert is_sh_stock("600000") is True
        assert is_sh_stock("601398") is True

    def test_sz_stock(self):
        assert is_sh_stock("000001") is False
        assert is_sh_stock("300001") is False

    def test_cyb_stock(self):
        assert is_sh_stock("301001") is False


class TestIsHKStock:
    def test_five_digit_code(self):
        assert is_hk_stock("00700") is True
        assert is_hk_stock("09988") is True

    def test_hk_prefix(self):
        assert is_hk_stock("HK00700") is True
        assert is_hk_stock("hk00700") is True

    def test_a_share_codes(self):
        assert is_hk_stock("600000") is False
        assert is_hk_stock("000001") is False

    def test_four_digit_not_hk(self):
        assert is_hk_stock("0070") is False


class TestDetectMarket:
    def test_a_share(self):
        assert detect_market("600000") == "A"
        assert detect_market("000001") == "A"

    def test_hk(self):
        assert detect_market("00700") == "HK"
        assert detect_market("HK00700") == "HK"


# ---- A-share fee calculations ----

class TestCalcBuyFees:
    def test_sh_stock_has_transfer_fee(self):
        fees = calc_buy_fees(10.0, 1000, "600000")
        assert fees.transfer_fee > 0

    def test_sz_stock_no_transfer_fee(self):
        fees = calc_buy_fees(10.0, 1000, "000001")
        assert fees.transfer_fee == 0.0

    def test_no_stamp_tax_on_buy(self):
        fees = calc_buy_fees(10.0, 1000, "600000")
        assert fees.stamp_tax == 0.0

    def test_commission_minimum_5(self):
        fees = calc_buy_fees(1.0, 10, "000001")
        assert fees.commission == 5.0

    def test_commission_calculated(self):
        fees = calc_buy_fees(100.0, 1000, "000001")
        expected = round(100_000 * 0.000115, 2)
        assert fees.commission == expected

    def test_transfer_fee_value_sh(self):
        fees = calc_buy_fees(50.0, 2000, "601398")
        expected = round(100_000 * 0.00002, 2)
        assert fees.transfer_fee == expected

    def test_custom_config(self):
        cfg = FeeConfig(commission_rate=0.0005, commission_min=10.0, transfer_fee_rate=0.0001)
        fees = calc_buy_fees(10.0, 1000, "600000", config=cfg)
        assert fees.commission == max(round(10_000 * 0.0005, 2), 10.0)
        assert fees.transfer_fee == round(10_000 * 0.0001, 2)

    def test_total_buy_sh(self):
        fees = calc_buy_fees(10.0, 1000, "600000")
        assert fees.total == fees.commission + fees.transfer_fee


class TestCalcSellFees:
    def test_stamp_tax_on_sell(self):
        fees = calc_sell_fees(10.0, 1000, "600000")
        expected = round(10_000 * 0.0005, 2)
        assert fees.stamp_tax == expected

    def test_sh_stock_has_transfer_fee(self):
        fees = calc_sell_fees(10.0, 1000, "600000")
        assert fees.transfer_fee > 0

    def test_sz_stock_no_transfer_fee(self):
        fees = calc_sell_fees(10.0, 1000, "000001")
        assert fees.transfer_fee == 0.0

    def test_commission_minimum_5(self):
        fees = calc_sell_fees(1.0, 10, "000001")
        assert fees.commission == 5.0

    def test_total_sell_sz(self):
        fees = calc_sell_fees(10.0, 1000, "000001")
        assert fees.total == fees.commission + fees.stamp_tax

    def test_total_sell_sh(self):
        fees = calc_sell_fees(10.0, 1000, "600000")
        assert fees.total == fees.commission + fees.stamp_tax + fees.transfer_fee

    def test_custom_config(self):
        cfg = FeeConfig(stamp_tax_rate=0.002)
        fees = calc_sell_fees(100.0, 100, "000001", config=cfg)
        assert fees.stamp_tax == round(10_000 * 0.002, 2)


# ---- HK stamp tax ----

class TestHKStampTax:
    def test_rounds_up(self):
        result = _hk_stamp_tax(10000, 0.001)
        assert result == math.ceil(10000 * 0.001)
        assert result == 10.0

    def test_minimum_one(self):
        result = _hk_stamp_tax(100, 0.001)
        assert result >= 1.0

    def test_fractional_rounds_up(self):
        result = _hk_stamp_tax(1500, 0.001)
        assert result == math.ceil(1.5)
        assert result == 2.0

    def test_very_small_amount(self):
        result = _hk_stamp_tax(0.5, 0.001)
        assert result == 1.0


# ---- HK fee calculations ----

class TestCalcHKBuyFees:
    def test_returns_hk_trade_fees(self):
        fees = calc_hk_buy_fees(50.0, 1000, "00700")
        assert isinstance(fees, HKTradeFees)

    def test_commission_minimum(self):
        fees = calc_hk_buy_fees(0.1, 10, "00700")
        assert fees.commission == 5.0

    def test_stamp_tax_ceiling(self):
        fees = calc_hk_buy_fees(50.0, 1000, "00700")
        amount = 50.0 * 1000
        assert fees.stamp_tax == max(math.ceil(amount * 0.001), 1.0)

    def test_settlement_fee_minimum(self):
        fees = calc_hk_buy_fees(0.1, 10, "00700")
        assert fees.settlement_fee >= 2.0

    def test_all_fee_components_positive(self):
        fees = calc_hk_buy_fees(100.0, 500, "00700")
        assert fees.commission > 0
        assert fees.stamp_tax > 0
        assert fees.trading_fee > 0
        assert fees.transaction_levy > 0
        assert fees.frc_levy >= 0
        assert fees.settlement_fee > 0

    def test_total_sum(self):
        fees = calc_hk_buy_fees(100.0, 500, "00700")
        expected = (
            fees.commission + fees.stamp_tax + fees.trading_fee
            + fees.transaction_levy + fees.frc_levy + fees.settlement_fee
        )
        assert pytest.approx(fees.total, abs=1e-10) == expected

    def test_custom_config(self):
        cfg = HKFeeConfig(commission_rate=0.001, commission_min=20.0)
        fees = calc_hk_buy_fees(100.0, 100, "00700", config=cfg)
        assert fees.commission == max(round(10_000 * 0.001, 2), 20.0)


class TestCalcHKSellFees:
    def test_same_as_buy(self):
        buy = calc_hk_buy_fees(100.0, 500, "00700")
        sell = calc_hk_sell_fees(100.0, 500, "00700")
        assert buy.total == sell.total

    def test_returns_hk_trade_fees(self):
        fees = calc_hk_sell_fees(50.0, 1000, "00700")
        assert isinstance(fees, HKTradeFees)
