"""
交易费用计算模块 - A股 & 港股通

A股费用 (2024年标准):
- 佣金: 万分之三 (双向, 单笔最低5元)
- 印花税: 千分之一 (仅卖出)
- 过户费: 万分之零点二 (双向, 仅沪市)

港股通费用 (2026年标准, 沪港通/深港通):
- 佣金: 万分之三 (双向, 单笔最低5港元, 可协商)
- 印花税: 千分之一 (双向, 不足1港元按1港元计)
- 交易费: 万分之零点五六五 (双向, 联交所收取)
- 交易征费: 万分之零点二七 (双向, 证监会收取)
- 会财局征费: 万分之零点零一五 (双向)
- 股份交收费: 万分之零点四二 (双向, 最低2港元)
"""
from dataclasses import dataclass
import math


# ======== 费率配置 ========

@dataclass
class FeeConfig:
    """A股交易费率配置"""
    commission_rate: float = 0.0003
    commission_min: float = 5.0
    stamp_tax_rate: float = 0.001
    transfer_fee_rate: float = 0.00002


@dataclass
class HKFeeConfig:
    """港股通交易费率配置"""
    commission_rate: float = 0.0003        # 佣金 万三
    commission_min: float = 5.0            # 最低佣金 5港元
    stamp_tax_rate: float = 0.001          # 印花税 千一 (双向, 向上取整到元)
    trading_fee_rate: float = 0.0000565    # 交易费 (联交所)
    transaction_levy_rate: float = 0.000027  # 交易征费 (证监会)
    frc_levy_rate: float = 0.0000015       # 会财局征费
    settlement_fee_rate: float = 0.000042  # 股份交收费
    settlement_fee_min: float = 2.0        # 交收费最低 2港元


# ======== 费用明细 ========

@dataclass
class TradeFees:
    """单笔交易费用明细"""
    commission: float = 0.0
    stamp_tax: float = 0.0
    transfer_fee: float = 0.0

    @property
    def total(self) -> float:
        return self.commission + self.stamp_tax + self.transfer_fee


@dataclass
class HKTradeFees:
    """港股通单笔交易费用明细"""
    commission: float = 0.0
    stamp_tax: float = 0.0
    trading_fee: float = 0.0
    transaction_levy: float = 0.0
    frc_levy: float = 0.0
    settlement_fee: float = 0.0

    @property
    def total(self) -> float:
        return (self.commission + self.stamp_tax + self.trading_fee
                + self.transaction_levy + self.frc_levy + self.settlement_fee)


# ======== 市场判断 ========

def is_sh_stock(code: str) -> bool:
    """沪市A股 (6开头)"""
    return code.startswith('6')


def is_hk_stock(code: str) -> bool:
    """港股通标的 (5位数字, 或以HK/hk前缀)"""
    clean = code.upper().replace("HK", "").strip()
    if clean.isdigit() and len(clean) == 5:
        return True
    if code.upper().startswith("HK"):
        return True
    return False


def detect_market(code: str) -> str:
    """
    自动检测市场类型
    返回: 'A' (A股) 或 'HK' (港股通)
    """
    if is_hk_stock(code):
        return "HK"
    return "A"


# ======== A股费用计算 ========

def calc_buy_fees(price: float, quantity: int, code: str,
                  config: FeeConfig = None) -> TradeFees:
    """计算A股买入费用"""
    if config is None:
        config = FeeConfig()

    amount = price * quantity
    commission = max(amount * config.commission_rate, config.commission_min)
    transfer_fee = amount * config.transfer_fee_rate if is_sh_stock(code) else 0.0

    return TradeFees(
        commission=round(commission, 2),
        stamp_tax=0.0,
        transfer_fee=round(transfer_fee, 2),
    )


def calc_sell_fees(price: float, quantity: int, code: str,
                   config: FeeConfig = None) -> TradeFees:
    """计算A股卖出费用"""
    if config is None:
        config = FeeConfig()

    amount = price * quantity
    commission = max(amount * config.commission_rate, config.commission_min)
    stamp_tax = amount * config.stamp_tax_rate
    transfer_fee = amount * config.transfer_fee_rate if is_sh_stock(code) else 0.0

    return TradeFees(
        commission=round(commission, 2),
        stamp_tax=round(stamp_tax, 2),
        transfer_fee=round(transfer_fee, 2),
    )


# ======== 港股通费用计算 ========

def _hk_stamp_tax(amount: float, rate: float) -> float:
    """港股印花税: 向上取整到整数港元, 不足1元按1元"""
    raw = amount * rate
    return max(math.ceil(raw), 1.0)


def calc_hk_buy_fees(price: float, quantity: int, code: str,
                     config: HKFeeConfig = None) -> HKTradeFees:
    """
    计算港股通买入费用
    港股通买卖双方都要缴全部费用（印花税、交易费、征费等）
    """
    if config is None:
        config = HKFeeConfig()

    amount = price * quantity

    commission = max(amount * config.commission_rate, config.commission_min)
    stamp_tax = _hk_stamp_tax(amount, config.stamp_tax_rate)
    trading_fee = round(amount * config.trading_fee_rate, 2)
    transaction_levy = round(amount * config.transaction_levy_rate, 2)
    frc_levy = round(amount * config.frc_levy_rate, 2)
    settlement_fee = max(round(amount * config.settlement_fee_rate, 2),
                         config.settlement_fee_min)

    return HKTradeFees(
        commission=round(commission, 2),
        stamp_tax=stamp_tax,
        trading_fee=trading_fee,
        transaction_levy=transaction_levy,
        frc_levy=frc_levy,
        settlement_fee=settlement_fee,
    )


def calc_hk_sell_fees(price: float, quantity: int, code: str,
                      config: HKFeeConfig = None) -> HKTradeFees:
    """
    计算港股通卖出费用
    与买入完全一致 — 港股通所有费用均双向收取
    """
    return calc_hk_buy_fees(price, quantity, code, config)
