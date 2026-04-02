"""单因子分析

IC/IR分析、分层回测，评估因子有效性。
"""
import numpy as np
import pandas as pd
from typing import Dict, Any, List, Optional

from src.common.logger import get_logger

logger = get_logger(__name__)


def calc_ic(factor_values: pd.Series, forward_returns: pd.Series) -> float:
    """计算信息系数 (IC) - Rank IC (Spearman相关系数)"""
    valid = factor_values.notna() & forward_returns.notna()
    if valid.sum() < 10:
        return np.nan
    return factor_values[valid].corr(forward_returns[valid], method="spearman")


def calc_ic_series(
    factor_df: pd.DataFrame,
    return_df: pd.DataFrame,
    factor_col: str,
) -> pd.Series:
    """计算IC时间序列

    Args:
        factor_df: MultiIndex(trade_date, code) -> factor_col
        return_df: MultiIndex(trade_date, code) -> 'forward_return'
    """
    dates = factor_df.index.get_level_values("trade_date").unique()
    ic_values = {}

    for dt in dates:
        try:
            f = factor_df.xs(dt, level="trade_date")[factor_col]
            r = return_df.xs(dt, level="trade_date")["forward_return"]
            common = f.index.intersection(r.index)
            if len(common) < 20:
                continue
            ic_values[dt] = calc_ic(f[common], r[common])
        except (KeyError, ValueError):
            continue

    return pd.Series(ic_values, name=f"IC_{factor_col}")


def calc_icir(ic_series: pd.Series) -> float:
    """计算信息比率 ICIR = IC均值 / IC标准差"""
    if ic_series.std() == 0:
        return 0.0
    return ic_series.mean() / ic_series.std()


def group_return_test(
    factor_values: pd.Series,
    forward_returns: pd.Series,
    n_groups: int = 5,
) -> Dict[str, float]:
    """分组回测

    将股票按因子值分为N组，计算各组平均收益。
    """
    valid = factor_values.notna() & forward_returns.notna()
    fv = factor_values[valid]
    fr = forward_returns[valid]

    if len(fv) < n_groups * 5:
        return {}

    labels = [f"G{i+1}" for i in range(n_groups)]
    groups = pd.qcut(fv, n_groups, labels=labels, duplicates="drop")

    result = {}
    for label in labels:
        mask = groups == label
        if mask.sum() > 0:
            result[label] = fr[mask].mean()

    if "G1" in result and f"G{n_groups}" in result:
        result["long_short"] = result[f"G{n_groups}"] - result["G1"]

    return result


def single_factor_report(
    factor_name: str,
    ic_series: pd.Series,
    group_returns: Dict[str, float],
) -> Dict[str, Any]:
    """生成单因子分析报告"""
    return {
        "factor_name": factor_name,
        "ic_mean": round(ic_series.mean(), 4) if len(ic_series) > 0 else None,
        "ic_std": round(ic_series.std(), 4) if len(ic_series) > 0 else None,
        "icir": round(calc_icir(ic_series), 4) if len(ic_series) > 0 else None,
        "ic_positive_ratio": round(
            (ic_series > 0).mean(), 4
        ) if len(ic_series) > 0 else None,
        "group_returns": group_returns,
        "n_periods": len(ic_series),
        "effective": abs(ic_series.mean()) > 0.02 if len(ic_series) > 0 else False,
    }
