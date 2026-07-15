"""已实现的选股策略 (import 即注册到 ``strategy`` 注册表)。

新增策略: 在此目录添加模块并用 ``@register_strategy`` 装饰, **不要**改选股服务层。
未注册的策略 (如仅有 JSON 预设、逻辑尚在制定中) 不会出现在 UI。
"""
from src.selection.strategies.bear_five_dev import BearFiveDevStrategy  # noqa: F401
from src.selection.strategies.bull_launch import BullLaunchStrategy  # noqa: F401

__all__ = ["BearFiveDevStrategy", "BullLaunchStrategy"]
