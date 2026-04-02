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
