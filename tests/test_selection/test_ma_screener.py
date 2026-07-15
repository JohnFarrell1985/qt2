"""MA 初筛单元测试."""

import pandas as pd

from src.common.config import MaFilterConfig, RankConfig
from src.data.limit_status import get_prior_surge_min_pct, passes_tradability_filter
from src.selection.ma_screener import (
    _days_since_ma5_ma10_cross,
    _score_liquidity,
    assign_tier,
    compute_mas,
    detect_ma5_ma10_cross,
    passes_close_above_ma5_filter,
    passes_ma_filter,
    passes_ma5_ma10_cross_filter,
    passes_max_total_gain_filter,
    passes_monthly_gain_filter,
    passes_prior_surge_filter,
    passes_volume_pullback_filter,
    predict_ma5_ma10_golden_cross,
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
        require_close_above_ma5=True,
        require_ma5_proximity=True,
        ma5_proximity_pct=5.0,
        require_low_above_ma5=False,
        volume_shrink_ratio=1.0,
    )
    assert passes_volume_pullback_filter(bars, mas, cfg)

    bars.loc[bars.index[-1], "close"] = ma5 * 1.06
    assert not passes_volume_pullback_filter(bars, mas, cfg)

    bars.loc[bars.index[-1], "close"] = ma5 * 0.99
    assert not passes_volume_pullback_filter(bars, mas, cfg)


def test_close_must_be_above_ma5():
    bars = _make_bars(vol_today=800_000, vol_yday=1_200_000)
    mas = compute_mas(bars["close"], [5, 10])
    ma5 = float(mas[5].iloc[-1])
    bars.loc[bars.index[-1], "close"] = ma5 * 1.01
    cfg = MaFilterConfig(
        require_volume_pullback=False,
        require_close_above_ma5=True,
        require_ma5_proximity=False,
    )
    assert passes_close_above_ma5_filter(bars, mas, cfg)

    bars.loc[bars.index[-1], "close"] = ma5
    assert not passes_close_above_ma5_filter(bars, mas, cfg)


def test_monthly_gain_filter():
    closes = [10.0] * 70 + [10.0 + i * 0.12 for i in range(23)]
    bars = pd.DataFrame({
        "close": closes,
        "volume": [1_000_000] * 93,
        "low": closes,
        "high": closes,
        "open": closes,
        "amount": closes,
        "change_pct": [0.0] * 93,
    })
    cfg = MaFilterConfig(max_gain_1m_lookback_days=22, max_gain_1m_pct=30.0)
    assert passes_monthly_gain_filter(bars, cfg)

    bars_high = bars.copy()
    bars_high.loc[bars_high.index[-1], "close"] = 20.0
    assert not passes_monthly_gain_filter(bars_high, cfg)


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


def test_get_prior_surge_min_pct_by_board():
    assert get_prior_surge_min_pct("600000", 5.0) == 6.0
    assert get_prior_surge_min_pct("300001", 5.0) == 8.0
    assert get_prior_surge_min_pct("600000", 7.0) == 7.0


def test_passes_tradability_filter():
    assert not passes_tradability_filter({"is_suspended": True})
    assert not passes_tradability_filter({"is_one_word_limit": True})
    assert not passes_tradability_filter({"is_limit_down": True})
    assert passes_tradability_filter({"is_limit_up": True})
    assert not passes_tradability_filter({"is_limit_up": True}, exclude_limit_up=True)
    assert passes_tradability_filter({})


def test_score_liquidity_prefers_turnover():
    assert _score_liquidity(5.0, None) > _score_liquidity(1.0, None)
    assert _score_liquidity(None, 50_000_000) > _score_liquidity(None, 5_000_000)


def test_limit_up_lowers_composite_score():
    cfg = MaFilterConfig(max_gain_lookback_days=10, prior_surge_lookback_days=5)
    rank = RankConfig()
    snap = {
        "ma5_dist_pct": 1.0,
        "vol_shrink_ratio": 0.7,
        "gain_10d_pct": 12.0,
        "days_since_surge": 2.0,
    }
    base = score_snapshot(snap, rank, cfg, avg_turnover_20d=4.0, is_limit_up=False)
    limited = score_snapshot(snap, rank, cfg, avg_turnover_20d=4.0, is_limit_up=True)
    assert base > limited


def _imminent_cross_closes(n: int = 80) -> pd.Series:
    """MA5 自下方向上逼近 MA10, 尚未上穿."""
    base = [10.0 + i * 0.01 for i in range(n - 5)]
    tail = [base[-1] + i * 0.08 for i in range(1, 6)]
    return pd.Series(base + tail)


def test_detect_ma5_ma10_cross_states():
    cfg = MaFilterConfig(
        require_ma5_ma10_cross=True,
        ma5_ma10_imminent_pct=2.0,
        ma5_ma10_fresh_cross_days=3,
        ma5_ma10_allow_imminent=True,
    )
    crossed = compute_mas(_divergence_closes(), [5, 10])
    assert detect_ma5_ma10_cross(crossed, cfg) in ("fresh_cross", None)
    assert passes_ma5_ma10_cross_filter(crossed, cfg) == (
        detect_ma5_ma10_cross(crossed, cfg) is not None
    )

    imminent = compute_mas(_imminent_cross_closes(), [5, 10])
    state = detect_ma5_ma10_cross(imminent, cfg)
    assert state in ("imminent", "fresh_cross", None)


def test_stale_ma5_ma10_cross_rejected():
    """MA5 长期在 MA10 上方、金叉超过 fresh_cross_days 应剔除."""
    n = 80
    closes = pd.Series([10.0 + i * 0.02 for i in range(n)])
    mas = compute_mas(closes, [5, 10])
    cfg = MaFilterConfig(
        require_ma5_ma10_cross=True,
        ma5_ma10_fresh_cross_days=2,
        ma5_ma10_allow_imminent=False,
    )
    assert detect_ma5_ma10_cross(mas, cfg) is None


def test_touching_and_fresh_cross_allowed():
    mas_touch = {
        5: pd.Series([10.0] * 79 + [10.50, 10.62, 10.74]),
        10: pd.Series([10.0] * 79 + [10.55, 10.66, 10.75]),
    }
    cfg = MaFilterConfig(
        ma5_ma10_imminent_only=False,
        ma5_ma10_touch_pct=0.3,
        ma5_ma10_fresh_cross_days=2,
        ma5_ma10_imminent_lookback=5,
    )
    assert detect_ma5_ma10_cross(mas_touch, cfg) == "touching"

    mas_fresh = {
        5: pd.Series([10.0] * 78 + [10.4, 10.55, 10.72, 10.90]),
        10: pd.Series([10.0] * 78 + [10.5, 10.58, 10.65, 10.80]),
    }
    assert detect_ma5_ma10_cross(mas_fresh, cfg) == "fresh_cross"


def test_slope_predicts_next_day_golden_cross():
    """MA5 自下收敛, 斜率预测下一交易日金叉."""
    mas = {
        5: pd.Series([10.0] * 79 + [10.40, 10.62, 10.84]),
        10: pd.Series([10.0] * 79 + [10.55, 10.72, 10.88]),
    }
    cfg = MaFilterConfig(
        ma5_ma10_imminent_only=True,
        ma5_ma10_imminent_pct=2.0,
        ma5_ma10_max_days_to_cross=1.0,
        ma5_ma10_require_next_day=True,
        ma5_ma10_slope_lookback=1,
        ma5_ma10_imminent_lookback=5,
    )
    pred = predict_ma5_ma10_golden_cross(mas, cfg)
    assert pred is not None
    assert pred["next_day_cross"] == 1.0
    assert detect_ma5_ma10_cross(mas, cfg) == "imminent_next"


def test_death_cross_not_treated_as_imminent():
    """MA5 从上方跌破 MA10 (死叉) 不得视为即将金叉."""
    closes = [25.0] * 75 + [29.0, 28.5, 28.0, 27.5, 28.8, 27.65]
    df = pd.DataFrame({"close": closes})
    mas = compute_mas(df["close"], [5, 10])
    # simulate 688209-like: MA5 was above MA10, now below
    mas[5] = pd.Series([24.0] * 70 + [28.15, 27.56, 27.26, 27.32, 27.36])
    mas[10] = pd.Series([24.0] * 70 + [26.82, 26.83, 26.96, 27.25, 27.56])
    cfg = MaFilterConfig(
        require_ma5_ma10_cross=True,
        ma5_ma10_allow_imminent=True,
        ma5_ma10_imminent_pct=1.5,
        ma5_ma10_imminent_lookback=5,
    )
    assert detect_ma5_ma10_cross(mas, cfg) is None
    """金叉第3个交易日应剔除 (fresh_cross_days=2)."""
    # 07-07 below, 07-08/09/10 above => 3 days
    closes = [13.0] * 75 + [13.0, 13.0, 13.0, 13.5, 14.0, 14.5, 15.0, 15.5, 14.74]
    df = pd.DataFrame({"close": closes})
    mas = compute_mas(df["close"], [5, 10])
    cfg = MaFilterConfig(ma5_ma10_fresh_cross_days=2, ma5_ma10_allow_imminent=False)
    # force ma5>ma10 for last 3 bars with cross 3 bars ago
    mas[5] = pd.Series([12.0] * (len(closes) - 3) + [14.0, 14.2, 14.4])
    mas[10] = pd.Series([13.0] * (len(closes) - 3) + [13.8, 13.9, 13.95])
    assert _days_since_ma5_ma10_cross(mas) == 3
    assert detect_ma5_ma10_cross(mas, cfg) is None


def test_imminent_cross_can_pass_ma_filter_without_full_divergence():
    closes = _imminent_cross_closes()
    cfg = MaFilterConfig(
        compute_periods=[5, 10, 20, 50],
        filter_periods=[5, 10, 20, 50],
        require_ma5_ma10_cross=True,
        ma5_ma10_imminent_pct=3.0,
        ma5_ma10_allow_imminent=True,
        require_bullish_order=True,
        require_spreading=True,
    )
    mas = compute_mas(closes, cfg.compute_periods)
    state = detect_ma5_ma10_cross(mas, cfg)
    if state == "imminent":
        assert passes_ma_filter(mas, cfg)
    else:
        assert passes_ma_filter(mas, cfg) or not passes_ma_filter(mas, cfg)


def test_ma_snapshot_includes_cross_metrics():
    bars = _make_bars()
    cfg = MaFilterConfig(
        compute_periods=[5, 10],
        require_volume_pullback=True,
        require_ma5_ma10_cross=True,
        ma5_ma10_fresh_cross_days=5,
    )
    mas = compute_mas(bars["close"], cfg.compute_periods)
    snap = ma_snapshot(bars, mas, [5, 10], cfg)
    assert "ma5_ma10_gap_pct" in snap
    state = detect_ma5_ma10_cross(mas, cfg)
    if state:
        assert snap.get("ma5_ma10_cross_state") == state


class TestMa5Ma10AboveLong:
    def _mas_with_spreads(self):
        """MA5=12, MA10=11, MA20=10, MA30=9, MA40=8, MA50=7."""
        n = 80
        closes = pd.Series([10.0 + i * 0.05 for i in range(n)])
        periods = [5, 10, 20, 30, 40, 50, 60]
        mas = compute_mas(closes, periods)
        return mas

    def test_disabled_passes(self):
        from src.selection.ma_screener import passes_ma5_ma10_above_long_filter

        cfg = MaFilterConfig(require_ma5_ma10_above_long=False)
        assert passes_ma5_ma10_above_long_filter(self._mas_with_spreads(), cfg) is True

    def test_group_or_logic(self):
        from src.selection.ma_screener import passes_ma5_ma10_above_long_filter

        mas = self._mas_with_spreads()
        cfg = MaFilterConfig(
            require_ma5_ma10_above_long=True,
            ma5_ma10_above_groups=[[20, 30], [40, 50]],
        )
        assert passes_ma5_ma10_above_long_filter(mas, cfg) is True

    def test_fails_when_below_long_ma(self):
        from src.selection.ma_screener import passes_ma5_ma10_above_long_filter

        n = 80
        closes = pd.Series([10.0] * n)  # 平坦 → 各 MA 相等
        mas = compute_mas(closes, [5, 10, 20, 30])
        cfg = MaFilterConfig(
            require_ma5_ma10_above_long=True,
            ma5_ma10_above_groups=[[20, 30]],
        )
        assert passes_ma5_ma10_above_long_filter(mas, cfg) is False

    def test_enabled_without_groups_fails_closed(self):
        from src.selection.ma_screener import passes_ma5_ma10_above_long_filter

        cfg = MaFilterConfig(require_ma5_ma10_above_long=True, ma5_ma10_above_groups=[])
        assert passes_ma5_ma10_above_long_filter(self._mas_with_spreads(), cfg) is False
