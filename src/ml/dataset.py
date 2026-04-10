"""数据集构建

将因子数据和收益率标签组装为ML训练集。
"""
import numpy as np
import pandas as pd
from datetime import date, timedelta
from typing import Tuple, List, Optional

from sqlalchemy import text

from src.common.db import get_session
from src.common.logger import get_logger
from src.data.factor_data import FactorDataManager
from src.factor.factor_preprocess import preprocess_cross_section

logger = get_logger(__name__)


class FactorDataset:
    """因子数据集构建器"""

    def __init__(self):
        self.factor_mgr = FactorDataManager()
        self.X: Optional[pd.DataFrame] = None
        self.y: Optional[pd.Series] = None
        self.dates: Optional[pd.Series] = None

    def build(
        self,
        factor_names: List[str],
        stock_pool: List[str],
        start_date: date,
        end_date: date,
        label_period: int = 5,
    ) -> Tuple[pd.DataFrame, pd.Series]:
        """构建训练数据集

        Args:
            factor_names: 因子名列表
            stock_pool: 股票代码列表
            start_date: 起始日期
            end_date: 结束日期
            label_period: 标签周期(未来N天收益率)

        Returns:
            (X, y) 因子矩阵和标签
        """
        factor_df = self.factor_mgr.get_factor_values(
            factor_names, stock_pool, start_date, end_date
        )
        if factor_df.empty:
            logger.warning("因子数据为空")
            return pd.DataFrame(), pd.Series(dtype=float)

        returns = self._calc_forward_returns(stock_pool, start_date, end_date, label_period)

        for dt, group in factor_df.groupby(level="trade_date"):
            idx = group.index
            codes_in_section = idx.get_level_values("code")
            industry, mcap = self._load_industry_data(codes_in_section.tolist())
            factor_df.loc[idx] = preprocess_cross_section(
                group.droplevel("trade_date"),
                neutralize_industry=True,
                industry_series=industry,
                market_cap_series=mcap,
            ).values

        common_idx = factor_df.index.intersection(returns.index)
        if len(common_idx) == 0:
            logger.warning("因子与收益率无交集")
            return pd.DataFrame(), pd.Series(dtype=float)

        X = factor_df.loc[common_idx]
        y = returns.loc[common_idx]

        X = X.fillna(0)
        valid = y.notna()
        X = X[valid]
        y = y[valid]

        self.X = X
        self.y = y
        self.dates = X.index.get_level_values("trade_date") if "trade_date" in X.index.names else None
        logger.info(f"数据集: {X.shape[0]} 样本, {X.shape[1]} 因子")
        return X, y

    def train_val_test_split(
        self, train_ratio: float = 0.6, val_ratio: float = 0.2
    ) -> dict:
        """时序分割数据集 (避免未来信息泄露)"""
        if self.X is None or self.y is None:
            raise ValueError("请先调用 build() 构建数据集")

        dates = self.X.index.get_level_values("trade_date")
        unique_dates = sorted(dates.unique())
        n = len(unique_dates)

        train_end = unique_dates[int(n * train_ratio)]
        val_end = unique_dates[int(n * (train_ratio + val_ratio))]

        train_mask = dates <= train_end
        val_mask = (dates > train_end) & (dates <= val_end)
        test_mask = dates > val_end

        return {
            "X_train": self.X[train_mask], "y_train": self.y[train_mask],
            "X_val": self.X[val_mask], "y_val": self.y[val_mask],
            "X_test": self.X[test_mask], "y_test": self.y[test_mask],
            "train_end": train_end, "val_end": val_end,
        }

    @staticmethod
    def deduplicate_factors(
        sota_factors: pd.DataFrame,
        new_factors: pd.DataFrame,
        threshold: float = 0.99,
    ) -> pd.DataFrame:
        """RD-Agent 式因子去重: 丢弃与已有 SOTA 因子高度相关的新因子

        按日期截面计算新旧因子相关性, 若新因子与任一 SOTA 因子
        的平均截面相关系数 >= threshold, 则丢弃该新因子。

        Args:
            sota_factors: 已有因子池, MultiIndex=(trade_date, code)
            new_factors: 待评估新因子, 同 index
            threshold: 去重阈值, 默认 0.99

        Returns:
            筛选后的 new_factors (仅保留非冗余因子)
        """
        if sota_factors.empty or new_factors.empty:
            return new_factors

        keep_cols = []
        for new_col in new_factors.columns:
            max_avg_corr = 0.0
            for sota_col in sota_factors.columns:
                corrs = []
                combined = pd.concat(
                    [sota_factors[sota_col], new_factors[new_col]], axis=1,
                ).dropna()
                if "trade_date" in combined.index.names:
                    for _, grp in combined.groupby(level="trade_date"):
                        if len(grp) >= 10:
                            corrs.append(grp.iloc[:, 0].corr(grp.iloc[:, 1]))
                elif len(combined) >= 10:
                    corrs.append(combined.iloc[:, 0].corr(combined.iloc[:, 1]))

                if corrs:
                    avg_corr = abs(float(np.mean(corrs)))
                    max_avg_corr = max(max_avg_corr, avg_corr)

            if max_avg_corr < threshold:
                keep_cols.append(new_col)
            else:
                logger.info(
                    f"[去重] 因子 {new_col} 与 SOTA 最大相关 {max_avg_corr:.4f} >= {threshold}, 丢弃"
                )

        if not keep_cols:
            logger.warning("[去重] 所有新因子均被去重, 返回空 DataFrame")
            return pd.DataFrame(index=new_factors.index)

        logger.info(f"[去重] 保留 {len(keep_cols)}/{len(new_factors.columns)} 个新因子")
        return new_factors[keep_cols]

    @staticmethod
    def _load_industry_data(
        codes: List[str],
    ) -> tuple:
        """加载行业分类和市值数据, 用于中性化"""
        from src.data.models import Stock
        with get_session() as session:
            rows = session.query(
                Stock.code, Stock.industry, Stock.market_cap,
            ).filter(Stock.code.in_(codes)).all()
        if not rows:
            return pd.Series(dtype=str), pd.Series(dtype=float)
        industry = pd.Series(
            {r.code: r.industry or "未知" for r in rows},
        )
        mcap = pd.Series(
            {r.code: r.market_cap or 0.0 for r in rows},
        )
        return industry, mcap

    def _calc_forward_returns(
        self,
        stock_pool: List[str],
        start_date: date,
        end_date: date,
        period: int = 5,
    ) -> pd.Series:
        """计算未来N日收益率作为标签"""
        extended_end = end_date + timedelta(days=period * 2)

        with get_session() as session:
            sql = text("""
                SELECT code, trade_date, close
                FROM stock_daily
                WHERE code = ANY(:codes)
                  AND trade_date BETWEEN :start AND :end
                ORDER BY code, trade_date
            """)
            result = session.execute(sql, {
                "codes": stock_pool,
                "start": start_date,
                "end": extended_end,
            })
            rows = result.fetchall()

        if not rows:
            return pd.Series(dtype=float)

        df = pd.DataFrame(rows, columns=["code", "trade_date", "close"])
        df = df.pivot(index="trade_date", columns="code", values="close")
        forward_ret = df.shift(-period) / df - 1

        stacked = forward_ret.stack()
        stacked.index.names = ["trade_date", "code"]
        stacked.name = "forward_return"

        mask = stacked.index.get_level_values("trade_date") <= end_date
        return stacked[mask]
