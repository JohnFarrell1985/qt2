"""策略编排器 v2

完整流程:
  1. 读取当前宏观环境 → 选择策略分配
  2. 通过 registry 实例化策略 → generate_signals (含持仓感知)
  3. PositionMonitor 扫描现有持仓 → 生成止损/止盈/超期卖出信号
  4. SignalArbiter 合并去重 → 解决冲突 → T+1 校验
  5. PositionSizer 分配仓位 → 输出最终 ActionItem 操作清单

散户实战适配:
  - 先卖后买, 卖出信号优先
  - T+1 不可当日卖出
  - 最大持仓 3~5 只
  - 单票 10%~20% 仓位
"""
import json
from datetime import date, datetime
from typing import Dict, Any, List, Optional

from src.common.db import get_session
from src.common.logger import get_logger
from src.data.models import StrategyAllocation, Strategy, InstrumentPool
from src.strategy.strategy_pool import StrategyPool
from src.strategy.instrument_pool import InstrumentPoolManager
from src.strategy.macro_env import MacroEnvironment
from src.strategy.base import Signal, HoldingPosition, ActionItem
from src.strategy.registry import registry
from src.strategy.position_monitor import PositionMonitor
from src.strategy.signal_arbiter import SignalArbiter
from src.strategy.position_sizer import PositionSizer

import src.strategy.rules  # noqa: F401
import src.strategy.scoring  # noqa: F401
import src.strategy.ml_strategy  # noqa: F401

logger = get_logger(__name__)


class StrategyOrchestrator:
    """策略编排器 v2"""

    def __init__(
        self,
        monitor_config: Optional[Dict] = None,
        arbiter_config: Optional[Dict] = None,
        sizer_config: Optional[Dict] = None,
    ):
        self.strategy_pool = StrategyPool()
        self.instrument_pool = InstrumentPoolManager()
        self.macro_env = MacroEnvironment()
        self.monitor = PositionMonitor(monitor_config)
        self.arbiter = SignalArbiter(arbiter_config)
        self.sizer = PositionSizer(sizer_config)

    def execute(
        self,
        trade_date: Optional[date] = None,
        holdings: Optional[List[HoldingPosition]] = None,
        total_capital: float = 1_000_000.0,
        available_cash: float = 0.0,
        price_map: Optional[Dict[str, float]] = None,
    ) -> Dict[str, Any]:
        """完整执行: 策略信号 → 持仓监控 → 仲裁 → 仓位 → 操作清单

        Args:
            trade_date: 交易日 (None=今天)
            holdings: 当前持仓列表
            total_capital: 总资产
            available_cash: 可用现金
            price_map: {code: 当前价格}

        Returns:
            {
                "trade_date": "2025-06-01",
                "macro_state": "range_bound",
                "all_signals": [...],
                "monitor_sells": [...],
                "actions": [ActionItem, ...],
                "summary": {...},
            }
        """
        if trade_date is None:
            trade_date = date.today()
        if holdings is None:
            holdings = []
        if available_cash <= 0:
            available_cash = total_capital * 0.5
        if price_map is None:
            price_map = {}

        macro_state = self.macro_env.get_current_state()
        position_mult = self.macro_env.get_position_multiplier()

        self.sizer.cfg["position_multiplier"] = position_mult

        # Step 1: 各策略生成信号 (含持仓感知)
        all_signals = self._run_strategies(trade_date, macro_state, holdings)

        # Step 2: 持仓监控 → 止损/止盈/超期卖出
        monitor_sells = self.monitor.scan(trade_date, holdings)
        all_signals.extend(monitor_sells)

        # Step 3: 仲裁
        current_pos_value = sum(
            p.current_price * p.quantity for p in holdings if p.current_price > 0
        )
        actions = self.arbiter.arbitrate(
            trade_date=trade_date,
            signals=all_signals,
            holdings=holdings,
            total_position_value=current_pos_value,
            total_capital=total_capital,
        )

        # Step 4: 仓位分配 (仅买入)
        buy_actions = [a for a in actions if a.direction == "buy"]
        sell_actions = [a for a in actions if a.direction == "sell"]

        sell_value = sum(
            _estimate_sell_value(a, holdings, price_map) for a in sell_actions
        )
        cash_after_sells = available_cash + sell_value

        position_after_sells = current_pos_value - sell_value
        current_pct = (position_after_sells / total_capital * 100) if total_capital > 0 else 0
        current_pct = max(0, current_pct)

        if buy_actions:
            buy_actions = self.sizer.allocate(
                buy_actions=buy_actions,
                total_capital=total_capital,
                available_cash=cash_after_sells,
                current_position_pct=current_pct,
                price_map=price_map,
            )

        final_actions = sell_actions + buy_actions

        summary = {
            "trade_date": trade_date.isoformat(),
            "macro_state": macro_state,
            "position_multiplier": position_mult,
            "total_signals": len(all_signals),
            "monitor_sells": len(monitor_sells),
            "final_sells": len(sell_actions),
            "final_buys": len(buy_actions),
            "total_capital": total_capital,
            "available_cash": available_cash,
            "cash_after_sells": cash_after_sells,
            "generated_at": datetime.now().isoformat(),
        }

        logger.info(
            f"[编排] {trade_date}: 卖 {len(sell_actions)} 买 {len(buy_actions)} "
            f"(macro={macro_state}, mult={position_mult})"
        )

        return {
            "trade_date": trade_date.isoformat(),
            "macro_state": macro_state,
            "all_signals": all_signals,
            "monitor_sells": monitor_sells,
            "actions": final_actions,
            "summary": summary,
        }

    def _run_strategies(
        self,
        trade_date: date,
        macro_state: str,
        holdings: List[HoldingPosition],
    ) -> List[Signal]:
        """执行所有激活策略"""
        allocations = self.get_active_allocations(macro_state=macro_state)
        avoid_list = self.macro_env.get_avoid_strategies()

        all_signals: List[Signal] = []

        for alloc in allocations:
            sname = alloc["strategy_name"]
            if sname in avoid_list:
                continue

            strategy_class_key = alloc.get("strategy_class") or sname
            try:
                strat = registry.create(strategy_class_key, config=alloc.get("config"))
            except KeyError:
                logger.warning(f"策略 {strategy_class_key} 未注册, 跳过")
                continue

            universe = alloc.get("pool_codes", [])
            if not universe:
                continue

            try:
                signals = strat.generate_signals(trade_date, universe, holdings)
                all_signals.extend(signals)
            except Exception as e:
                logger.error(f"[编排] 策略 {sname} 执行失败: {e}")

        return all_signals

    # ---- 以下保留原有 CRUD 方法 ----

    def create_allocation(
        self, strategy_name: str, pool_name: str,
        macro_state: str = "", weight: float = 1.0,
    ) -> int:
        strat = self.strategy_pool.get_strategy(strategy_name)
        pool = self.instrument_pool.get_pool(pool_name)
        if not strat:
            raise ValueError(f"策略不存在: {strategy_name}")
        if not pool:
            raise ValueError(f"标的池不存在: {pool_name}")

        with get_session() as session:
            alloc = StrategyAllocation(
                strategy_id=strat["id"],
                pool_id=pool["id"],
                macro_state=macro_state,
                weight=weight,
                is_active="true",
            )
            session.add(alloc)
            session.flush()
            alloc_id = alloc.id
            logger.info(
                f"分配已创建: {strategy_name} → {pool_name} "
                f"(macro={macro_state or 'any'}, weight={weight})"
            )
            return alloc_id

    def get_active_allocations(
        self, macro_state: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        with get_session() as session:
            rows = (
                session.query(StrategyAllocation, Strategy, InstrumentPool)
                .join(Strategy, StrategyAllocation.strategy_id == Strategy.id)
                .join(InstrumentPool, StrategyAllocation.pool_id == InstrumentPool.id)
                .filter(StrategyAllocation.is_active == "true")
                .all()
            )

        result = []
        for alloc, strat, pool in rows:
            if macro_state and alloc.macro_state and alloc.macro_state != macro_state:
                continue
            result.append({
                "allocation_id": alloc.id,
                "strategy_name": strat.strategy_name,
                "strategy_id": strat.id,
                "strategy_tier": strat.strategy_tier or "ml",
                "strategy_class": strat.strategy_class or "",
                "config": json.loads(strat.config_json) if strat.config_json else {},
                "factor_names": json.loads(strat.factor_names_json) if strat.factor_names_json else [],
                "model_path": strat.model_path,
                "pool_name": pool.pool_name,
                "pool_codes": json.loads(pool.codes_json) if pool.codes_json else [],
                "macro_state": alloc.macro_state or "any",
                "weight": alloc.weight,
            })
        return result

    def get_current_plan(self) -> Dict[str, Any]:
        current_state = self.macro_env.get_current_state()
        state_detail = self.macro_env.get_state_detail()
        position_mult = self.macro_env.get_position_multiplier()
        avoid_list = self.macro_env.get_avoid_strategies()
        allocations = self.get_active_allocations(macro_state=current_state)

        plan_items = []
        for alloc in allocations:
            if alloc["strategy_name"] in avoid_list:
                continue
            plan_items.append({
                **alloc,
                "adjusted_weight": alloc["weight"] * position_mult,
            })

        return {
            "macro_state": current_state,
            "macro_label": state_detail.get("label", ""),
            "position_multiplier": position_mult,
            "n_strategies": len(plan_items),
            "allocations": plan_items,
            "avoid_strategies": avoid_list,
            "registered_strategies": registry.list_all(),
            "generated_at": datetime.now().isoformat(),
        }

    def deactivate_allocation(self, allocation_id: int) -> None:
        with get_session() as session:
            alloc = session.query(StrategyAllocation).filter_by(id=allocation_id).first()
            if alloc:
                alloc.is_active = "false"


def _estimate_sell_value(
    action: ActionItem,
    holdings: List[HoldingPosition],
    price_map: Dict[str, float],
) -> float:
    """估算卖出操作回收的现金"""
    for pos in holdings:
        if pos.code == action.code:
            price = price_map.get(action.code, pos.current_price)
            qty = action.target_quantity or pos.quantity
            return price * qty
    return 0.0
