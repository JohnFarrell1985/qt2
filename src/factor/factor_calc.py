"""自定义因子计算

基于行情数据计算技术类和动量类因子。
"""
import numpy as np
import pandas as pd
from typing import Dict, List

from src.common.logger import get_logger

logger = get_logger(__name__)


def calc_momentum(close_series: pd.Series, window: int = 20) -> pd.Series:
    """动量因子: N日收益率"""
    return close_series.pct_change(window)


def calc_volatility(close_series: pd.Series, window: int = 20) -> pd.Series:
    """波动率因子: N日收益率标准差"""
    returns = close_series.pct_change()
    return returns.rolling(window).std()


def calc_turnover_avg(turnover_series: pd.Series, window: int = 20) -> pd.Series:
    """换手率均值因子"""
    return turnover_series.rolling(window).mean()


def calc_volume_ratio(volume_series: pd.Series, short: int = 5, long: int = 20) -> pd.Series:
    """量比因子: 短期均量/长期均量"""
    short_avg = volume_series.rolling(short).mean()
    long_avg = volume_series.rolling(long).mean()
    return short_avg / long_avg.replace(0, np.nan)


def calc_rsi(close_series: pd.Series, period: int = 14) -> pd.Series:
    """RSI因子"""
    delta = close_series.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def calc_macd_histogram(close_series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> pd.Series:
    """MACD柱状图因子"""
    ema_fast = close_series.ewm(span=fast, adjust=False).mean()
    ema_slow = close_series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line - signal_line


def calc_amplitude(high_series: pd.Series, low_series: pd.Series, close_series: pd.Series, window: int = 20) -> pd.Series:
    """振幅因子: N日平均振幅"""
    daily_amp = (high_series - low_series) / close_series.shift(1)
    return daily_amp.rolling(window).mean()


def calc_all_technical_factors(daily_df: pd.DataFrame) -> pd.DataFrame:
    """对单只股票的日线数据计算所有技术因子

    Args:
        daily_df: 需包含 close, high, low, volume, turnover_rate 列，按日期升序

    Returns:
        DataFrame 附加因子列
    """
    result = daily_df.copy()
    close = result["close"]

    result["mom_5"] = calc_momentum(close, 5)
    result["mom_10"] = calc_momentum(close, 10)
    result["mom_20"] = calc_momentum(close, 20)
    result["mom_60"] = calc_momentum(close, 60)

    result["vol_20"] = calc_volatility(close, 20)
    result["vol_60"] = calc_volatility(close, 60)

    result["rsi_14"] = calc_rsi(close, 14)
    result["macd_hist"] = calc_macd_histogram(close)

    if "volume" in result.columns:
        result["volume_ratio"] = calc_volume_ratio(result["volume"])

    if "turnover_rate" in result.columns:
        result["turnover_avg_20"] = calc_turnover_avg(result["turnover_rate"], 20)

    if "high" in result.columns and "low" in result.columns:
        result["amplitude_20"] = calc_amplitude(result["high"], result["low"], close, 20)

    return result
