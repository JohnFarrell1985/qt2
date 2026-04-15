"""LLM 择时参数自适应 (P2-31)

TiMi 范式: LLM 根据市场状态动态调整策略参数, 而非直接产生买卖信号。
输入: SentimentDaily + 市场统计 → 输出: 策略参数覆盖 (JSON)

参考: TiMi (Microsoft, Trade in Minutes)
"""
from __future__ import annotations

from typing import Dict, Optional

from src.common.logger import get_logger

logger = get_logger(__name__)


class LLMParamTuner:
    """LLM 择时参数调优"""

    def __init__(self, llm_client=None):
        self.llm = llm_client
        self._cache: Dict[str, Dict] = {}

    def suggest_params(
        self,
        sentiment: Dict,
        market_stats: Dict,
    ) -> Dict[str, float]:
        """根据市场状态生成策略参数覆盖

        Args:
            sentiment: SentimentDaily 数据
            market_stats: 市场统计 (波动率/涨跌比等)

        Returns:
            参数覆盖字典
        """
        if self.llm is None:
            return self._rule_suggest(sentiment, market_stats)

        try:
            prompt = self._build_prompt(sentiment, market_stats)
            result = self.llm.extract(prompt, schema=dict)
            return self._validate_params(result)
        except Exception as e:
            logger.warning("LLM 参数建议失败, 使用规则降级: %s", e)
            return self._rule_suggest(sentiment, market_stats)

    def _build_prompt(self, sentiment: Dict, market_stats: Dict) -> str:
        return f"""你是一个量化策略参数调优专家。
当前市场状态:
- 情绪合成指数: {sentiment.get('composite_sentiment', 0)}
- 赚钱效应: {sentiment.get('earning_effect', 0)}
- 北向资金 5 日累计: {sentiment.get('north_net_flow', 'N/A')} 亿
- 波动率 (20日): {market_stats.get('volatility_20d', 'N/A')}
- 宏观状态: {sentiment.get('applied_state', 'normal')}

输出 JSON: kelly_fraction(0.1~0.5), max_position_pct(0.3~1.0),
momentum_lookback(10~60), stop_loss_pct(0.03~0.10)"""

    @staticmethod
    def _rule_suggest(sentiment: Dict, market_stats: Dict) -> Dict[str, float]:
        """规则降级: 基于情绪阈值调参"""
        cs = float(sentiment.get("composite_sentiment", 0))
        if cs > 0.3:
            return {
                "kelly_fraction": 0.4,
                "max_position_pct": 0.8,
                "momentum_lookback": 20,
                "stop_loss_pct": 0.08,
            }
        if cs < -0.3:
            return {
                "kelly_fraction": 0.15,
                "max_position_pct": 0.4,
                "momentum_lookback": 40,
                "stop_loss_pct": 0.05,
            }
        return {
            "kelly_fraction": 0.25,
            "max_position_pct": 0.6,
            "momentum_lookback": 30,
            "stop_loss_pct": 0.07,
        }

    @staticmethod
    def _validate_params(params: Dict) -> Dict[str, float]:
        """校验参数范围"""
        validated = {}
        bounds = {
            "kelly_fraction": (0.1, 0.5),
            "max_position_pct": (0.3, 1.0),
            "momentum_lookback": (10, 60),
            "stop_loss_pct": (0.03, 0.10),
        }
        for key, (lo, hi) in bounds.items():
            if key in params:
                validated[key] = max(lo, min(hi, float(params[key])))
        return validated
