"""宏观状态分类器 (规则引擎)

根据合成情绪指数和各维度指标, 判断当前市场处于哪种宏观状态:
  bull_strong / bull_moderate / range_bound / bear_moderate / bear_severe / recovery

P1-17: 规则引擎实现, 输出建议状态 + 置信度
"""
from datetime import date, timedelta
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text

from src.common.db import get_session
from src.common.logger import get_logger

logger = get_logger(__name__)

MACRO_STATES = [
    "bull_strong", "bull_moderate", "range_bound",
    "bear_moderate", "bear_severe", "recovery",
]

MACRO_RULES: dict[str, dict] = {
    "bull_strong": {
        "conditions": [
            ("ad_ratio_ma5", ">=", 1.5),
            ("new_high_60d_ma5", ">=", 80),
            ("volume_ratio_ma5", ">=", 1.3),
            ("composite_sentiment", ">=", 0.5),
        ],
        "min_match": 3,
        "description": "涨跌比高+新高家数多+放量+情绪乐观",
    },
    "bull_moderate": {
        "conditions": [
            ("ad_ratio_ma5", ">=", 1.1),
            ("composite_sentiment", ">=", 0.2),
            ("capital_mood_ma5", ">=", 0.1),
            ("volatility_mood_ma5", ">=", -0.3),
        ],
        "min_match": 3,
        "description": "温和上涨+情绪偏乐观+资金流入+波动可控",
    },
    "range_bound": {
        "conditions": [
            ("ad_ratio_ma5", "between", (0.7, 1.3)),
            ("composite_sentiment", "between", (-0.3, 0.3)),
            ("volatility_mood_ma5", "between", (-0.5, 0.3)),
        ],
        "min_match": 2,
        "description": "涨跌均衡+情绪中性+波动一般",
    },
    "bear_moderate": {
        "conditions": [
            ("ad_ratio_ma5", "<=", 0.8),
            ("composite_sentiment", "<=", -0.2),
            ("capital_mood_ma5", "<=", -0.1),
            ("new_low_60d_ma5", ">=", 50),
        ],
        "min_match": 3,
        "description": "跌多涨少+情绪偏悲观+资金流出",
    },
    "bear_severe": {
        "conditions": [
            ("ad_ratio_ma5", "<=", 0.5),
            ("composite_sentiment", "<=", -0.5),
            ("limit_down_ma5", ">=", 20),
            ("volatility_mood_ma5", "<=", -0.5),
        ],
        "min_match": 3,
        "description": "大面积下跌+恐慌+跌停潮+高波动",
    },
    "recovery": {
        "conditions": [
            ("ad_ratio_diff5", ">", 0.3),
            ("composite_sentiment_diff5", ">", 0.3),
            ("capital_mood_diff5", ">", 0.2),
            ("ad_ratio_ma5", "<=", 1.2),
        ],
        "min_match": 3,
        "description": "情绪快速改善+资金回流+但尚未到牛市水平",
    },
}


def _check_condition(value: Optional[float], op: str, threshold) -> bool:
    """检查单条规则"""
    if value is None or np.isnan(value):
        return False
    if op == ">=":
        return value >= threshold
    if op == "<=":
        return value <= threshold
    if op == ">":
        return value > threshold
    if op == "<":
        return value < threshold
    if op == "between":
        lo, hi = threshold
        return lo <= value <= hi
    return False


class MacroClassifier:
    """宏观状态分类器 — 规则引擎"""

    def classify(
        self,
        features: dict[str, float],
        current_state: Optional[str] = None,
    ) -> dict:
        """根据特征字典判断宏观状态

        Args:
            features: 合成指标 + 衍生特征 (如 ad_ratio_ma5, composite_sentiment 等)
            current_state: 当前生效状态 (用于判断是否发生切换)

        Returns:
            dict with: suggested_state, confidence, match_detail, state_changed, recommendation
        """
        match_detail = {}
        best_state = "range_bound"
        best_score = -1.0

        for state, rule in MACRO_RULES.items():
            conditions = rule["conditions"]
            min_match = rule["min_match"]
            matched = sum(
                1 for indicator, op, threshold in conditions
                if _check_condition(features.get(indicator), op, threshold)
            )
            score = matched / len(conditions) if conditions else 0.0
            match_detail[state] = {
                "matched": matched,
                "required": min_match,
                "total": len(conditions),
                "score": round(score, 3),
            }
            if matched >= min_match and score > best_score:
                best_score = score
                best_state = state

        confidence = best_score
        state_changed = current_state is not None and current_state != best_state

        result = {
            "suggested_state": best_state,
            "confidence": round(confidence, 3),
            "match_detail": match_detail,
            "state_changed": state_changed,
            "current_state": current_state,
            "recommendation": MACRO_RULES.get(best_state, {}).get("description", ""),
        }

        logger.info(
            f"[MacroClassifier] 建议状态: {best_state} (置信度 {confidence:.2f}), "
            f"{'状态切换!' if state_changed else '状态不变'}"
        )
        return result

    def build_features(self, trade_date: date) -> dict[str, float]:
        """从 DB 加载近期情绪数据并生成分类特征

        衍生特征:
            *_ma5: 5 日均值
            *_diff5: 5 日变化量
        """
        start = trade_date - timedelta(days=30)
        with get_session() as session:
            sql = text("""
                SELECT trade_date, ad_ratio, limit_up_count, limit_down_count,
                       new_high_60d, new_low_60d,
                       market_volatility_5d, market_volatility_20d,
                       volume_ratio, sector_concentration,
                       earning_effect, capital_mood, volatility_mood,
                       sector_heat, news_mood, global_mood,
                       composite_sentiment
                FROM sentiment_daily
                WHERE trade_date BETWEEN :start AND :td
                ORDER BY trade_date
            """)
            rows = session.execute(sql, {"start": start, "td": trade_date}).fetchall()

        if not rows:
            return {}

        cols = [
            "trade_date", "ad_ratio", "limit_up_count", "limit_down_count",
            "new_high_60d", "new_low_60d",
            "market_volatility_5d", "market_volatility_20d",
            "volume_ratio", "sector_concentration",
            "earning_effect", "capital_mood", "volatility_mood",
            "sector_heat", "news_mood", "global_mood",
            "composite_sentiment",
        ]
        df = pd.DataFrame(rows, columns=cols)
        df.set_index("trade_date", inplace=True)

        features: dict[str, float] = {}
        if len(df) == 0:
            return features

        latest = df.iloc[-1]
        for col in df.columns:
            val = latest[col]
            features[col] = float(val) if pd.notna(val) else 0.0

        numeric_cols = df.select_dtypes(include="number").columns
        for col in numeric_cols:
            ma5 = df[col].tail(5).mean()
            features[f"{col}_ma5"] = float(ma5) if pd.notna(ma5) else 0.0

            if len(df) >= 6:
                diff5 = float(df[col].iloc[-1]) - float(df[col].iloc[-6])
                features[f"{col}_diff5"] = diff5 if pd.notna(diff5) else 0.0
            else:
                features[f"{col}_diff5"] = 0.0

        features.setdefault("limit_down_ma5", features.get("limit_down_count_ma5", 0.0))

        return features
