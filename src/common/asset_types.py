"""资产类型枚举与代码推断 — data / strategy 共用, 避免循环依赖"""
from __future__ import annotations

from enum import Enum

from src.common.config import settings

_CROSS_BORDER_ETF_PREFIXES: tuple[str, ...] = (
    "513", "159920", "159941", "164824", "501018",
    "159934", "159937", "501021", "159866",
)


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
