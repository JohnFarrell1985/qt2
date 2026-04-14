"""自动因子筛选管线

三步筛选: IC/ICIR 阈值 → 衰减检测 → 相关性去重

P1-21: 多源因子管线 — 因子自动筛选
"""

import numpy as np
import pandas as pd

from src.common.config import settings
from src.common.logger import get_logger
from src.factor.factor_analysis import calc_ic, calc_icir

logger = get_logger(__name__)


class AutoFactorScreen:
    """自动因子筛选器

    读取 FactorPipelineConfig 中的阈值参数, 对因子矩阵执行三步筛选:
      1. IC/ICIR 阈值过滤
      2. IC 衰减半衰期检测
      3. 因子相关性去重
    """

    def __init__(
        self,
        ic_threshold: float | None = None,
        icir_threshold: float | None = None,
        ic_positive_ratio: float | None = None,
        corr_threshold: float | None = None,
        decay_halflife_min: int | None = None,
    ):
        cfg = settings.factor_pipeline
        self.ic_threshold = ic_threshold if ic_threshold is not None else cfg.screen_ic_threshold
        self.icir_threshold = icir_threshold if icir_threshold is not None else cfg.screen_icir_threshold
        self.ic_positive_ratio = ic_positive_ratio if ic_positive_ratio is not None else cfg.screen_ic_positive_ratio
        self.corr_threshold = corr_threshold if corr_threshold is not None else cfg.screen_corr_threshold
        self.decay_halflife_min = (
            decay_halflife_min if decay_halflife_min is not None else cfg.screen_decay_halflife_min
        )

    def screen(
        self,
        factor_matrix: pd.DataFrame,
        forward_returns: pd.Series,
    ) -> list[str]:
        """执行三步因子筛选

        Args:
            factor_matrix: index=MultiIndex(trade_date, stock_code), columns=factor_names
            forward_returns: 同 index 的未来收益率 Series

        Returns:
            通过筛选的因子名称列表
        """
        factor_names = list(factor_matrix.columns)
        logger.info("开始因子筛选: %d 个候选因子", len(factor_names))

        # Step 1: IC/ICIR 阈值过滤
        passed_step1 = self._step1_ic_filter(factor_matrix, forward_returns, factor_names)
        logger.info("Step1 IC/ICIR 过滤: %d → %d", len(factor_names), len(passed_step1))

        if not passed_step1:
            return []

        # Step 2: IC 衰减检测
        passed_step2 = self._step2_decay_filter(factor_matrix, forward_returns, passed_step1)
        logger.info("Step2 衰减过滤: %d → %d", len(passed_step1), len(passed_step2))

        if not passed_step2:
            return []

        # Step 3: 相关性去重
        passed_step3 = self._step3_corr_dedup(factor_matrix, forward_returns, passed_step2)
        logger.info("Step3 相关性去重: %d → %d", len(passed_step2), len(passed_step3))

        return passed_step3

    def _step1_ic_filter(
        self,
        factor_matrix: pd.DataFrame,
        forward_returns: pd.Series,
        factor_names: list[str],
    ) -> list[str]:
        """IC >= threshold AND ICIR >= threshold AND positive_ratio >= threshold"""
        passed: list[str] = []
        dates = factor_matrix.index.get_level_values("trade_date").unique()

        for name in factor_names:
            ic_values = []
            for dt in dates:
                try:
                    f = factor_matrix.xs(dt, level="trade_date")[name]
                    r = forward_returns.xs(dt, level="trade_date")
                    common = f.index.intersection(r.index)
                    if len(common) < 20:
                        continue
                    ic = calc_ic(f[common], r[common])
                    if not np.isnan(ic):
                        ic_values.append(ic)
                except (KeyError, ValueError):
                    continue

            if len(ic_values) < 5:
                continue

            ic_series = pd.Series(ic_values)
            ic_mean = abs(ic_series.mean())
            icir = abs(calc_icir(ic_series))
            pos_ratio = (ic_series > 0).mean() if ic_series.mean() > 0 else (ic_series < 0).mean()

            if ic_mean >= self.ic_threshold and icir >= self.icir_threshold and pos_ratio >= self.ic_positive_ratio:
                passed.append(name)

        return passed

    def _step2_decay_filter(
        self,
        factor_matrix: pd.DataFrame,
        forward_returns: pd.Series,
        factor_names: list[str],
    ) -> list[str]:
        """Rolling IC halflife >= decay_halflife_min"""
        passed: list[str] = []
        dates = sorted(factor_matrix.index.get_level_values("trade_date").unique())

        for name in factor_names:
            ic_values = []
            for dt in dates:
                try:
                    f = factor_matrix.xs(dt, level="trade_date")[name]
                    r = forward_returns.xs(dt, level="trade_date")
                    common = f.index.intersection(r.index)
                    if len(common) < 20:
                        continue
                    ic = calc_ic(f[common], r[common])
                    if not np.isnan(ic):
                        ic_values.append(ic)
                except (KeyError, ValueError):
                    continue

            if len(ic_values) < 10:
                passed.append(name)
                continue

            halflife = self._halflife(pd.Series(ic_values))
            if np.isnan(halflife) or halflife >= self.decay_halflife_min:
                passed.append(name)

        return passed

    def _step3_corr_dedup(
        self,
        factor_matrix: pd.DataFrame,
        forward_returns: pd.Series,
        factor_names: list[str],
    ) -> list[str]:
        """Pearson correlation > corr_threshold → drop lower |IC| factor"""
        if len(factor_names) <= 1:
            return factor_names

        dates = factor_matrix.index.get_level_values("trade_date").unique()
        ic_dict: dict[str, float] = {}
        for name in factor_names:
            ic_values = []
            for dt in dates:
                try:
                    f = factor_matrix.xs(dt, level="trade_date")[name]
                    r = forward_returns.xs(dt, level="trade_date")
                    common = f.index.intersection(r.index)
                    if len(common) < 20:
                        continue
                    ic = calc_ic(f[common], r[common])
                    if not np.isnan(ic):
                        ic_values.append(ic)
                except (KeyError, ValueError):
                    continue
            ic_dict[name] = abs(np.mean(ic_values)) if ic_values else 0.0

        sub = factor_matrix[factor_names]
        flat = sub.reset_index(drop=True)
        corr_matrix = flat.corr(method="pearson")

        dropped: set[str] = set()
        sorted_names = sorted(factor_names, key=lambda n: ic_dict.get(n, 0), reverse=True)

        for i, name_i in enumerate(sorted_names):
            if name_i in dropped:
                continue
            for name_j in sorted_names[i + 1 :]:
                if name_j in dropped:
                    continue
                if abs(corr_matrix.loc[name_i, name_j]) > self.corr_threshold:
                    dropped.add(name_j)
                    logger.debug("去重: %s (IC=%.4f) 被 %s (IC=%.4f) 替代",
                                 name_j, ic_dict[name_j], name_i, ic_dict[name_i])

        return [n for n in sorted_names if n not in dropped]

    @staticmethod
    def _halflife(series: pd.Series) -> float:
        """OLS 拟合指数衰减, 返回半衰期 (天数)

        对 log|IC| 做线性回归: log|IC_t| = a + b*t
        halflife = -ln(2) / b

        若 b >= 0 (未衰减) 返回 inf; 若拟合失败返回 NaN。
        """
        abs_vals = series.abs().replace(0, np.nan).dropna()
        if len(abs_vals) < 5:
            return np.nan

        log_vals = np.log(abs_vals.values)
        t = np.arange(len(log_vals), dtype=float)

        valid = np.isfinite(log_vals)
        if valid.sum() < 5:
            return np.nan

        t_valid = t[valid]
        y_valid = log_vals[valid]

        t_mean = t_valid.mean()
        y_mean = y_valid.mean()
        ss_tt = ((t_valid - t_mean) ** 2).sum()
        if ss_tt < _EPS:
            return np.nan
        slope = ((t_valid - t_mean) * (y_valid - y_mean)).sum() / ss_tt

        if slope >= 0:
            return np.inf

        return -np.log(2) / slope


_EPS = 1e-12
