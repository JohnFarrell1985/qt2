"""因子预处理

去极值、标准化、中性化等处理步骤。
"""
import numpy as np
import pandas as pd
from typing import Optional

from src.common.logger import get_logger

logger = get_logger(__name__)


def winsorize(series: pd.Series, n_std: float = 3.0) -> pd.Series:
    """MAD去极值"""
    median = series.median()
    mad = (series - median).abs().median()
    mad_e = 1.4826 * mad
    upper = median + n_std * mad_e
    lower = median - n_std * mad_e
    return series.clip(lower, upper)


def standardize(series: pd.Series) -> pd.Series:
    """Z-score标准化"""
    mean = series.mean()
    std = series.std()
    if std == 0 or pd.isna(std):
        return series * 0
    return (series - mean) / std


def neutralize(
    factor: pd.Series,
    industry: pd.Series,
    market_cap: Optional[pd.Series] = None,
) -> pd.Series:
    """行业/市值中性化

    使用OLS回归残差作为中性化后的因子值。
    """
    df = pd.DataFrame({"factor": factor})

    industry_dummies = pd.get_dummies(industry, prefix="ind", drop_first=True)
    X = industry_dummies.copy()

    if market_cap is not None:
        X["ln_cap"] = np.log(market_cap.clip(lower=1))

    X = X.reindex(factor.index).fillna(0)

    from sklearn.linear_model import LinearRegression

    valid = factor.notna() & X.notna().all(axis=1)
    if valid.sum() < 10:
        return factor

    model = LinearRegression()
    model.fit(X.loc[valid], factor.loc[valid])
    predicted = model.predict(X.loc[valid])
    residuals = factor.copy()
    residuals.loc[valid] = factor.loc[valid] - predicted
    return residuals


def preprocess_cross_section(
    factor_df: pd.DataFrame,
    winsorize_std: float = 3.0,
    neutralize_industry: bool = False,
    industry_series: Optional[pd.Series] = None,
    market_cap_series: Optional[pd.Series] = None,
) -> pd.DataFrame:
    """对截面因子数据做标准预处理流水线

    Args:
        factor_df: index=stock_code, columns=factor_names
        winsorize_std: MAD 去极值倍数
        neutralize_industry: 是否启用行业/市值中性化
        industry_series: 行业分类 (申万一级), index=stock_code
        market_cap_series: 总市值, index=stock_code
    """
    result = factor_df.copy()
    for col in result.columns:
        series = result[col].dropna()
        if len(series) < 5:
            continue
        series = winsorize(series, winsorize_std)
        series = standardize(series)
        result[col] = series

    if neutralize_industry and industry_series is not None:
        common = result.index.intersection(industry_series.index)
        if len(common) >= 10:
            for col in result.columns:
                result.loc[common, col] = neutralize(
                    result.loc[common, col],
                    industry_series.loc[common],
                    market_cap_series.loc[common] if market_cap_series is not None else None,
                )

    return result
