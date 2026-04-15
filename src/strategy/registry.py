"""策略注册表

所有策略类通过 @register_strategy 装饰器或 StrategyRegistry.register() 注册。
orchestrator / API 通过 registry 按名称实例化策略。

P2-35: auto_discover() 自动扫描 src/strategy/ 下所有 BaseStrategy 子类,
替代硬编码 import (OCP — 新增策略只需放入目录, 无需修改 __init__.py)。
"""
import importlib
import pkgutil
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


def auto_discover(package_paths: Optional[List[str]] = None) -> int:
    """P2-35: 自动发现并注册所有 BaseStrategy 子类

    扫描 src/strategy/rules/, src/strategy/scoring/, src/strategy/ml_strategy.py
    下的所有模块, 导入后 @register_strategy 装饰器自动注册。

    Args:
        package_paths: 要扫描的包/模块路径列表, None 则使用默认列表

    Returns:
        新发现的策略数量
    """
    if package_paths is None:
        package_paths = [
            "src.strategy.rules",
            "src.strategy.scoring",
            "src.strategy.ml_strategy",
        ]

    before = len(registry._classes)

    for path in package_paths:
        try:
            mod = importlib.import_module(path)
        except ImportError:
            logger.debug("模块 %s 不存在, 跳过", path)
            continue

        if not hasattr(mod, "__path__"):
            continue

        for _importer, modname, _ispkg in pkgutil.walk_packages(
            mod.__path__, prefix=f"{path}.",
        ):
            try:
                importlib.import_module(modname)
            except Exception as e:
                logger.debug("导入 %s 失败: %s", modname, e)

    discovered = len(registry._classes) - before
    if discovered > 0:
        logger.info("自动发现 %d 个新策略, 当前共 %d 个", discovered, len(registry._classes))
    return discovered
