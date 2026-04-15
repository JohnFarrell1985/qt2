"""轻量级事件总线 (P2-34)

基于 blinker 的进程内信号机制, 实现模块间松耦合通信。
降级方案: blinker 不可用时回退到简单回调列表。

使用示例:
    from src.common.event_bus import events, data_collected

    # 发布事件
    data_collected.send(sender="akshare_collector", codes=["000001.SZ"])

    # 订阅事件
    @data_collected.connect
    def on_data_collected(sender, **kwargs):
        print(f"数据采集完成: {sender}, {kwargs}")
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from src.common.logger import get_logger

logger = get_logger(__name__)

try:
    from blinker import Namespace

    _USE_BLINKER = True
    _ns = Namespace()
except ImportError:
    _USE_BLINKER = False
    _ns = None
    logger.info("blinker 不可用, 事件总线使用简易回调实现")


class _SimpleSignal:
    """blinker 不可用时的最小替代"""

    def __init__(self, name: str):
        self.name = name
        self._receivers: List[Callable] = []

    def connect(self, func: Callable) -> Callable:
        self._receivers.append(func)
        return func

    def send(self, sender: Any = None, **kwargs: Any) -> None:
        for fn in self._receivers:
            try:
                fn(sender, **kwargs)
            except Exception as e:
                logger.error("事件 %s 处理异常: %s", self.name, e)

    def disconnect(self, func: Callable) -> None:
        self._receivers = [f for f in self._receivers if f is not func]


class _SimpleNamespace:
    """blinker Namespace 替代"""

    def __init__(self):
        self._signals: Dict[str, _SimpleSignal] = {}

    def signal(self, name: str) -> _SimpleSignal:
        if name not in self._signals:
            self._signals[name] = _SimpleSignal(name)
        return self._signals[name]


if not _USE_BLINKER:
    _ns = _SimpleNamespace()

events = _ns

data_collected = events.signal("data_collected")
data_cleaned = events.signal("data_cleaned")
factor_computed = events.signal("factor_computed")
model_predicted = events.signal("model_predicted")
signal_generated = events.signal("signal_generated")
trade_executed = events.signal("trade_executed")
risk_alert = events.signal("risk_alert")
flywheel_queued = events.signal("flywheel_queued")
