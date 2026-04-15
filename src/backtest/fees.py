"""
交易费用计算模块 - A股 & 港股通 + 滑点模型

A股费用 (2024年标准, 印花税 2023.08.28 减半):
- 佣金: 券商协商 (默认万1.15, 双向, 单笔最低5元)
- 印花税: 千分之零点五 (仅卖出, 2023年8月28日起)
- 过户费: 万分之零点二 (双向, 仅沪市)

港股通费用 (2026年标准, 沪港通/深港通):
- 佣金: 万分之三 (双向, 单笔最低5港元, 可协商)
- 印花税: 千分之一 (双向, 不足1港元按1港元计)
- 交易费: 万分之零点五六五 (双向, 联交所收取)
- 交易征费: 万分之零点二七 (双向, 证监会收取)
- 会财局征费: 万分之零点零一五 (双向)
- 股份交收费: 万分之零点四二 (双向, 最低2港元)

滑点模型 (P2-01):
- 固定滑点 (bps) + 基于成交量的市场冲击
- 简化 Almgren-Chriss: impact = coeff × (V_order/V_avg) × σ
- 费率可通过 env/.env.trading 中的 FEE_*/SLIPPAGE_* 环境变量配置

费率可通过 env/.env.trading 中的 FEE_* 环境变量配置,
也可在代码中直接构造 FeeConfig/HKFeeConfig 覆盖。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.common.config import BacktestConfig


# ======== 费率配置 ========

@dataclass
class FeeConfig:
    """A股交易费率配置 (默认值从 env/.env.trading 的 FEE_* 读取)"""
    commission_rate: float = 0.000115      # 万1.15
    commission_min: float = 5.0
    stamp_tax_rate: float = 0.0005         # 千0.5 (2023.08.28 起)
    transfer_fee_rate: float = 0.00002

    @classmethod
    def from_settings(cls, cfg: BacktestConfig) -> FeeConfig:
        return cls(
            commission_rate=cfg.commission_rate,
            commission_min=cfg.commission_min,
            stamp_tax_rate=cfg.stamp_tax_rate,
            transfer_fee_rate=cfg.transfer_fee_rate,
        )


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

    @classmethod
    def from_settings(cls, cfg: BacktestConfig) -> HKFeeConfig:
        return cls(
            commission_rate=cfg.hk_commission_rate,
            commission_min=cfg.hk_commission_min,
            stamp_tax_rate=cfg.hk_stamp_tax_rate,
            trading_fee_rate=cfg.hk_trading_fee_rate,
            transaction_levy_rate=cfg.hk_transaction_levy_rate,
            frc_levy_rate=cfg.hk_frc_levy_rate,
            settlement_fee_rate=cfg.hk_settlement_fee_rate,
            settlement_fee_min=cfg.hk_settlement_fee_min,
        )


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


# ======== 滑点模型 (P2-01) ========

@dataclass
class SlippageConfig:
    """滑点模型参数

    简化 Almgren-Chriss 市场冲击模型:
    slippage = fixed_bps + impact_coeff × (order_value / daily_volume) × volatility
    """
    enabled: bool = False
    fixed_bps: float = 5.0
    impact_coeff: float = 0.1
    vol_lookback_days: int = 20
    asymmetric: bool = True

    @classmethod
    def from_settings(cls, cfg: BacktestConfig) -> SlippageConfig:
        return cls(
            enabled=cfg.slippage_enabled,
            fixed_bps=cfg.slippage_fixed_bps,
            impact_coeff=cfg.slippage_impact_coeff,
            vol_lookback_days=cfg.slippage_vol_lookback,
            asymmetric=cfg.slippage_asymmetric,
        )


@dataclass
class SlippageResult:
    """单笔交易滑点明细"""
    fixed_cost: float = 0.0
    impact_cost: float = 0.0

    @property
    def total(self) -> float:
        return self.fixed_cost + self.impact_cost


class SlippageModel:
    """基于成交量的动态滑点模型

    合并了固定买卖价差 (bid-ask spread) 和成交量冲击:
    - fixed: order_value × fixed_bps / 10000
    - impact: impact_coeff × (order_value / daily_volume) × volatility × order_value

    对散户而言 impact 部分通常很小 (订单占日成交量比例极低),
    但对大资金或小盘股交易会产生可观的冲击成本。
    """

    def __init__(self, config: SlippageConfig | None = None):
        self.config = config or SlippageConfig()

    def estimate(
        self,
        order_value: float,
        daily_volume: float = 0.0,
        volatility: float = 0.0,
        direction: str = "buy",
    ) -> SlippageResult:
        """估算单笔交易的滑点成本

        Args:
            order_value: 订单金额 (元)
            daily_volume: 当日成交额 (元), 0 则忽略冲击项
            volatility: 标的近期波动率 (年化标准差, 如 0.30)
            direction: "buy" 或 "sell"

        Returns:
            SlippageResult 包含 fixed_cost 和 impact_cost
        """
        if not self.config.enabled or order_value <= 0:
            return SlippageResult()

        bps = self.config.fixed_bps
        if self.config.asymmetric and direction == "sell":
            bps *= 1.2

        fixed_cost = order_value * bps / 10_000

        impact_cost = 0.0
        if daily_volume > 0 and volatility > 0:
            participation = order_value / daily_volume
            impact_cost = (
                self.config.impact_coeff
                * participation
                * volatility
                * order_value
            )

        return SlippageResult(
            fixed_cost=round(fixed_cost, 2),
            impact_cost=round(impact_cost, 2),
        )

    def adjust_price(
        self,
        price: float,
        order_value: float,
        daily_volume: float = 0.0,
        volatility: float = 0.0,
        direction: str = "buy",
    ) -> float:
        """返回考虑滑点后的成交价格

        买入: 价格上调 (付出更多); 卖出: 价格下调 (收到更少)
        """
        result = self.estimate(order_value, daily_volume, volatility, direction)
        slippage_pct = result.total / order_value if order_value > 0 else 0.0
        if direction == "buy":
            return round(price * (1 + slippage_pct), 4)
        return round(price * (1 - slippage_pct), 4)
