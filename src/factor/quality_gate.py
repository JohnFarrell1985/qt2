"""因子质量门控 (alphalens 风格)

P1-34: 基于 IC 分析 + 分层回测的标准因子质量门控。
作为因子"入库前的质量检查", 避免低质量因子进入 ML 训练。

不直接依赖 alphalens 库, 使用自研等价实现 (兼容性更好)。
"""
from typing import Optional

import numpy as np
import pandas as pd

from src.common.logger import get_logger
from src.factor.factor_analysis import calc_ic_series, calc_icir, group_return_test

logger = get_logger(__name__)


class FactorQualityGate:
    """因子质量门控 — IC + 分层回测 + 单调性"""

    DEFAULT_CRITERIA = {
        "ic_mean_abs": 0.025,
        "icir_abs": 0.3,
        "quantile_spread": 0.003,
        "monotonicity": 0.5,
    }

    def __init__(self, criteria: Optional[dict] = None):
        self.criteria = {**self.DEFAULT_CRITERIA, **(criteria or {})}

    def evaluate(
        self,
        factor_df: pd.DataFrame,
        return_df: pd.DataFrame,
        factor_col: str,
        n_groups: int = 5,
    ) -> dict:
        """评估单个因子质量

        Args:
            factor_df: MultiIndex(trade_date, code) -> factor columns
            return_df: MultiIndex(trade_date, code) -> 'forward_return'
            factor_col: 待评估因子列名
            n_groups: 分层数

        Returns:
            dict with ic_mean, ic_std, icir, quantile_spread, monotonicity, passed
        """
        ic_series = calc_ic_series(factor_df, return_df, factor_col)

        if len(ic_series) < 5:
            return {
                "factor_name": factor_col,
                "ic_mean": None,
                "ic_std": None,
                "icir": None,
                "quantile_spread": None,
                "monotonicity": None,
                "passed": False,
                "reason": "IC 序列过短",
            }

        ic_mean = ic_series.mean()
        ic_std = ic_series.std()
        icir = calc_icir(ic_series)

        dates = factor_df.index.get_level_values("trade_date").unique()
        spreads = []
        mono_scores = []

        for dt in dates:
            try:
                f = factor_df.xs(dt, level="trade_date")[factor_col]
                r = return_df.xs(dt, level="trade_date")["forward_return"]
                common = f.index.intersection(r.index)
                if len(common) < n_groups * 5:
                    continue
                grp = group_return_test(f[common], r[common], n_groups=n_groups)
                if f"G{n_groups}" in grp and "G1" in grp:
                    spreads.append(grp[f"G{n_groups}"] - grp["G1"])

                group_returns = [
                    grp.get(f"G{i+1}", 0) for i in range(n_groups)
                    if f"G{i+1}" in grp
                ]
                if len(group_returns) >= n_groups:
                    mono = self._monotonicity_score(group_returns)
                    mono_scores.append(mono)
            except (KeyError, ValueError):
                continue

        avg_spread = float(np.mean(spreads)) if spreads else 0.0
        avg_mono = float(np.mean(mono_scores)) if mono_scores else 0.0

        passed = True
        reason = []
        if abs(ic_mean) < self.criteria["ic_mean_abs"]:
            passed = False
            reason.append(f"|IC|={abs(ic_mean):.4f} < {self.criteria['ic_mean_abs']}")
        if abs(icir) < self.criteria["icir_abs"]:
            passed = False
            reason.append(f"|ICIR|={abs(icir):.4f} < {self.criteria['icir_abs']}")
        if abs(avg_spread) < self.criteria["quantile_spread"]:
            passed = False
            reason.append(f"spread={avg_spread:.5f} < {self.criteria['quantile_spread']}")
        if avg_mono < self.criteria["monotonicity"]:
            passed = False
            reason.append(f"mono={avg_mono:.3f} < {self.criteria['monotonicity']}")

        result = {
            "factor_name": factor_col,
            "ic_mean": round(float(ic_mean), 5),
            "ic_std": round(float(ic_std), 5),
            "icir": round(float(icir), 4),
            "ic_positive_ratio": round(float((ic_series > 0).mean()), 4),
            "quantile_spread": round(avg_spread, 6),
            "monotonicity": round(avg_mono, 4),
            "passed": passed,
            "reason": "; ".join(reason) if reason else "all criteria met",
        }

        logger.debug(
            f"[QualityGate] {factor_col}: IC={ic_mean:.4f}, ICIR={icir:.3f}, "
            f"spread={avg_spread:.5f}, mono={avg_mono:.3f} → {'✓' if passed else '✗'}"
        )
        return result

    def batch_evaluate(
        self,
        factor_df: pd.DataFrame,
        return_df: pd.DataFrame,
        factor_cols: Optional[list[str]] = None,
        n_groups: int = 5,
    ) -> list[dict]:
        """批量评估多个因子"""
        cols = factor_cols or [
            c for c in factor_df.columns if c != "forward_return"
        ]
        results = []
        for col in cols:
            results.append(self.evaluate(factor_df, return_df, col, n_groups))
        passed_count = sum(1 for r in results if r["passed"])
        logger.info(f"[QualityGate] 批量评估: {passed_count}/{len(results)} 因子通过")
        return results

    @staticmethod
    def _monotonicity_score(group_returns: list[float]) -> float:
        """分组收益单调性评分

        检查从 G1 到 Gn 收益是否单调递增 (或递减)。
        score = max(正序一致对数, 逆序一致对数) / 总对数
        """
        n = len(group_returns)
        if n < 2:
            return 0.0
        concordant = 0
        discordant = 0
        for i in range(n):
            for j in range(i + 1, n):
                if group_returns[j] > group_returns[i]:
                    concordant += 1
                elif group_returns[j] < group_returns[i]:
                    discordant += 1
        total = concordant + discordant
        if total == 0:
            return 0.0
        return max(concordant, discordant) / total
