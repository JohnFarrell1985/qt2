"""模型评估

IC/ICIR评估、分组收益测试。
"""
import numpy as np
import pandas as pd
from typing import Dict, Any

from src.common.logger import get_logger

logger = get_logger(__name__)


def evaluate_predictions(
    predictions: pd.Series,
    actual_returns: pd.Series,
    n_groups: int = 5,
) -> Dict[str, Any]:
    """评估模型预测结果

    Args:
        predictions: 预测收益率 (MultiIndex: trade_date, code)
        actual_returns: 实际收益率
    """
    common = predictions.index.intersection(actual_returns.index)
    pred = predictions.loc[common]
    actual = actual_returns.loc[common]

    ic = pred.corr(actual, method="spearman")

    dates = pred.index.get_level_values("trade_date").unique()
    daily_ic = []
    for dt in dates:
        try:
            p = pred.xs(dt, level="trade_date")
            a = actual.xs(dt, level="trade_date")
            ci = p.index.intersection(a.index)
            if len(ci) >= 20:
                daily_ic.append(p[ci].corr(a[ci], method="spearman"))
        except (KeyError, ValueError):
            continue

    ic_series = pd.Series(daily_ic)

    labels = [f"G{i+1}" for i in range(n_groups)]
    groups = pd.qcut(pred, n_groups, labels=labels, duplicates="drop")
    group_returns = {}
    for label in labels:
        mask = groups == label
        if mask.sum() > 0:
            group_returns[label] = float(actual[mask].mean())

    long_short = (
        group_returns.get(f"G{n_groups}", 0) - group_returns.get("G1", 0)
    )

    return {
        "overall_ic": round(float(ic), 4),
        "ic_mean": round(float(ic_series.mean()), 4) if len(ic_series) > 0 else None,
        "ic_std": round(float(ic_series.std()), 4) if len(ic_series) > 0 else None,
        "icir": round(float(ic_series.mean() / ic_series.std()), 4) if ic_series.std() > 0 else None,
        "group_returns": group_returns,
        "long_short_return": round(long_short, 4),
        "n_samples": len(common),
        "n_periods": len(daily_ic),
    }
