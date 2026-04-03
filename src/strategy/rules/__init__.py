"""Tier 1 规则策略包

导入本包时自动注册所有规则策略到全局 registry。
"""
from src.strategy.rules.cb_dual_low import CBDualLowStrategy
from src.strategy.rules.momentum import MomentumStrategy
from src.strategy.rules.reversal import ReversalStrategy
from src.strategy.rules.industry_rotation import IndustryRotationStrategy
from src.strategy.rules.moving_average import MovingAverageStrategy
from src.strategy.rules.grid_trading import GridTradingStrategy
from src.strategy.rules.low_vol_dividend import LowVolDividendStrategy

__all__ = [
    "CBDualLowStrategy",
    "MomentumStrategy",
    "ReversalStrategy",
    "IndustryRotationStrategy",
    "MovingAverageStrategy",
    "GridTradingStrategy",
    "LowVolDividendStrategy",
]
