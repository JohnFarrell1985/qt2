"""选股策略抽象接口与注册表。

选股服务 (Web UI / workflow) **只按 strategy_id 调度**, 不直接依赖具体筛选实现。
各策略在 ``src/selection/strategies/`` 中继承 ``SelectionStrategy`` 并实现 ``screen``。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Any, Dict, List, Type

from src.common.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class ScreenResult:
    """单次选股/选基结果 (原始代码列表 + 指标快照)。"""

    candidates: List[str]
    snapshots: Dict[str, dict]
    export_top_n: int | None = None


class SelectionStrategy(ABC):
    """选股策略基类 —— 子类实现具体筛选逻辑, 父类/注册表负责统一调度。"""

    @classmethod
    @abstractmethod
    def strategy_id(cls) -> str:
        """策略唯一标识, 与 ``config/strategies/{id}.json`` 对应。"""

    @classmethod
    @abstractmethod
    def screen(
        cls,
        kind: str,
        trade_date: date,
        params: Dict[str, Any] | None = None,
    ) -> ScreenResult:
        """执行选股。``kind``: ``stock`` | ``etf``; ``params`` 为 UI 覆盖参数字典。"""

    @classmethod
    @abstractmethod
    def catalog_entry(cls) -> Dict[str, Any]:
        """供 UI 展示: id, label, description, supports, params(schema+defaults)。"""

    @classmethod
    def format_reason(cls, snap: Dict[str, Any]) -> str:
        """将指标快照转为简短理由 (子类可覆盖)。"""
        bits = []
        tier = snap.get("tier")
        if tier:
            bits.append(f"tier {tier}")
        cross = snap.get("ma5_ma10_cross_state")
        if cross:
            zh = {
                "fresh_cross": "新金叉",
                "touching": "贴合",
                "imminent": "即将金叉",
                "imminent_next": "次日金叉",
            }.get(cross, cross)
            bits.append(zh)
        ds = snap.get("days_since_surge")
        if ds is not None:
            bits.append(f"{int(ds)}日前大涨")
        return " · ".join(bits)


_REGISTRY: Dict[str, Type[SelectionStrategy]] = {}


def register_strategy(cls: Type[SelectionStrategy]) -> Type[SelectionStrategy]:
    """装饰器: 注册策略实现 (未注册的策略不会出现在 UI)。"""
    sid = cls.strategy_id()
    if sid in _REGISTRY:
        logger.warning("策略 %s 重复注册, 后者覆盖前者", sid)
    _REGISTRY[sid] = cls
    return cls


def get_strategy(strategy_id: str) -> Type[SelectionStrategy]:
    if strategy_id not in _REGISTRY:
        available = ", ".join(sorted(_REGISTRY)) or "(无)"
        raise KeyError(f"策略未实现或未启用: {strategy_id} (可用: {available})")
    return _REGISTRY[strategy_id]


def list_registered_strategies() -> List[Type[SelectionStrategy]]:
    return list(_REGISTRY.values())


def strategy_catalog() -> List[Dict[str, Any]]:
    """已注册且可用的策略列表 (供 Web UI 下拉框)。"""
    return [cls.catalog_entry() for cls in _REGISTRY.values()]
