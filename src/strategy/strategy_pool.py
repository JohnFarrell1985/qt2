"""策略池管理

管理多策略的生命周期: 创建、训练、评估、激活/暂停。
一个策略 = 一组因子 + LGB模型参数 + 训练好的模型权重。
"""
import json
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

import pandas as pd
from sqlalchemy.dialects.postgresql import insert

from src.common.db import get_session
from src.common.logger import get_logger
from src.data.models import Strategy

logger = get_logger(__name__)


class StrategyPool:
    """策略池管理器"""

    def create_strategy(
        self,
        name: str,
        factor_names: List[str],
        factor_weights: Optional[Dict[str, float]] = None,
        model_params: Optional[Dict[str, Any]] = None,
        description: str = "",
        applicable_macro: Optional[List[str]] = None,
    ) -> int:
        """创建新策略"""
        with get_session() as session:
            stmt = insert(Strategy).values(
                strategy_name=name,
                description=description,
                factor_names_json=json.dumps(factor_names, ensure_ascii=False),
                factor_weights_json=json.dumps(factor_weights or {}, ensure_ascii=False),
                model_params_json=json.dumps(model_params or {}, ensure_ascii=False),
                applicable_macro=",".join(applicable_macro) if applicable_macro else "",
                status="active",
            ).on_conflict_do_update(
                index_elements=["strategy_name"],
                set_={
                    "description": description,
                    "factor_names_json": json.dumps(factor_names, ensure_ascii=False),
                    "factor_weights_json": json.dumps(factor_weights or {}, ensure_ascii=False),
                    "model_params_json": json.dumps(model_params or {}, ensure_ascii=False),
                    "applicable_macro": ",".join(applicable_macro) if applicable_macro else "",
                    "updated_at": datetime.now(),
                },
            ).returning(Strategy.id)
            result = session.execute(stmt)
            strategy_id = result.scalar_one()
            logger.info(f"策略已创建/更新: {name} (id={strategy_id})")
            return strategy_id

    def update_backtest_metrics(
        self,
        strategy_name: str,
        sharpe: float,
        annual_return: float,
        max_drawdown: float,
        ic_mean: float = 0,
        icir: float = 0,
        model_path: str = "",
    ) -> None:
        """更新策略回测指标"""
        with get_session() as session:
            strat = session.query(Strategy).filter_by(strategy_name=strategy_name).first()
            if strat:
                strat.backtest_sharpe = sharpe
                strat.backtest_annual_return = annual_return
                strat.backtest_max_drawdown = max_drawdown
                strat.ic_mean = ic_mean
                strat.icir = icir
                if model_path:
                    strat.model_path = model_path
                strat.updated_at = datetime.now()
                logger.info(f"策略指标已更新: {strategy_name}, sharpe={sharpe:.2f}")

    def list_strategies(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """列出策略"""
        with get_session() as session:
            q = session.query(Strategy)
            if status:
                q = q.filter_by(status=status)
            rows = q.order_by(Strategy.backtest_sharpe.desc().nullslast()).all()
            return [self._to_dict(r) for r in rows]

    def get_strategy(self, name: str) -> Optional[Dict[str, Any]]:
        """获取策略详情"""
        with get_session() as session:
            s = session.query(Strategy).filter_by(strategy_name=name).first()
            return self._to_dict(s) if s else None

    def set_status(self, name: str, status: str) -> None:
        """设置策略状态"""
        with get_session() as session:
            s = session.query(Strategy).filter_by(strategy_name=name).first()
            if s:
                s.status = status
                s.updated_at = datetime.now()

    def get_strategies_for_macro(self, macro_state: str) -> List[Dict[str, Any]]:
        """获取当前宏观环境下可用的策略"""
        all_strats = self.list_strategies(status="active")
        result = []
        for s in all_strats:
            applicable = s.get("applicable_macro", "")
            if not applicable or macro_state in applicable.split(","):
                result.append(s)
        return result

    def rank_strategies(self, metric: str = "backtest_sharpe") -> pd.DataFrame:
        """按指定指标对策略排名"""
        strats = self.list_strategies(status="active")
        if not strats:
            return pd.DataFrame()
        df = pd.DataFrame(strats)
        if metric in df.columns:
            df = df.sort_values(metric, ascending=False).reset_index(drop=True)
        return df

    @staticmethod
    def _to_dict(s: Strategy) -> Dict[str, Any]:
        return {
            "id": s.id,
            "strategy_name": s.strategy_name,
            "description": s.description,
            "factor_names": json.loads(s.factor_names_json) if s.factor_names_json else [],
            "factor_weights": json.loads(s.factor_weights_json) if s.factor_weights_json else {},
            "model_params": json.loads(s.model_params_json) if s.model_params_json else {},
            "model_path": s.model_path,
            "backtest_sharpe": s.backtest_sharpe,
            "backtest_annual_return": s.backtest_annual_return,
            "backtest_max_drawdown": s.backtest_max_drawdown,
            "ic_mean": s.ic_mean,
            "icir": s.icir,
            "status": s.status,
            "applicable_macro": s.applicable_macro or "",
            "created_at": s.created_at.isoformat() if s.created_at else None,
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }
