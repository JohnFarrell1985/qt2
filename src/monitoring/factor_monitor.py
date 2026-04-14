"""因子衰减监控

核心 KPI:
  - 滚动 IC (Information Coefficient): 因子值与未来收益的截面 rank correlation
  - ICIR (IC / std(IC)): IC 的稳定性
  - PSI (Population Stability Index): 因子分布漂移
  - 拥挤度: HHI、成交量异常、因子间相关性

References:
  - Advances in Financial Machine Learning, Ch.7
  - stockalpha.ai: Concept Drift Alarms for Quant Signals
  - microalphas.com: Signal Decay Patterns
"""
import numpy as np
import pandas as pd
from scipy import stats

from src.common.config import settings
from src.common.logger import get_logger

logger = get_logger(__name__)

_EPS = 1e-10


def rolling_ic(
    factor_values: pd.Series,
    forward_returns: pd.Series,
    dates: pd.Series,
    window: int = 20,
) -> pd.Series:
    """Calculate rolling cross-sectional IC (Spearman rank correlation).

    For each date, computes rank correlation between factor values and
    forward returns across all stocks on that date. Then returns a
    rolling mean over *window* dates.
    """
    df = pd.DataFrame({
        "factor": factor_values.values,
        "ret": forward_returns.values,
        "date": pd.to_datetime(dates).values,
    })

    def _spearman(group):
        if len(group) < 3:
            return np.nan
        corr, _ = stats.spearmanr(group["factor"], group["ret"])
        return corr

    daily_ic = df.groupby("date").apply(_spearman, include_groups=False)
    daily_ic = daily_ic.sort_index()
    return daily_ic.rolling(window=window, min_periods=1).mean()


def calc_icir(ic_series: pd.Series) -> float:
    """ICIR = mean(IC) / std(IC). Higher is better (> 0.5 is decent)."""
    std = ic_series.std()
    if std < _EPS:
        return 0.0
    return float(ic_series.mean() / std)


def calc_psi(
    reference: np.ndarray,
    current: np.ndarray,
    n_bins: int = 10,
) -> float:
    """Population Stability Index.

    PSI < 0.1  → stable
    PSI 0.1–0.2 → moderate shift
    PSI > 0.2  → significant shift
    """
    ref = np.asarray(reference, dtype=float)
    cur = np.asarray(current, dtype=float)

    combined = np.concatenate([ref, cur])
    bins = np.percentile(combined, np.linspace(0, 100, n_bins + 1))
    bins[0] = -np.inf
    bins[-1] = np.inf
    bins = np.unique(bins)

    ref_counts = np.histogram(ref, bins=bins)[0].astype(float)
    cur_counts = np.histogram(cur, bins=bins)[0].astype(float)

    ref_pct = ref_counts / ref_counts.sum()
    cur_pct = cur_counts / cur_counts.sum()

    ref_pct = np.clip(ref_pct, _EPS, None)
    cur_pct = np.clip(cur_pct, _EPS, None)

    psi = float(np.sum((cur_pct - ref_pct) * np.log(cur_pct / ref_pct)))
    return psi


class FactorDecayMonitor:
    """Monitors factor predictive power over time."""

    def __init__(
        self,
        ic_warning: float = settings.factor_monitor.ic_warning_threshold,
        icir_warning: float = settings.factor_monitor.icir_threshold,
        psi_warning: float = settings.factor_monitor.psi_warning,
        psi_critical: float = settings.factor_monitor.psi_critical,
        ic_window: int = settings.factor_monitor.ic_window,
    ):
        self.ic_warning = ic_warning
        self.icir_warning = icir_warning
        self.psi_warning = psi_warning
        self.psi_critical = psi_critical
        self.ic_window = ic_window

    def check_decay(
        self,
        factor_values: pd.Series,
        forward_returns: pd.Series,
        dates: pd.Series,
        reference_values: np.ndarray | None = None,
    ) -> dict:
        """Comprehensive factor decay check.

        Returns
        -------
        dict with keys: ic_mean, icir, psi, level (normal/warning/critical), action
        """
        ic_series = rolling_ic(factor_values, forward_returns, dates, self.ic_window)
        ic_mean = float(ic_series.iloc[-1]) if len(ic_series) > 0 else 0.0
        icir = calc_icir(ic_series)

        psi = 0.0
        if reference_values is not None:
            psi = calc_psi(reference_values, factor_values.values)

        level = "normal"
        action = "continue"

        if psi >= self.psi_critical:
            level = "critical"
            action = "retrain_model"
            logger.warning("因子分布严重漂移 PSI=%.4f, 建议立即重训模型", psi)
        elif psi >= self.psi_warning or abs(ic_mean) < self.ic_warning or icir < self.icir_warning:
            level = "warning"
            action = "review_factor"
            logger.warning(
                "因子衰减预警 IC=%.4f, ICIR=%.4f, PSI=%.4f",
                ic_mean, icir, psi,
            )
        else:
            logger.info("因子状态正常 IC=%.4f, ICIR=%.4f, PSI=%.4f", ic_mean, icir, psi)

        return {
            "ic_mean": ic_mean,
            "icir": icir,
            "psi": psi,
            "level": level,
            "action": action,
        }


class CrowdingDetector:
    """Detects factor crowding via concentration and co-movement metrics."""

    def herfindahl_index(self, weights: np.ndarray) -> float:
        """HHI for portfolio concentration. Range [1/N, 1]."""
        w = np.asarray(weights, dtype=float)
        total = w.sum()
        if total < _EPS:
            return 0.0
        w_norm = w / total
        return float(np.sum(w_norm ** 2))

    def volume_anomaly(self, recent_volume: float, historical_mean: float) -> float:
        """Volume ratio: recent / historical. > 2.0 suggests crowding."""
        if historical_mean < _EPS:
            return 0.0
        return recent_volume / historical_mean

    def cross_factor_correlation(self, factor_a: pd.Series, factor_b: pd.Series) -> float:
        """Spearman correlation between two factor series."""
        a = factor_a.dropna()
        b = factor_b.dropna()
        common = a.index.intersection(b.index)
        if len(common) < 3:
            return 0.0
        corr, _ = stats.spearmanr(a.loc[common], b.loc[common])
        return float(corr) if not np.isnan(corr) else 0.0

    def detect(
        self,
        weights: np.ndarray,
        recent_vol: float,
        hist_vol: float,
        factor_a: pd.Series | None = None,
        factor_b: pd.Series | None = None,
    ) -> dict:
        """Comprehensive crowding check.

        Returns
        -------
        dict with keys: hhi, volume_ratio, cross_corr, crowding_score, action
        """
        hhi = self.herfindahl_index(weights)
        vol_ratio = self.volume_anomaly(recent_vol, hist_vol)

        cross_corr = 0.0
        if factor_a is not None and factor_b is not None:
            cross_corr = self.cross_factor_correlation(factor_a, factor_b)

        crowding_score = 0.4 * min(hhi * 5, 1.0) + 0.3 * min(vol_ratio / 3.0, 1.0) + 0.3 * abs(cross_corr)
        crowding_score = float(np.clip(crowding_score, 0, 1))

        if crowding_score > 0.7:
            action = "reduce_exposure"
        elif crowding_score > 0.4:
            action = "monitor_closely"
        else:
            action = "normal"

        return {
            "hhi": hhi,
            "volume_ratio": vol_ratio,
            "cross_corr": cross_corr,
            "crowding_score": crowding_score,
            "action": action,
        }
