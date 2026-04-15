"""策略构建

将LightGBM模型预测输出转换为交易信号。
"""
import pandas as pd
from datetime import date
from typing import List, Dict

from src.common.db import get_session
from src.common.logger import get_logger
from src.data.models import MLPrediction
from src.ml.lgb_model import LGBFactorModel

logger = get_logger(__name__)


class StrategyBuilder:
    """策略构建器 - 模型输出 -> 交易信号"""

    def __init__(
        self,
        model: LGBFactorModel,
        top_n: int = 10,
        long_threshold: float = 0.0,
    ):
        self.model = model
        self.top_n = top_n
        self.long_threshold = long_threshold

    def generate_signals(
        self,
        factor_data: pd.DataFrame,
        trade_date: date,
    ) -> List[Dict]:
        """生成交易信号

        Args:
            factor_data: 截面因子数据 index=code, columns=factor_names
            trade_date: 交易日

        Returns:
            [{"code": "000001", "signal": "buy", "score": 0.05, "rank": 1}, ...]
        """
        predictions = self.model.predict(factor_data)

        ranked = predictions.sort_values(ascending=False)
        signals = []

        for rank, (code, score) in enumerate(ranked.items(), 1):
            if rank > self.top_n:
                break
            if score < self.long_threshold:
                continue
            signals.append({
                "code": code,
                "signal": "buy",
                "predicted_return": round(float(score), 6),
                "rank": rank,
            })

        logger.info(f"[{trade_date}] 生成 {len(signals)} 个买入信号")
        return signals

    def save_predictions(
        self,
        predictions: pd.Series,
        trade_date: date,
        model_id: int = 0,
    ) -> int:
        """保存预测结果到数据库"""
        ranked = predictions.rank(ascending=False, method="min").astype(int)
        count = 0

        with get_session() as session:
            for code, pred_return in predictions.items():
                rank = int(ranked[code])
                signal = "buy" if pred_return > self.long_threshold else "hold"

                record = MLPrediction(
                    model_id=model_id,
                    trade_date=trade_date,
                    code=code,
                    predicted_return=float(pred_return),
                    rank_score=rank,
                    signal=signal,
                )
                session.add(record)
                count += 1

        logger.info(f"已保存 {count} 条预测结果")
        return count
