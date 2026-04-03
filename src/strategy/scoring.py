"""Tier 2 多因子打分引擎

支持两种权重模式:
  - equal:  各因子等权
  - ic:     按滚动 IC 值加权 (信息系数越高, 因子权重越大)

打分流程: 截面因子 → 标准化 → 加权求和 → 排序 → 信号
"""
from datetime import date
from typing import List, Dict, Any, Optional

import numpy as np
import pandas as pd

from src.common.config import settings
from src.common.logger import get_logger
from src.strategy.base import BaseStrategy, Signal, HoldingPosition
from src.strategy.registry import register_strategy

logger = get_logger(__name__)


def _default_config():
    s = settings.strat_scoring
    return {
        "factor_names": [],
        "weight_mode": "equal",
        "ic_window": s.ic_window,
        "top_n": s.top_n,
        "neutralize_industry": s.neutralize_industry,
    }


def _zscore(s: pd.Series) -> pd.Series:
    """截面 Z-Score 标准化, 去极值 (MAD 3 倍)"""
    median = s.median()
    mad = (s - median).abs().median()
    if mad == 0:
        return pd.Series(0.0, index=s.index)
    upper = median + 3 * 1.4826 * mad
    lower = median - 3 * 1.4826 * mad
    clipped = s.clip(lower, upper)
    mean = clipped.mean()
    std = clipped.std()
    if std == 0:
        return pd.Series(0.0, index=s.index)
    return (clipped - mean) / std


def _calc_ic(factor_values: pd.Series, forward_returns: pd.Series) -> float:
    """计算截面 IC (Spearman 秩相关)"""
    common = factor_values.dropna().index.intersection(forward_returns.dropna().index)
    if len(common) < 10:
        return 0.0
    return float(factor_values[common].corr(forward_returns[common], method="spearman"))


@register_strategy
class MultiFactorScoringStrategy(BaseStrategy):
    """多因子等权打分策略"""

    tier = "scoring"
    name = "multifactor_equal"
    description = "多因子打分(等权): 因子标准化后等权加总排序"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.cfg = {**_default_config(), **(config or {}), "weight_mode": "equal"}

    def generate_signals(
        self, trade_date: date, universe: List[str],
        holdings: Optional[List[HoldingPosition]] = None,
    ) -> List[Signal]:
        return _generate_scoring_signals(self, trade_date, universe, holdings)


@register_strategy
class ICWeightedScoringStrategy(BaseStrategy):
    """多因子 IC 加权打分策略"""

    tier = "scoring"
    name = "multifactor_ic"
    description = "多因子打分(IC加权): 按滚动IC加权因子"

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.cfg = {**_default_config(), **(config or {}), "weight_mode": "ic"}

    def generate_signals(
        self, trade_date: date, universe: List[str],
        holdings: Optional[List[HoldingPosition]] = None,
    ) -> List[Signal]:
        return _generate_scoring_signals(self, trade_date, universe, holdings)


def _generate_scoring_signals(
    strategy: BaseStrategy, trade_date: date, universe: List[str],
    holdings: Optional[List[HoldingPosition]] = None,
) -> List[Signal]:
    """打分策略的通用信号生成逻辑"""
    cfg = strategy.cfg
    factor_names = cfg.get("factor_names", [])

    if not factor_names:
        logger.warning(f"[{strategy.name}] 未配置因子列表")
        return []

    factor_df = _load_factor_data(trade_date, universe, factor_names)
    if factor_df.empty:
        logger.warning(f"[{strategy.name}] 因子数据为空")
        return []

    normed = factor_df.apply(_zscore, axis=0)

    if cfg["weight_mode"] == "ic":
        weights = _load_ic_weights(trade_date, factor_names, cfg["ic_window"])
    else:
        weights = pd.Series(1.0 / len(factor_names), index=factor_names)

    weights = weights.reindex(normed.columns).fillna(0)
    if weights.sum() == 0:
        weights = pd.Series(1.0 / len(factor_names), index=factor_names)

    composite = normed.dot(weights)
    composite = composite.sort_values(ascending=False)

    top_n = cfg["top_n"]
    buy_codes = set()
    signals = []
    for rank, (code, score) in enumerate(composite.head(top_n).items(), 1):
        buy_codes.add(code)
        signals.append(Signal(
            trade_date=trade_date,
            code=code,
            direction="buy",
            score=round(float(score), 4),
            strategy_name=strategy.name,
            strategy_tier=strategy.tier,
            reason=f"综合得分={score:.3f} rank={rank}",
            stop_loss_pct=settings.strat_scoring.stop_loss_pct,
            take_profit_pct=settings.strat_scoring.take_profit_pct,
            max_hold_days=settings.strat_scoring.max_hold_days,
            trailing_stop_pct=settings.strat_scoring.trailing_stop_pct,
        ))

    if holdings:
        for pos in holdings:
            if pos.strategy_name != strategy.name:
                continue
            if pos.code in buy_codes:
                continue
            if pos.code in composite.index:
                rank = int((composite > composite[pos.code]).sum()) + 1
                if rank > len(composite) * 0.7:
                    signals.append(Signal(
                        trade_date=trade_date,
                        code=pos.code,
                        direction="sell",
                        score=50.0,
                        quantity=pos.quantity,
                        strategy_name=strategy.name,
                        strategy_tier=strategy.tier,
                        reason=f"因子排名下降至 {rank}/{len(composite)}, 不再入选",
                    ))

    logger.info(
        f"[{strategy.name}] {trade_date}: "
        f"{len(factor_names)}因子, {len(factor_df)}只股, 信号{len(signals)}只"
    )
    return signals


def _load_factor_data(
    trade_date: date, universe: List[str], factor_names: List[str],
) -> pd.DataFrame:
    """从 DB 加载截面因子数据"""
    from src.common.db import get_session
    from src.data.models import FactorValue, FactorMeta

    with get_session() as session:
        metas = session.query(FactorMeta).filter(
            FactorMeta.factor_name.in_(factor_names)
        ).all()
        name_to_id = {m.factor_name: m.factor_id for m in metas}

        factor_ids = list(name_to_id.values())
        if not factor_ids:
            return pd.DataFrame()

        rows = session.query(FactorValue).filter(
            FactorValue.trade_date == trade_date,
            FactorValue.code.in_(universe),
            FactorValue.factor_id.in_(factor_ids),
        ).all()

    id_to_name = {v: k for k, v in name_to_id.items()}
    records = []
    for r in rows:
        records.append({
            "code": r.code,
            "factor": id_to_name.get(r.factor_id, ""),
            "value": r.value,
        })

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records).pivot(index="code", columns="factor", values="value")
    return df.reindex(columns=factor_names).dropna(how="all")


def _load_ic_weights(
    trade_date: date, factor_names: List[str], window: int,
) -> pd.Series:
    """计算滚动 IC 均值作为因子权重

    从最近 window 个交易日中取各因子的 IC, 取均值。
    权重 = IC均值的绝对值归一化。
    """
    from src.common.db import get_session
    from src.data.models import FactorValue, FactorMeta, StockDaily
    from sqlalchemy import func

    with get_session() as session:
        recent_dates = (
            session.query(StockDaily.trade_date)
            .filter(StockDaily.trade_date <= trade_date)
            .distinct()
            .order_by(StockDaily.trade_date.desc())
            .limit(window + 5)
            .all()
        )
    dates = sorted([r[0] for r in recent_dates])
    if len(dates) < 5:
        return pd.Series(dtype=float)

    ic_values: Dict[str, List[float]] = {f: [] for f in factor_names}

    for i in range(len(dates) - 1):
        d = dates[i]
        d_next = dates[i + 1] if i + 1 < len(dates) else None
        if d_next is None:
            continue

        try:
            with get_session() as session:
                metas = session.query(FactorMeta).filter(
                    FactorMeta.factor_name.in_(factor_names)
                ).all()
                name_to_id = {m.factor_name: m.factor_id for m in metas}

                factor_rows = session.query(FactorValue).filter(
                    FactorValue.trade_date == d,
                    FactorValue.factor_id.in_(list(name_to_id.values())),
                ).all()

                ret_rows = session.query(
                    StockDaily.code,
                    StockDaily.change_pct,
                ).filter(StockDaily.trade_date == d_next).all()

            ret_map = {r.code: r.change_pct for r in ret_rows if r.change_pct is not None}
            fwd_ret = pd.Series(ret_map)

            id_to_name = {v: k for k, v in name_to_id.items()}
            for fname in factor_names:
                fid = name_to_id.get(fname)
                if fid is None:
                    continue
                vals = {r.code: r.value for r in factor_rows if r.factor_id == fid and r.value is not None}
                if len(vals) < 20:
                    continue
                fv = pd.Series(vals)
                ic = _calc_ic(fv, fwd_ret)
                ic_values[fname].append(ic)
        except Exception:
            continue

    ic_means = {}
    for fname, ics in ic_values.items():
        if ics:
            ic_means[fname] = np.mean(ics)
        else:
            ic_means[fname] = 0.0

    s = pd.Series(ic_means)
    abs_sum = s.abs().sum()
    if abs_sum > 0:
        return s.abs() / abs_sum
    return pd.Series(1.0 / len(factor_names), index=factor_names)
