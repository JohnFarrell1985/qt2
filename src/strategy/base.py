"""三档策略统一基类与信号协议

所有策略 (规则/打分/ML) 必须继承 BaseStrategy 并实现 generate_signals。
统一信号输出为 List[Signal], 供回测引擎和交易模块消费。

v2: 增加止损/止盈/持仓天数/流动性等散户实战字段
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import List, Dict, Any, Optional


def _sig_defaults():
    """延迟加载, 避免循环导入"""
    from src.common.config import settings
    return settings.signal_defaults


@dataclass
class Signal:
    """统一交易信号

    核心字段:
        direction: "buy" 买入 / "sell" 卖出 / "hold" 观望
        score: 综合打分, 越高越优先
    风控字段 (策略生成时建议填写, PositionMonitor 会用到):
        stop_loss_pct: 止损比例 (如 -8.0 表示亏损 8% 触发)
        take_profit_pct: 止盈比例 (如 15.0 表示盈利 15% 触发)
        max_hold_days: 最大持仓天数, 超期触发卖出
        trailing_stop_pct: 移动止损回撤比例 (从最高点回落 N% 卖出)
    执行字段:
        target_weight_pct: 目标仓位占比 (0~100), 0=由 PositionSizer 决定
        min_amount: 最低日成交额要求 (万元), 低于此值不交易以保证流动性
        can_trade_date: 最早可交易日 (用于 T+1 约束)

    默认值均来自 .env 中 SIG_* 参数。
    """
    trade_date: date
    code: str
    direction: str

    score: float = 0.0
    quantity: int = 0
    strategy_name: str = ""
    strategy_tier: str = ""
    reason: str = ""

    stop_loss_pct: float = -8.0
    take_profit_pct: float = 15.0
    max_hold_days: int = 10
    trailing_stop_pct: float = 0.0

    target_weight_pct: float = 0.0
    min_amount: float = 5000.0
    can_trade_date: Optional[date] = None


@dataclass
class HoldingPosition:
    """当前持仓快照 — 供策略和 PositionMonitor 使用"""
    code: str
    buy_date: date
    buy_price: float
    quantity: int
    current_price: float = 0.0
    highest_price: float = 0.0
    hold_days: int = 0
    strategy_name: str = ""
    profit_pct: float = 0.0
    can_sell: bool = True


@dataclass
class ActionItem:
    """最终操作指令 — SignalArbiter 输出"""
    code: str
    direction: str          # "buy" / "sell"
    target_quantity: int = 0
    target_amount: float = 0.0
    target_weight_pct: float = 0.0
    priority: int = 0       # 优先级, 1 最高
    signals: List[Signal] = field(default_factory=list)
    reasons: List[str] = field(default_factory=list)


@dataclass
class StrategyConfig:
    """策略通用配置"""
    name: str = ""
    tier: str = ""
    description: str = ""
    params: Dict[str, Any] = field(default_factory=dict)


class BaseStrategy(ABC):
    """三档策略统一基类

    子类需设置:
        tier: str  — "rule" / "scoring" / "ml"
        name: str  — 策略唯一标识

    子类必须实现:
        generate_signals(trade_date, universe, holdings) -> List[Signal]
    """

    tier: str = ""
    name: str = ""
    description: str = ""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}

    @abstractmethod
    def generate_signals(
        self,
        trade_date: date,
        universe: List[str],
        holdings: Optional[List[HoldingPosition]] = None,
    ) -> List[Signal]:
        """给定日期、标的池、当前持仓, 输出交易信号

        Args:
            trade_date: 交易日
            universe: 标的代码列表 (QMT 格式, 如 000001.SZ)
            holdings: 当前持仓列表, None 则不考虑持仓

        Returns:
            信号列表 (含买入和卖出)
        """
        ...

    def get_info(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "tier": self.tier,
            "description": self.description,
            "config": self.config,
        }
