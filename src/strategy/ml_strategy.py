"""Tier 3 ML 策略

将现有 LGBFactorModel 包装为 BaseStrategy 子类。
预留 XGBoost / CatBoost 接口 — 只需继承 BaseMLStrategy 并覆盖 _create_model。
"""
from datetime import date
from typing import List, Dict, Any, Optional

import pandas as pd

from src.common.config import settings
from src.common.logger import get_logger
from src.strategy.base import BaseStrategy, Signal, HoldingPosition
from src.strategy.registry import register_strategy

logger = get_logger(__name__)


def _default_ml_config():
    s = settings.strat_ml
    return {
        "model_path": "",
        "factor_names": [],
        "top_n": s.top_n,
        "long_threshold": s.long_threshold,
    }


class BaseMLStrategy(BaseStrategy):
    """ML 策略基类 — 子类覆盖 _create_model 切换算法"""

    tier = "ml"
    name = ""
    description = ""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.cfg = {**_default_ml_config(), **(config or {})}
        self._model = None

    def _create_model(self):
        raise NotImplementedError

    def _ensure_model(self):
        if self._model is not None:
            return
        self._model = self._create_model()
        model_path = self.cfg.get("model_path", "")
        if model_path:
            self._model.load(model_path)
            logger.info(f"[{self.name}] 模型已加载: {model_path}")

    def generate_signals(
        self, trade_date: date, universe: List[str],
        holdings: Optional[List[HoldingPosition]] = None,
    ) -> List[Signal]:
        self._ensure_model()

        factor_df = self._load_factors(trade_date, universe)
        if factor_df.empty:
            logger.warning(f"[{self.name}] 因子数据为空")
            return []

        predictions = self._model.predict(factor_df)
        ranked = predictions.sort_values(ascending=False)

        top_n = self.cfg["top_n"]
        threshold = self.cfg["long_threshold"]

        buy_codes = set()
        signals = []
        for rank, (code, score) in enumerate(ranked.items(), 1):
            if rank > top_n:
                break
            if score < threshold:
                continue
            buy_codes.add(code)
            signals.append(Signal(
                trade_date=trade_date,
                code=code,
                direction="buy",
                score=round(float(score), 6),
                strategy_name=self.name,
                strategy_tier=self.tier,
                reason=f"预测收益={score:.4f} rank={rank}",
                stop_loss_pct=settings.strat_ml.stop_loss_pct,
                take_profit_pct=settings.strat_ml.take_profit_pct,
                max_hold_days=settings.strat_ml.max_hold_days,
                trailing_stop_pct=settings.strat_ml.trailing_stop_pct,
            ))

        if holdings:
            for pos in holdings:
                if pos.strategy_name != self.name:
                    continue
                if pos.code in buy_codes:
                    continue
                pred = predictions.get(pos.code, None)
                if pred is not None and pred < threshold:
                    signals.append(Signal(
                        trade_date=trade_date,
                        code=pos.code,
                        direction="sell",
                        score=50.0,
                        quantity=pos.quantity,
                        strategy_name=self.name,
                        strategy_tier=self.tier,
                        reason=f"模型预测收益={pred:.4f}<阈值{threshold}",
                    ))

        logger.info(f"[{self.name}] {trade_date}: 信号 {len(signals)} 只")
        return signals

    def _load_factors(self, trade_date: date, universe: List[str]) -> pd.DataFrame:
        """从 DB 加载截面因子数据"""
        factor_names = self.cfg.get("factor_names", [])
        if not factor_names and self._model:
            factor_names = getattr(self._model, "feature_names", [])

        if not factor_names:
            return pd.DataFrame()

        from src.common.db import get_session
        from src.data.models import FactorValue, FactorMeta

        with get_session() as session:
            metas = session.query(FactorMeta).filter(
                FactorMeta.factor_name.in_(factor_names)
            ).all()
            name_to_id = {m.factor_name: m.factor_id for m in metas}

            rows = session.query(FactorValue).filter(
                FactorValue.trade_date == trade_date,
                FactorValue.code.in_(universe),
                FactorValue.factor_id.in_(list(name_to_id.values())),
            ).all()

        id_to_name = {v: k for k, v in name_to_id.items()}
        records = [
            {"code": r.code, "factor": id_to_name.get(r.factor_id, ""), "value": r.value}
            for r in rows
        ]
        if not records:
            return pd.DataFrame()

        df = pd.DataFrame(records).pivot(index="code", columns="factor", values="value")
        return df.reindex(columns=factor_names).dropna(how="all")


@register_strategy
class LGBStrategy(BaseMLStrategy):
    """LightGBM ML 策略"""

    name = "lgb_ml"
    description = "LightGBM 因子选股模型"

    def _create_model(self):
        from src.ml.lgb_model import LGBFactorModel
        params = self.cfg.get("model_params", {})
        return LGBFactorModel(params=params)


@register_strategy
class XGBoostStrategy(BaseMLStrategy):
    """XGBoost ML 策略 (预留接口)"""

    name = "xgboost_ml"
    description = "XGBoost 因子选股模型 (预留)"

    def _create_model(self):
        try:
            import xgboost as xgb
        except ImportError:
            raise ImportError("xgboost 未安装, 请 pip install xgboost")
        from src.ml.lgb_model import LGBFactorModel
        logger.warning("[xgboost_ml] XGBoost 适配层未实现, 暂用 LGB 替代")
        return LGBFactorModel()


@register_strategy
class CatBoostStrategy(BaseMLStrategy):
    """CatBoost ML 策略 (预留接口)"""

    name = "catboost_ml"
    description = "CatBoost 因子选股模型 (预留)"

    def _create_model(self):
        try:
            import catboost
        except ImportError:
            raise ImportError("catboost 未安装, 请 pip install catboost")
        from src.ml.lgb_model import LGBFactorModel
        logger.warning("[catboost_ml] CatBoost 适配层未实现, 暂用 LGB 替代")
        return LGBFactorModel()
