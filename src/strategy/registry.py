"""策略注册表

所有策略类通过 @register_strategy 装饰器或 StrategyRegistry.register() 注册。
orchestrator / API 通过 registry 按名称实例化策略。
"""
from typing import Dict, Type, Optional, List

from src.common.logger import get_logger
from src.strategy.base import BaseStrategy

logger = get_logger(__name__)


class StrategyRegistry:
    """全局策略注册表 — 单例"""

    _instance: Optional["StrategyRegistry"] = None
    _classes: Dict[str, Type[BaseStrategy]] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def register(self, cls: Type[BaseStrategy]) -> Type[BaseStrategy]:
        key = cls.name
        if not key:
            raise ValueError(f"策略类 {cls.__name__} 必须设置 name 属性")
        self._classes[key] = cls
        logger.debug(f"策略已注册: {key} ({cls.tier})")
        return cls

    def get(self, name: str) -> Optional[Type[BaseStrategy]]:
        return self._classes.get(name)

    def create(self, name: str, config: Optional[dict] = None) -> BaseStrategy:
        cls = self.get(name)
        if cls is None:
            raise KeyError(f"策略未注册: {name}, 可用: {list(self._classes.keys())}")
        return cls(config=config)

    def list_all(self) -> List[Dict]:
        return [
            {"name": cls.name, "tier": cls.tier, "description": cls.description}
            for cls in self._classes.values()
        ]

    def list_by_tier(self, tier: str) -> List[Dict]:
        return [
            {"name": cls.name, "tier": cls.tier, "description": cls.description}
            for cls in self._classes.values()
            if cls.tier == tier
        ]


registry = StrategyRegistry()


def register_strategy(cls: Type[BaseStrategy]) -> Type[BaseStrategy]:
    """装饰器: 自动注册策略类到全局 registry"""
    registry.register(cls)
    return cls
