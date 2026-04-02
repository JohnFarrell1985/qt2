"""因子筛选

通过IC/IR分析、相关性过滤选出有效因子子集。
"""
import numpy as np
import pandas as pd
from typing import List, Dict, Tuple

from src.common.logger import get_logger
from src.factor.factor_analysis import calc_ic_series, calc_icir, group_return_test

logger = get_logger(__name__)


class FactorSelector:
    """因子筛选器"""

    def __init__(
        self,
        factor_df: pd.DataFrame,
        return_df: pd.DataFrame,
    ):
        """
        Args:
            factor_df: MultiIndex(trade_date, code), 列为因子名
            return_df: MultiIndex(trade_date, code), 列含 'forward_return'
        """
        self.factor_df = factor_df
        self.return_df = return_df
        self._ic_results: Dict[str, pd.Series] = {}
        self._reports: List[dict] = []

    def analyze_all(self) -> List[dict]:
        """对所有因子执行IC分析"""
        reports = []
        for col in self.factor_df.columns:
            ic_series = calc_ic_series(self.factor_df, self.return_df, col)
            self._ic_results[col] = ic_series

            dates = self.factor_df.index.get_level_values("trade_date")
            last_date = dates.max()
            try:
                f_last = self.factor_df.xs(last_date, level="trade_date")[col]
                r_last = self.return_df.xs(last_date, level="trade_date")["forward_return"]
                common = f_last.index.intersection(r_last.index)
                gr = group_return_test(f_last[common], r_last[common])
            except (KeyError, ValueError):
                gr = {}

            report = {
                "factor_name": col,
                "ic_mean": round(ic_series.mean(), 4) if len(ic_series) > 0 else None,
                "icir": round(calc_icir(ic_series), 4) if len(ic_series) > 0 else None,
                "ic_positive_ratio": round((ic_series > 0).mean(), 4) if len(ic_series) > 0 else None,
                "group_returns": gr,
            }
            reports.append(report)

        self._reports = sorted(reports, key=lambda x: abs(x.get("ic_mean") or 0), reverse=True)
        return self._reports

    def select_top_factors(self, n: int = 50, min_abs_ic: float = 0.02) -> List[str]:
        """选出IC绝对值最大的Top N因子"""
        if not self._reports:
            self.analyze_all()

        selected = [
            r["factor_name"]
            for r in self._reports
            if r.get("ic_mean") is not None and abs(r["ic_mean"]) >= min_abs_ic
        ]
        return selected[:n]

    def correlation_filter(
        self, factor_names: List[str], threshold: float = 0.7
    ) -> List[str]:
        """相关性过滤 - 去除高度相关的因子，保留IC更高的"""
        if not factor_names:
            return []

        sub = self.factor_df[factor_names].dropna()
        if sub.empty:
            return factor_names

        corr = sub.corr(method="spearman").abs()

        ic_map = {}
        for r in self._reports:
            if r["factor_name"] in factor_names:
                ic_map[r["factor_name"]] = abs(r.get("ic_mean") or 0)

        sorted_factors = sorted(factor_names, key=lambda x: ic_map.get(x, 0), reverse=True)

        keep = []
        removed = set()
        for f in sorted_factors:
            if f in removed:
                continue
            keep.append(f)
            for other in sorted_factors:
                if other != f and other not in removed:
                    if corr.loc[f, other] > threshold:
                        removed.add(other)

        logger.info(f"相关性过滤: {len(factor_names)} -> {len(keep)} 因子")
        return keep
