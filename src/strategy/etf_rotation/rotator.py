"""轮动引擎 — 排名选择、防锯齿、止损检查"""
from datetime import date

import pandas as pd

from src.common.logger import get_logger
from src.strategy.base import HoldingPosition

logger = get_logger(__name__)


class ETFRotator:
    """ETF 轮动核心逻辑"""

    @staticmethod
    def rank_and_select(
        scores: pd.Series,
        top_k: int,
        score_min: float = 0.0,
        score_max: float = 5.0,
    ) -> list[str]:
        """按动量打分排序, 过滤分数边界, 选取 top K

        Args:
            scores: index=code, values=momentum_score
            top_k: 选取前 K 个
            score_min: 最低分数阈值 (含)
            score_max: 最高分数阈值 (含), 超高分可能是异常

        Returns:
            选中的 code 列表 (已排序, 分数高在前)
        """
        if scores.empty:
            return []

        filtered = scores[(scores >= score_min) & (scores <= score_max)].dropna()
        if filtered.empty:
            return []

        ranked = filtered.sort_values(ascending=False)
        selected = ranked.head(top_k).index.tolist()
        logger.debug("rank_and_select: top_%d = %s (scores: %s)",
                      top_k, selected, ranked.head(top_k).to_dict())
        return selected

    @staticmethod
    def anti_whipsaw_filter(
        new_selected: list[str],
        current_holdings: list[HoldingPosition] | None,
        scores: pd.Series,
        min_hold_days: int,
        rank_threshold: float,
    ) -> list[str]:
        """防锯齿过滤 — 避免频繁换仓

        规则:
        1. 持仓未满 min_hold_days 的标的保留不换
        2. 现有持仓如果排名差距在 rank_threshold 以内, 也保留

        Args:
            new_selected: 本轮新选出的 codes
            current_holdings: 当前持仓列表
            scores: 全部标的的动量分数
            min_hold_days: 最低持有天数
            rank_threshold: 排名容忍偏差 (分数比例)

        Returns:
            过滤后的 code 列表
        """
        if not current_holdings:
            return new_selected

        result = list(new_selected)

        for h in current_holdings:
            if h.code in result:
                continue

            if h.hold_days < min_hold_days:
                logger.debug("anti_whipsaw: 保留 %s (持仓 %d 天 < %d)",
                             h.code, h.hold_days, min_hold_days)
                result.append(h.code)
                continue

            if h.code in scores.index and len(result) > 0:
                best_score = scores[result[0]] if result[0] in scores.index else 0
                h_score = scores[h.code]
                if best_score != 0 and abs(best_score - h_score) / abs(best_score) <= rank_threshold:
                    logger.debug("anti_whipsaw: 保留 %s (分差 %.2f%% <= %.2f%%)",
                                 h.code, abs(best_score - h_score) / abs(best_score) * 100,
                                 rank_threshold * 100)
                    result.append(h.code)

        return result

    @staticmethod
    def check_stop_loss(
        holdings: list[HoldingPosition],
        stop_loss_daily: float,
        stop_loss_3d: float,
        prices: pd.DataFrame | None = None,
    ) -> list[str]:
        """止损检查 — 返回需要卖出的代码列表

        Args:
            holdings: 当前持仓
            stop_loss_daily: 单日跌幅阈值 (如 0.05 = 5%)
            stop_loss_3d: 3 日累计跌幅阈值 (如 0.08 = 8%)
            prices: 价格矩阵 (用于 3 日判断, 可选)

        Returns:
            需要止损卖出的 code 列表
        """
        sell_codes: list[str] = []

        for h in holdings:
            if not h.can_sell:
                continue

            if h.buy_price > 0 and h.current_price > 0:
                daily_loss = (h.current_price - h.buy_price) / h.buy_price
                if daily_loss <= -stop_loss_daily:
                    logger.info("止损触发(单日): %s 亏损 %.2f%%", h.code, daily_loss * 100)
                    sell_codes.append(h.code)
                    continue

            if prices is not None and h.code in prices.columns and len(prices) >= 3:
                recent = prices[h.code].iloc[-3:]
                if recent.iloc[0] > 0:
                    loss_3d = (recent.iloc[-1] - recent.iloc[0]) / recent.iloc[0]
                    if loss_3d <= -stop_loss_3d:
                        logger.info("止损触发(3日): %s 3日亏损 %.2f%%", h.code, loss_3d * 100)
                        sell_codes.append(h.code)

        return list(set(sell_codes))

    @staticmethod
    def is_rebalance_day(
        last_rebalance_date: date | None,
        current_date: date,
        interval: int,
    ) -> bool:
        """判断是否为调仓日

        Args:
            last_rebalance_date: 上次调仓日, None 则视为首次
            current_date: 当前日期
            interval: 调仓间隔 (交易日数)

        Returns:
            True 则需要调仓
        """
        if last_rebalance_date is None:
            return True

        delta = (current_date - last_rebalance_date).days
        trading_days_approx = int(delta * 5 / 7)
        return trading_days_approx >= interval
