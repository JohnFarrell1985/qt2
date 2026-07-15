"""前复权校正与除权刷新逻辑测试。"""
import pandas as pd

from src.data.price_adjust import (
    detect_ex_dividend_gap_index,
    repair_mixed_adjustment_bars,
)


def test_detect_ex_dividend_gap():
    bars = pd.DataFrame({
        "close": [24.22, 24.05, 23.12, 23.92, 16.66],
        "change_pct": [None, None, None, 3.46, None],
    })
    assert detect_ex_dividend_gap_index(bars) == 4


def test_repair_mixed_adjustment_bars_ma5():
    bars = pd.DataFrame({
        "trade_date": pd.date_range("2026-07-09", periods=5, freq="B"),
        "open": [24.8, 24.25, 24.0, 23.12, 16.89],
        "high": [24.97, 24.43, 24.09, 24.03, 16.89],
        "low": [23.8, 23.9, 22.9, 22.93, 16.42],
        "close": [24.22, 24.05, 23.12, 23.92, 16.66],
        "change_pct": [None, None, None, 3.46, None],
    })
    fixed = repair_mixed_adjustment_bars(bars)
    ma5 = fixed["close"].tail(5).mean()
    dist = (fixed["close"].iloc[-1] / ma5 - 1) * 100
    assert 16.5 < ma5 < 16.9
    assert -2 < dist < 2


def test_collect_codes_needing_qfq_refresh_merges():
    from src.data.kline_ex_div_refresh import collect_codes_needing_qfq_refresh

    codes = collect_codes_needing_qfq_refresh(ex_lookback_days=90, gap_scan_days=30)
    assert isinstance(codes, list)


def test_build_qfq_refresh_tasks_empty():
    from src.data.kline_ex_div_refresh import build_qfq_refresh_tasks

    assert build_qfq_refresh_tasks([]) == []
