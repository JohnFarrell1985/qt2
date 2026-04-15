"""ETF 标的池管理 — 解析配置、加载历史价格"""
from datetime import date

import pandas as pd
from sqlalchemy import select

from src.common.config import settings
from src.common.db import get_session
from src.common.logger import get_logger
from src.data.models import ETFDaily

logger = get_logger(__name__)


class ETFUniverse:
    """ETF 标的池 — 从 settings.etf_rotation 解析风险/防御/金丝雀池"""

    def __init__(self):
        cfg = settings.etf_rotation
        self._risk_pool = list(cfg.risk_pool)
        self._defensive_pool = list(cfg.defensive_pool)
        self._canary_pool = list(cfg.canary_pool)

    @property
    def risk_pool(self) -> list[str]:
        return self._risk_pool

    @property
    def defensive_pool(self) -> list[str]:
        return self._defensive_pool

    @property
    def canary_pool(self) -> list[str]:
        return self._canary_pool

    def get_all_codes(self) -> set[str]:
        """返回所有池的去重合集"""
        return set(self._risk_pool) | set(self._defensive_pool) | set(self._canary_pool)

    @staticmethod
    def load_prices(
        codes: list[str] | set[str],
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """从 etf_daily 表加载收盘价矩阵

        Returns:
            DataFrame — index=trade_date, columns=code, values=close
            缺失代码的列不会出现 (而非全 NaN)
        """
        codes = list(codes)
        if not codes:
            return pd.DataFrame()

        stmt = (
            select(ETFDaily.trade_date, ETFDaily.code, ETFDaily.close)
            .where(
                ETFDaily.code.in_(codes),
                ETFDaily.trade_date >= start_date,
                ETFDaily.trade_date <= end_date,
            )
            .order_by(ETFDaily.trade_date)
        )

        with get_session() as session:
            rows = session.execute(stmt).all()

        if not rows:
            logger.warning("load_prices: 无数据 codes=%s range=[%s,%s]", codes, start_date, end_date)
            return pd.DataFrame()

        df = pd.DataFrame(rows, columns=["trade_date", "code", "close"])
        pivot = df.pivot(index="trade_date", columns="code", values="close")
        pivot.index = pd.to_datetime(pivot.index)
        pivot.sort_index(inplace=True)
        return pivot
