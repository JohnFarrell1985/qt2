"""标的池分类与交易规则引擎

根据证券代码自动推断资产类型，并提供对应的交易规则（T+N、涨跌幅、
印花税、最小交易单位等）。供 SignalArbiter / PositionSizer / PositionMonitor 使用。

参考：
  - 深交所交易规则: https://www.szse.cn/lawrules/rule/
  - 上交所交易规则: http://www.sse.com.cn/lawandrules/
  - 港股通交易规则: https://www.hkex.com.cn/
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from src.common.config import settings


class AssetType(str, Enum):
    A_STOCK_MAIN = "a_stock_main"
    A_STOCK_STAR = "a_stock_star"
    A_STOCK_GEM = "a_stock_gem"
    A_STOCK_BSE = "a_stock_bse"
    HK_CONNECT = "hk_connect"
    ETF_DOMESTIC = "etf_domestic"
    ETF_CROSS_BORDER = "etf_cross_border"
    CONVERTIBLE_BOND = "cb"
    MARGIN_LONG = "margin_long"
    MARGIN_SHORT = "margin_short"


@dataclass(frozen=True)
class TradingRule:
    """资产交易规则"""

    asset_type: AssetType
    t_plus_n: int
    price_limit_pct: Optional[float]
    stamp_tax_rate: float
    min_lot_size: int
    can_short: bool
    margin_ratio: Optional[float]
    session_hours: str


TRADING_RULES: dict[AssetType, TradingRule] = {
    AssetType.A_STOCK_MAIN: TradingRule(
        asset_type=AssetType.A_STOCK_MAIN,
        t_plus_n=1,
        price_limit_pct=0.10,
        stamp_tax_rate=0.0005,
        min_lot_size=100,
        can_short=False,
        margin_ratio=None,
        session_hours="09:30-11:30,13:00-15:00",
    ),
    AssetType.A_STOCK_STAR: TradingRule(
        asset_type=AssetType.A_STOCK_STAR,
        t_plus_n=1,
        price_limit_pct=0.20,
        stamp_tax_rate=0.0005,
        min_lot_size=200,
        can_short=False,
        margin_ratio=None,
        session_hours="09:30-11:30,13:00-15:00",
    ),
    AssetType.A_STOCK_GEM: TradingRule(
        asset_type=AssetType.A_STOCK_GEM,
        t_plus_n=1,
        price_limit_pct=0.20,
        stamp_tax_rate=0.0005,
        min_lot_size=100,
        can_short=False,
        margin_ratio=None,
        session_hours="09:30-11:30,13:00-15:00",
    ),
    AssetType.A_STOCK_BSE: TradingRule(
        asset_type=AssetType.A_STOCK_BSE,
        t_plus_n=1,
        price_limit_pct=0.30,
        stamp_tax_rate=0.0005,
        min_lot_size=100,
        can_short=False,
        margin_ratio=None,
        session_hours="09:30-11:30,13:00-15:00",
    ),
    AssetType.HK_CONNECT: TradingRule(
        asset_type=AssetType.HK_CONNECT,
        t_plus_n=0,
        price_limit_pct=None,
        stamp_tax_rate=0.0,
        min_lot_size=1,
        can_short=False,
        margin_ratio=None,
        session_hours="09:30-12:00,13:00-16:00",
    ),
    AssetType.ETF_DOMESTIC: TradingRule(
        asset_type=AssetType.ETF_DOMESTIC,
        t_plus_n=1,
        price_limit_pct=None,
        stamp_tax_rate=0.0,
        min_lot_size=100,
        can_short=False,
        margin_ratio=None,
        session_hours="09:30-11:30,13:00-15:00",
    ),
    AssetType.ETF_CROSS_BORDER: TradingRule(
        asset_type=AssetType.ETF_CROSS_BORDER,
        t_plus_n=0,
        price_limit_pct=None,
        stamp_tax_rate=0.0,
        min_lot_size=100,
        can_short=False,
        margin_ratio=None,
        session_hours="09:30-11:30,13:00-15:00",
    ),
    AssetType.CONVERTIBLE_BOND: TradingRule(
        asset_type=AssetType.CONVERTIBLE_BOND,
        t_plus_n=0,
        price_limit_pct=0.20,
        stamp_tax_rate=0.0,
        min_lot_size=10,
        can_short=False,
        margin_ratio=None,
        session_hours="09:30-11:30,13:00-15:00",
    ),
    AssetType.MARGIN_LONG: TradingRule(
        asset_type=AssetType.MARGIN_LONG,
        t_plus_n=1,
        price_limit_pct=0.10,
        stamp_tax_rate=0.0005,
        min_lot_size=100,
        can_short=False,
        margin_ratio=1.0,
        session_hours="09:30-11:30,13:00-15:00",
    ),
    AssetType.MARGIN_SHORT: TradingRule(
        asset_type=AssetType.MARGIN_SHORT,
        t_plus_n=1,
        price_limit_pct=0.10,
        stamp_tax_rate=0.0005,
        min_lot_size=100,
        can_short=True,
        margin_ratio=0.5,
        session_hours="09:30-11:30,13:00-15:00",
    ),
}

_CROSS_BORDER_ETF_PREFIXES: tuple[str, ...] = (
    "513", "159920", "159941", "164824", "501018",
    "159934", "159937", "501021", "159866",
)


def _classify_etf(code: str) -> AssetType:
    """区分境内 ETF (T+1) 与跨境/商品 ETF (T+0)"""
    bare = code.split(".")[0]
    extra = settings.trading_rules.cross_border_etf_prefixes
    all_prefixes = _CROSS_BORDER_ETF_PREFIXES + tuple(extra)
    for prefix in all_prefixes:
        if bare.startswith(prefix):
            return AssetType.ETF_CROSS_BORDER
    return AssetType.ETF_DOMESTIC


def infer_asset_type(code: str) -> AssetType:
    """根据证券代码自动推断资产类型"""
    bare = code.split(".")[0]

    if code.upper().endswith(".HK") or bare.startswith("HK"):
        return AssetType.HK_CONNECT

    if bare.startswith(("688", "689")):
        return AssetType.A_STOCK_STAR

    if bare.startswith(("300", "301")):
        return AssetType.A_STOCK_GEM

    if bare.startswith(("8", "4")) and len(bare) == 6:
        return AssetType.A_STOCK_BSE

    if bare.startswith(("51", "159", "52", "56", "58")):
        return _classify_etf(code)

    if bare.startswith(("11", "12")) and len(bare) == 6:
        return AssetType.CONVERTIBLE_BOND

    return AssetType.A_STOCK_MAIN


def get_trading_rule(code: str) -> TradingRule:
    """便捷函数：由代码直接获取交易规则"""
    return TRADING_RULES[infer_asset_type(code)]
