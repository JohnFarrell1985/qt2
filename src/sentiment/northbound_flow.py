"""北向资金流 Regime 信号

P1-33: 北向资金 (沪股通 + 深股通) 是 A 股最公开的"聪明钱"代理变量。
学术实证: 北向净流入对 A 股次日/次周收益有显著预测力 (月度异常收益 0.54%-0.64%)。

数据源: AKShare `stock_hsgt_north_net_flow_in` (免费)
         或从 sentiment_daily 表已有的 north_net_flow 字段读取

信号:
  - 5 日净流入 Z-score > 0.5  → risk_on
  - 5 日净流入 Z-score < -0.5 → risk_off
  - 其余 → neutral
"""
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import text

from src.common.db import get_session
from src.common.logger import get_logger

logger = get_logger(__name__)


class NorthboundFlowSignal:
    """北向资金流信号 — 情绪引擎增强维度"""

    def __init__(
        self,
        short_window: int = 5,
        long_window: int = 20,
        zscore_window: int = 60,
        risk_on_threshold: float = 0.5,
        risk_off_threshold: float = -0.5,
    ):
        self.short_window = short_window
        self.long_window = long_window
        self.zscore_window = zscore_window
        self.risk_on_threshold = risk_on_threshold
        self.risk_off_threshold = risk_off_threshold

    def compute(self, trade_date: date) -> dict:
        """计算北向资金流信号

        Returns:
            dict with nb_flow_5d, nb_flow_20d, nb_flow_z, nb_regime
        """
        flow_series = self._load_flow(trade_date)
        if flow_series is None or len(flow_series) < self.short_window:
            logger.warning(f"[NorthboundFlow] {trade_date} 数据不足")
            return {
                "nb_flow_5d": None,
                "nb_flow_20d": None,
                "nb_flow_z": None,
                "nb_regime": "unknown",
            }

        return self._compute_from_series(flow_series)

    def compute_from_series(self, flow_series: pd.Series) -> dict:
        """外部提供 flow 数据时的接口 (测试/离线用)"""
        return self._compute_from_series(flow_series)

    def _compute_from_series(self, flow_series: pd.Series) -> dict:
        net_flow_5d = flow_series.rolling(self.short_window, min_periods=1).sum()
        net_flow_20d = flow_series.rolling(self.long_window, min_periods=1).sum()

        flow_momentum = net_flow_5d / (net_flow_20d.abs() + 1e-6)

        rolling_mean = flow_momentum.rolling(self.zscore_window, min_periods=10).mean()
        rolling_std = flow_momentum.rolling(self.zscore_window, min_periods=10).std()
        z_score = (flow_momentum - rolling_mean) / (rolling_std + 1e-6)

        latest_z = float(z_score.iloc[-1]) if len(z_score) > 0 and pd.notna(z_score.iloc[-1]) else 0.0
        latest_5d = float(net_flow_5d.iloc[-1]) if len(net_flow_5d) > 0 else 0.0
        latest_20d = float(net_flow_20d.iloc[-1]) if len(net_flow_20d) > 0 else 0.0

        if latest_z > self.risk_on_threshold:
            regime = "risk_on"
        elif latest_z < self.risk_off_threshold:
            regime = "risk_off"
        else:
            regime = "neutral"

        logger.debug(f"[NorthboundFlow] Z={latest_z:.2f}, 5d={latest_5d:.1f}亿, regime={regime}")

        return {
            "nb_flow_5d": round(latest_5d, 2),
            "nb_flow_20d": round(latest_20d, 2),
            "nb_flow_z": round(latest_z, 4),
            "nb_regime": regime,
        }

    def _load_flow(self, trade_date: date) -> Optional[pd.Series]:
        """从 sentiment_daily 加载北向净流入序列"""
        start = trade_date - timedelta(days=self.zscore_window * 2)
        with get_session() as session:
            sql = text("""
                SELECT trade_date, north_net_flow
                FROM sentiment_daily
                WHERE trade_date BETWEEN :start AND :td
                  AND north_net_flow IS NOT NULL
                ORDER BY trade_date
            """)
            rows = session.execute(sql, {"start": start, "td": trade_date}).fetchall()

        if not rows:
            return None

        df = pd.DataFrame(rows, columns=["trade_date", "north_net_flow"])
        return df.set_index("trade_date")["north_net_flow"]
