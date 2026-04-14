"""因子抽象基类 + 全局注册表

所有因子 (技术/量价/基本面/Alpha158) 继承 BaseFactor 并通过
@register_factor 装饰器或 FactorRegistry.register() 注册。

P1-30: 因子一等公民 — 统一的元数据、自动发现、注册管理框架。
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Type

import pandas as pd

from src.common.logger import get_logger

logger = get_logger(__name__)


class BaseFactor(ABC):
    """因子抽象基类 — 所有可计算因子的一等公民"""

    @property
    @abstractmethod
    def name(self) -> str:
        """因子唯一标识 (如 'mom_20', 'KBAR_open', 'pe_ttm')"""
        ...

    @property
    @abstractmethod
    def category(self) -> str:
        """因子类别 (如 'momentum', 'kbar', 'volume', 'fundamental')"""
        ...

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def data_source(self) -> str:
        """数据源: 'ohlcv' / 'xuntou' / 'jqdata' / 'custom'"""
        return "ohlcv"

    @property
    def lookback_days(self) -> int:
        """计算所需的最少历史天数"""
        return 60

    @property
    def description(self) -> str:
        return ""

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.Series:
        """计算单只标的的因子值

        Args:
            df: 日线 DataFrame, 至少含 OHLCV 列, 按日期升序

        Returns:
            因子值 Series, 与 df 同 index
        """
        ...


class FactorRegistry:
    """因子注册表 — 自动发现 + 元数据管理 (单例)"""

    _instance: Optional["FactorRegistry"] = None
    _factors: Dict[str, BaseFactor] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._factors = {}
        return cls._instance

    def register(self, factor: BaseFactor) -> BaseFactor:
        key = factor.name
        if not key:
            raise ValueError(f"因子类 {type(factor).__name__} 必须设置 name 属性")
        self._factors[key] = factor
        logger.debug(f"因子已注册: {key} ({factor.category})")
        return factor

    def register_class(self, cls: Type[BaseFactor]) -> Type[BaseFactor]:
        """注册因子类 (实例化后注册)"""
        instance = cls()
        self.register(instance)
        return cls

    def get(self, name: str) -> Optional[BaseFactor]:
        return self._factors.get(name)

    def list_all(self) -> List[Dict]:
        return [
            {
                "name": f.name,
                "category": f.category,
                "version": f.version,
                "data_source": f.data_source,
                "lookback_days": f.lookback_days,
                "description": f.description,
            }
            for f in self._factors.values()
        ]

    def list_by_category(self, category: str) -> List[BaseFactor]:
        return [f for f in self._factors.values() if f.category == category]

    def list_names(self, category: Optional[str] = None) -> List[str]:
        if category:
            return [f.name for f in self._factors.values() if f.category == category]
        return list(self._factors.keys())

    def compute_all(
        self,
        df: pd.DataFrame,
        names: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """批量计算指定因子, 返回附加因子列的 DataFrame"""
        result = df.copy()
        targets = names or list(self._factors.keys())
        for name in targets:
            factor = self._factors.get(name)
            if factor is None:
                logger.warning(f"因子未注册: {name}")
                continue
            try:
                result[name] = factor.compute(df)
            except Exception as e:
                logger.warning(f"因子 {name} 计算失败: {e}")
        return result

    def clear(self):
        """清空注册表 (测试用)"""
        self._factors.clear()


factor_registry = FactorRegistry()


def register_factor(cls: Type[BaseFactor]) -> Type[BaseFactor]:
    """装饰器: 自动实例化并注册因子到全局 registry"""
    factor_registry.register_class(cls)
    return cls
