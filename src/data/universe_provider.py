"""统一标的池提供者接口

将 UniverseManager (PIT 回测侧) 和 InstrumentPoolManager (策略侧)
统一为 UniverseProvider 抽象，使每种 AssetType 都有对应的 PIT 提供者。
与 P1-27 TradingRules 联动：共同构成 "标的分类 + 交易规则" 体系。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

from src.common.logger import get_logger
from src.strategy.trading_rules import AssetType, infer_asset_type

logger = get_logger(__name__)


class UniverseProvider(ABC):
    """统一标的池提供者接口"""

    @abstractmethod
    def get_codes(self, trade_date: date, **filters) -> list[str]:
        """返回指定日期可交易的标的代码列表 (PIT 安全)"""
        ...

    @abstractmethod
    def get_asset_type(self, code: str) -> AssetType:
        """返回标的的资产类型"""
        ...


class AStockUniverseProvider(UniverseProvider):
    """A 股 (主板/科创/创业/北交) — 基于 UniverseManager PIT 查询"""

    def __init__(self):
        from src.data.universe_manager import UniverseManager
        self._mgr = UniverseManager()

    def get_codes(self, trade_date: date, **filters) -> list[str]:
        exclude_st = filters.get("exclude_st", True)
        exclude_suspended = filters.get("exclude_suspended", True)
        return self._mgr.get_tradable(trade_date, exclude_st, exclude_suspended)

    def get_asset_type(self, code: str) -> AssetType:
        return infer_asset_type(code)


class ETFUniverseProvider(UniverseProvider):
    """ETF (境内 + 跨境) — 基于 InstrumentPoolManager"""

    def __init__(self, pool_name: str = "ETF基金"):
        self._pool_name = pool_name

    def get_codes(self, trade_date: date, **filters) -> list[str]:
        from src.strategy.instrument_pool import InstrumentPoolManager
        mgr = InstrumentPoolManager()
        return mgr.get_pool_codes(self._pool_name)

    def get_asset_type(self, code: str) -> AssetType:
        return infer_asset_type(code)


class CBUniverseProvider(UniverseProvider):
    """可转债 — 基于 InstrumentPoolManager"""

    def __init__(self, pool_name: str = "沪深转债"):
        self._pool_name = pool_name

    def get_codes(self, trade_date: date, **filters) -> list[str]:
        from src.strategy.instrument_pool import InstrumentPoolManager
        mgr = InstrumentPoolManager()
        return mgr.get_pool_codes(self._pool_name)

    def get_asset_type(self, code: str) -> AssetType:
        return AssetType.CONVERTIBLE_BOND


class HKConnectUniverseProvider(UniverseProvider):
    """港股通 — 基于 InstrumentPoolManager (港股通名单每月更新)"""

    def __init__(self, pool_name: str = "港股通"):
        self._pool_name = pool_name

    def get_codes(self, trade_date: date, **filters) -> list[str]:
        from src.strategy.instrument_pool import InstrumentPoolManager
        mgr = InstrumentPoolManager()
        return mgr.get_pool_codes(self._pool_name)

    def get_asset_type(self, code: str) -> AssetType:
        return AssetType.HK_CONNECT


class CompositeUniverseProvider(UniverseProvider):
    """组合式提供者 — 根据 asset_type 委托到具体 Provider"""

    def __init__(self):
        self._providers: dict[AssetType, UniverseProvider] = {}

    def register(self, asset_type: AssetType, provider: UniverseProvider):
        self._providers[asset_type] = provider

    def get_provider(self, asset_type: AssetType) -> Optional[UniverseProvider]:
        return self._providers.get(asset_type)

    def get_codes(self, trade_date: date, **filters) -> list[str]:
        """返回所有注册 Provider 的标的合集"""
        asset_types = filters.pop("asset_types", None)
        targets = asset_types if asset_types else list(self._providers.keys())
        all_codes: list[str] = []
        for at in targets:
            p = self._providers.get(at)
            if p:
                all_codes.extend(p.get_codes(trade_date, **filters))
        return sorted(set(all_codes))

    def get_asset_type(self, code: str) -> AssetType:
        return infer_asset_type(code)

    @classmethod
    def create_default(cls) -> "CompositeUniverseProvider":
        """创建包含所有默认 Provider 的组合实例"""
        comp = cls()
        a_stock = AStockUniverseProvider()
        for at in (
            AssetType.A_STOCK_MAIN, AssetType.A_STOCK_STAR,
            AssetType.A_STOCK_GEM, AssetType.A_STOCK_BSE,
        ):
            comp.register(at, a_stock)
        comp.register(AssetType.ETF_DOMESTIC, ETFUniverseProvider())
        comp.register(AssetType.ETF_CROSS_BORDER, ETFUniverseProvider())
        comp.register(AssetType.CONVERTIBLE_BOND, CBUniverseProvider())
        comp.register(AssetType.HK_CONNECT, HKConnectUniverseProvider())
        return comp
