"""MA 初筛单元测试."""

import pandas as pd

from src.common.config import MaFilterConfig, RankConfig
from src.selection.ma_screener import (
    assign_tier,
    compute_mas,
    passes_ma_filter,
    passes_max_total_gain_filter,
    passes_prior_surge_filter,
    passes_volume_pullback_filter,
    ma_snapshot,
    score_snapshot,
)


def _divergence_closes(n: int = 80) -> pd.Series:
    """末尾两天加速上涨, 使当天满足向上发散."""
    base = [10.0 + i * 0.02 for i in range(n - 2)]
    return pd.Series(base + [base[-1] + 0.5, base[-1] + 1.0])


def _make_bars(
    n: int = 80,
    *,
    vol_today: float = 800_000,
    vol_yday: float = 1_200_000,
    surge_offset: int = 3,
    surge_pct: float = 6.0,
) -> pd.DataFrame:
    closes = _divergence_closes(n)
    volumes = [2_000_000] * (n - 2) + [vol_yday, vol_today]
    change_pct = [0.0] * n
    idx = n - 1 - surge_offset
    change_pct[idx] = surge_pct

    df = pd.DataFrame({
        "trade_date": pd.date_range("2025-01-01", periods=n, freq="B"),
        "open": closes,
        "high": closes + 0.1,
        "low": closes - 0.02,
        "close": closes,
        "volume": volumes,
        "amount": [v * c for v, c in zip(volumes, closes)],
        "change_pct": change_pct,
    })
    ma5 = float(compute_mas(df["close"], [5])[5].iloc[-1])
    df.loc[df.index[-1], "close"] = ma5 * 1.005
    df.loc[df.index[-1], "low"] = ma5
    return df


def test_today_divergence_passes():
    closes = _divergence_closes()
    cfg = MaFilterConfig(
        compute_periods=[5, 10, 20, 50],
        filter_periods=[5, 10, 20],
        require_volume_pullback=False,
    )
    mas = compute_mas(closes, cfg.compute_periods)
    assert passes_ma_filter(mas, cfg)


def test_flat_day_fails_divergence():
    closes = pd.Series([10.0] * 80)
    cfg = MaFilterConfig(
        compute_periods=[5, 10, 20],
        filter_periods=[5, 10, 20],
        require_volume_pullback=False,
    )
    mas = compute_mas(closes, cfg.compute_periods)
    assert not passes_ma_filter(mas, cfg)


def test_prior_surge_requires_big_move_in_window():
    bars = _make_bars(surge_pct=6.0)
    cfg = MaFilterConfig(prior_surge_lookback_days=5, prior_surge_min_pct=5.0)
    assert passes_prior_surge_filter(bars, cfg)

    bars2 = _make_bars(surge_pct=3.0)
    assert not passes_prior_surge_filter(bars2, cfg)


def test_volume_shrink_vs_yesterday():
    bars = _make_bars(vol_today=800_000, vol_yday=1_200_000)
    cfg = MaFilterConfig(
        compute_periods=[5, 10, 20, 50],
        require_volume_pullback=True,
        require_ma5_proximity=False,
        volume_shrink_ratio=1.0,
    )
    mas = compute_mas(bars["close"], cfg.compute_periods)
    assert passes_volume_pullback_filter(bars, mas, cfg)

    bars.loc[bars.index[-1], "volume"] = 1_500_000
    assert not passes_volume_pullback_filter(bars, mas, cfg)


def test_ma5_proximity_within_band():
    bars = _make_bars(vol_today=800_000, vol_yday=1_200_000)
    mas = compute_mas(bars["close"], [5, 10, 20, 50])
    ma5 = float(mas[5].iloc[-1])
    bars.loc[bars.index[-1], "close"] = ma5 * 1.04
    cfg = MaFilterConfig(
        require_volume_pullback=True,
        require_ma5_proximity=True,
        ma5_proximity_pct=5.0,
        require_low_above_ma5=False,
        volume_shrink_ratio=1.0,
    )
    assert passes_volume_pullback_filter(bars, mas, cfg)

    bars.loc[bars.index[-1], "close"] = ma5 * 1.06
    assert not passes_volume_pullback_filter(bars, mas, cfg)


def test_ma5_proximity_optional():
    bars = _make_bars(vol_today=800_000, vol_yday=1_200_000)
    bars.loc[bars.index[-1], "low"] = 0.01
    cfg = MaFilterConfig(
        require_volume_pullback=True,
        require_ma5_proximity=False,
        volume_shrink_ratio=1.0,
    )
    mas = compute_mas(bars["close"], cfg.compute_periods)
    assert passes_volume_pullback_filter(bars, mas, cfg)

    cfg_strict = MaFilterConfig(
        ma5_proximity_pct=2.0,
        require_volume_pullback=True,
        require_ma5_proximity=True,
        require_low_above_ma5=True,
    )
    assert not passes_volume_pullback_filter(bars, mas, cfg_strict)


def test_max_total_gain_filter():
    closes = [10.0] * 70 + [10.0 + i * 0.2 for i in range(11)]
    bars = pd.DataFrame({
        "close": closes,
        "volume": [1_000_000] * 81,
        "low": closes,
        "high": closes,
        "open": closes,
        "amount": closes,
        "change_pct": [0.0] * 81,
    })
    cfg = MaFilterConfig(max_gain_lookback_days=10, max_gain_total_pct=30.0)
    assert passes_max_total_gain_filter(bars, cfg)

    bars_high = bars.copy()
    bars_high.loc[bars_high.index[-1], "close"] = 20.0
    assert not passes_max_total_gain_filter(bars_high, cfg)


def test_ma_snapshot_includes_metrics():
    bars = _make_bars()
    cfg = MaFilterConfig(compute_periods=[5, 10], require_volume_pullback=True)
    mas = compute_mas(bars["close"], cfg.compute_periods)
    snap = ma_snapshot(bars, mas, [5, 10], cfg)
    assert "ma5" in snap and "vol_shrink_ratio" in snap
    assert "max_prior_surge_pct" in snap
    assert "days_since_surge" in snap
    assert "low_ma5_dist_pct" in snap


def test_score_prefers_tight_ma5_and_strong_shrink():
    cfg = MaFilterConfig(max_gain_lookback_days=10, prior_surge_lookback_days=5)
    rank = RankConfig()
    tight = {
        "ma5_dist_pct": 0.5,
        "vol_shrink_ratio": 0.55,
        "gain_10d_pct": 12.0,
        "days_since_surge": 1.0,
    }
    loose = {
        "ma5_dist_pct": 5.0,
        "vol_shrink_ratio": 0.95,
        "gain_10d_pct": 28.0,
        "days_since_surge": 5.0,
    }
    assert score_snapshot(tight, rank, cfg) > score_snapshot(loose, rank, cfg)


def test_assign_tier():
    rank = RankConfig(tier_a_min=75, tier_b_min=60)
    assert assign_tier(80, rank) == "A"
    assert assign_tier(65, rank) == "B"
    assert assign_tier(50, rank) == "C"
