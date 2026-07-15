"""熊市五日偏离策略筛选逻辑。"""
import pandas as pd

from src.common.config import MaFilterConfig
from src.selection.ma_screener import (
    passes_close_below_ma5_filter,
    passes_ma5_below_long_filter,
)


def _mas(ma5: float, ma30: float, ma10: float = 10.0) -> dict[int, pd.Series]:
    return {
        5: pd.Series([ma5]),
        10: pd.Series([ma10]),
        30: pd.Series([ma30]),
    }


def _bars(close: float) -> pd.DataFrame:
    return pd.DataFrame({
        "close": [close],
        "low": [close * 0.99],
        "volume": [1000.0],
    })


def test_ma5_below_ma30_passes():
    cfg = MaFilterConfig(
        require_ma5_below_long=True,
        ma5_below_groups=[[30]],
    )
    assert passes_ma5_below_long_filter(_mas(9.0, 10.0), cfg)


def test_ma5_not_below_ma30_fails():
    cfg = MaFilterConfig(
        require_ma5_below_long=True,
        ma5_below_groups=[[30]],
    )
    assert not passes_ma5_below_long_filter(_mas(11.0, 10.0), cfg)


def test_close_below_ma5_within_10pct_fails():
    cfg = MaFilterConfig(
        anchor_ma_period=5,
        require_close_below_ma5=True,
        ma5_below_pct=10.0,
    )
    mas = {5: pd.Series([10.0])}
    bars = _bars(9.1)  # -9%
    assert not passes_close_below_ma5_filter(bars, mas, cfg)


def test_close_below_ma5_at_least_10pct():
    cfg = MaFilterConfig(
        anchor_ma_period=5,
        require_close_below_ma5=True,
        ma5_below_pct=10.0,
    )
    mas = {5: pd.Series([10.0])}
    bars = _bars(8.9)  # -11%
    assert passes_close_below_ma5_filter(bars, mas, cfg)


def test_close_below_ma5_deep_deviation_passes():
    cfg = MaFilterConfig(
        anchor_ma_period=5,
        require_close_below_ma5=True,
        ma5_below_pct=10.0,
    )
    mas = {5: pd.Series([10.0])}
    bars = _bars(8.0)  # -20%
    assert passes_close_below_ma5_filter(bars, mas, cfg)


def test_ma5_below_all_nan_passes():
    """长均线均不可算时不剔除 (新股等)。"""
    cfg = MaFilterConfig(
        require_ma5_below_long=True,
        ma5_below_groups=[[60]],
    )
    mas = {
        5: pd.Series([9.0]),
        60: pd.Series([float("nan")]),
    }
    assert passes_ma5_below_long_filter(mas, cfg)


def test_ma5_below_skips_nan_long_ma():
    """上市不足 N 日时跳过无法计算的长均线, 仅用可算的周期判断。"""
    cfg = MaFilterConfig(
        require_ma5_below_long=True,
        ma5_below_groups=[[60, 10]],
    )
    mas = {
        5: pd.Series([9.0]),
        10: pd.Series([10.0]),
        60: pd.Series([float("nan")]),
    }
    assert passes_ma5_below_long_filter(mas, cfg)


def test_passes_ma_filter_single_period_ok():
    from src.selection.ma_screener import passes_ma_filter

    cfg = MaFilterConfig(
        filter_periods=[5],
        require_bullish_order=False,
        require_rising=False,
        require_spreading=False,
        require_ma5_ma10_cross=False,
    )
    mas = {5: pd.Series([10.0, 10.5, 11.0])}
    assert passes_ma_filter(mas, cfg)


def test_close_above_ma5_fails():
    cfg = MaFilterConfig(
        anchor_ma_period=5,
        require_close_below_ma5=True,
        ma5_below_pct=10.0,
    )
    mas = {5: pd.Series([10.0])}
    bars = _bars(10.5)
    assert not passes_close_below_ma5_filter(bars, mas, cfg)


def test_repair_ex_dividend_bars_fixes_ma5():
    """除权日混用未复权历史时, 校正后偏离度与行情软件一致。"""
    from src.data.price_adjust import repair_mixed_adjustment_bars

    bars = pd.DataFrame({
        "trade_date": pd.date_range("2026-07-09", periods=5, freq="B"),
        "open": [24.8, 24.25, 24.0, 23.12, 16.89],
        "high": [24.97, 24.43, 24.09, 24.03, 16.89],
        "low": [23.8, 23.9, 22.9, 22.93, 16.42],
        "close": [24.22, 24.05, 23.12, 23.92, 16.66],
        "volume": [1.0] * 5,
        "amount": [1.0] * 5,
        "change_pct": [None, None, None, 3.46, None],
    })
    fixed = repair_mixed_adjustment_bars(bars)
    ma5 = fixed["close"].tail(5).mean()
    dist = (fixed["close"].iloc[-1] / ma5 - 1) * 100
    assert 16.5 < ma5 < 16.9
    assert -2 < dist < 2


def test_score_ma5_below_dist_prefers_larger_deviation():
    from src.selection.ma_screener import _score_ma5_below_dist

    assert _score_ma5_below_dist(-18.0, 10.0) > _score_ma5_below_dist(-12.0, 10.0)
    assert _score_ma5_below_dist(-9.0, 10.0) == 0.0
