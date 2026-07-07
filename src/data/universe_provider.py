"""统一标的池提供者接口 — PIT 安全查询."""
from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date
from typing import Optional

from sqlalchemy import text

from src.common.logger import get_logger
from src.common.asset_types import AssetType, infer_asset_type
from src.common.db import get_session

logger = get_logger(__name__)


class UniverseProvider(ABC):
    @abstractmethod
    def get_codes(self, trade_date: date, **filters) -> list[str]:
        ...

    @abstractmethod
    def get_asset_type(self, code: str) -> AssetType:
        ...


class AStockUniverseProvider(UniverseProvider):
    def __init__(self):
        from src.data.universe_manager import UniverseManager
        self._mgr = UniverseManager()

    def get_codes(self, trade_date: date, **filters) -> list[str]:
        exclude_st = filters.get("exclude_st", True)
        exclude_suspended = filters.get("exclude_suspended", True)
        return self._mgr.get_tradable(trade_date, exclude_st, exclude_suspended)

    def get_asset_type(self, code: str) -> AssetType:
        return infer_asset_type(code)


def _codes_from_stocks_table(sector_filter: str | None = None) -> list[str]:
    sql = "SELECT code FROM stocks"
    params = {}
    if sector_filter:
        sql += " WHERE sector ILIKE :sector"
        params["sector"] = f"%{sector_filter}%"
    with get_session() as session:
        rows = session.execute(text(sql), params).fetchall()
    return [r[0] for r in rows]


class ETFUniverseProvider(UniverseProvider):
    def get_codes(self, trade_date: date, **filters) -> list[str]:
        return _codes_from_stocks_table("ETF")

    def get_asset_type(self, code: str) -> AssetType:
        return infer_asset_type(code)


class CBUniverseProvider(UniverseProvider):
    def get_codes(self, trade_date: date, **filters) -> list[str]:
        return _codes_from_stocks_table("转债")

    def get_asset_type(self, code: str) -> AssetType:
        return AssetType.CONVERTIBLE_BOND


class HKConnectUniverseProvider(UniverseProvider):
    def get_codes(self, trade_date: date, **filters) -> list[str]:
        return _codes_from_stocks_table("港股通")

    def get_asset_type(self, code: str) -> AssetType:
        return AssetType.HK_CONNECT


class CompositeUniverseProvider(UniverseProvider):
    def __init__(self):
        self._providers: dict[AssetType, UniverseProvider] = {}

    def register(self, asset_type: AssetType, provider: UniverseProvider):
        self._providers[asset_type] = provider

    def get_provider(self, asset_type: AssetType) -> Optional[UniverseProvider]:
        return self._providers.get(asset_type)

    def get_codes(self, trade_date: date, **filters) -> list[str]:
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
