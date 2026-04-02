"""策略编排器

核心调度: 宏观环境 → 选择策略 → 绑定标的池 → 执行交易信号。
"""
import json
from datetime import date, datetime
from typing import Dict, Any, List, Optional

from src.common.db import get_session
from src.common.logger import get_logger
from src.data.models import StrategyAllocation
from src.strategy.strategy_pool import StrategyPool
from src.strategy.instrument_pool import InstrumentPoolManager
from src.strategy.macro_env import MacroEnvironment

logger = get_logger(__name__)


class StrategyOrchestrator:
    """策略编排器 - 根据宏观环境选策略+标的池"""

    def __init__(self):
        self.strategy_pool = StrategyPool()
        self.instrument_pool = InstrumentPoolManager()
        self.macro_env = MacroEnvironment()

    def create_allocation(
        self,
        strategy_name: str,
        pool_name: str,
        macro_state: str = "",
        weight: float = 1.0,
    ) -> int:
        """创建策略-标的池分配"""
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
        self, macro_state: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """获取当前有效的策略分配

        如果指定 macro_state, 只返回匹配该状态的分配 + 不限状态的分配。
        """
        with get_session() as session:
            q = session.query(StrategyAllocation).filter_by(is_active="true")
            rows = q.all()

        from src.data.models import Strategy, InstrumentPool

        result = []
        for alloc in rows:
            if macro_state and alloc.macro_state and alloc.macro_state != macro_state:
                continue

            with get_session() as session:
                strat = session.query(Strategy).filter_by(id=alloc.strategy_id).first()
                pool = session.query(InstrumentPool).filter_by(id=alloc.pool_id).first()

            if not strat or not pool:
                continue

            result.append({
                "allocation_id": alloc.id,
                "strategy_name": strat.strategy_name,
                "strategy_id": strat.id,
                "factor_names": json.loads(strat.factor_names_json) if strat.factor_names_json else [],
                "model_path": strat.model_path,
                "pool_name": pool.pool_name,
                "pool_codes": json.loads(pool.codes_json) if pool.codes_json else [],
                "macro_state": alloc.macro_state or "any",
                "weight": alloc.weight,
            })

        return result

    def get_current_plan(self) -> Dict[str, Any]:
        """获取基于当前宏观环境的完整执行计划"""
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
            "generated_at": datetime.now().isoformat(),
        }

    def deactivate_allocation(self, allocation_id: int) -> None:
        """停用分配"""
        with get_session() as session:
            alloc = session.query(StrategyAllocation).filter_by(id=allocation_id).first()
            if alloc:
                alloc.is_active = "false"
