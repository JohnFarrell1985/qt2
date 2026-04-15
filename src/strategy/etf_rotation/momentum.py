"""动量因子计算 — 三种方法

- 13612W: Keller 加权动量
- r2_return: 趋势质量 (年化收益 × R²)
- dual_momentum: 简单 N 月收益
"""
import numpy as np
import pandas as pd
from scipy import stats

from src.common.logger import get_logger

logger = get_logger(__name__)

TRADING_DAYS_PER_MONTH = 21
TRADING_DAYS_PER_YEAR = 252


def calc_13612w(prices: pd.DataFrame) -> pd.Series:
    """Keller 13612W 加权动量 (SSRN 3002624)

    score = (12×r1 + 4×r3 + 2×r6 + 1×r12) / 4
    其中 rt = current_price / price_t_months_ago - 1

    注: 权重 (12,4,2,1) 非简单平均, 刻意偏向短期窗口
    (Keller 原版设计: 短期动量预测力更强)。除以 4 是对 4 个
    窗口求均值, 而非对权重和 19 归一化。
    """
    if prices.empty:
        return pd.Series(dtype=float)

    current = prices.iloc[-1]
    months = {1: 12, 3: 4, 6: 2, 12: 1}
    result = pd.Series(0.0, index=prices.columns)

    for m, weight in months.items():
        offset = m * TRADING_DAYS_PER_MONTH
        if len(prices) <= offset:
            logger.debug("calc_13612w: 历史数据不足 %d 月 (%d 行), 跳过", m, len(prices))
            continue
        past = prices.iloc[-1 - offset]
        valid = past != 0
        ret = pd.Series(0.0, index=prices.columns)
        ret[valid] = current[valid] / past[valid] - 1.0
        result += weight * ret

    result /= 4.0
    return result


def calc_r2_return(prices: pd.DataFrame, lookback: int = 25) -> pd.Series:
    """趋势质量 = annualized_return × R²

    对 log(price) 做线性回归, R² 衡量趋势稳定性, slope 年化后为收益率。
    """
    if prices.empty or len(prices) < lookback:
        return pd.Series(dtype=float)

    window = prices.iloc[-lookback:]
    x = np.arange(lookback)
    result = {}

    for col in window.columns:
        y = window[col].values
        valid = ~np.isnan(y) & (y > 0)
        if valid.sum() < max(5, lookback // 2):
            result[col] = 0.0
            continue
        log_y = np.log(y[valid])
        x_valid = x[valid]
        slope, _intercept, r_value, _p_value, _std_err = stats.linregress(x_valid, log_y)
        annualized = np.exp(slope * TRADING_DAYS_PER_YEAR) - 1.0
        result[col] = annualized * (r_value ** 2)

    return pd.Series(result)


def calc_dual_momentum(prices: pd.DataFrame, lookback_months: int = 12) -> pd.Series:
    """简单 N 月收益率动量"""
    if prices.empty:
        return pd.Series(dtype=float)

    offset = lookback_months * TRADING_DAYS_PER_MONTH
    if len(prices) <= offset:
        logger.debug("calc_dual_momentum: 历史数据不足 %d 月", lookback_months)
        offset = len(prices) - 1
        if offset <= 0:
            return pd.Series(0.0, index=prices.columns)

    current = prices.iloc[-1]
    past = prices.iloc[-1 - offset]
    valid = past != 0
    result = pd.Series(0.0, index=prices.columns)
    result[valid] = current[valid] / past[valid] - 1.0
    return result


def score(
    prices: pd.DataFrame,
    method: str = "13612w",
    lookback_days: int = 25,
) -> pd.Series:
    """统一入口 — 根据 method 分派到对应计算函数

    Args:
        prices: index=trade_date, columns=codes, values=close
        method: "13612w" | "r2_return" | "dual_momentum"
        lookback_days: 回看天数 (仅 r2_return 使用)

    Returns:
        Series — index=code, values=momentum_score
    """
    dispatchers = {
        "13612w": lambda: calc_13612w(prices),
        "r2_return": lambda: calc_r2_return(prices, lookback=lookback_days),
        "dual_momentum": lambda: calc_dual_momentum(prices),
    }

    func = dispatchers.get(method)
    if func is None:
        raise ValueError(f"未知动量方法: {method}, 可选: {list(dispatchers.keys())}")

    return func()
