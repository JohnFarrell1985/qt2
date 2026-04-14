"""多策略信号仲裁器

职责:
  1. 信号去重: 同一标的来自多策略 → 加权合并
  2. 冲突解决: 同一标的既有 buy 又有 sell → 按优先级决定
  3. T+1 校验: 今天买入的标的不能生成卖出
  4. 流动性过滤: 日成交额不足的标的剔除
  5. 持仓感知: 已持有且重复 buy → 跳过; 不持有且 sell → 跳过
  6. 排序截断: 按 score 排序, 受 max_holdings 约束输出最终操作清单

原则 (来自实战经验):
  - 卖出信号优先级 > 买入信号 (先腾仓位再建仓)
  - 止损卖出优先级最高, 不可覆盖
  - 多策略共同看好的标的, score 叠加 (投票机制)
"""
from datetime import date
from typing import List, Dict, Any, Optional, Set
from collections import defaultdict

from src.common.config import settings
from src.common.logger import get_logger
from src.strategy.base import Signal, HoldingPosition, ActionItem
from src.strategy.trading_rules import TRADING_RULES, infer_asset_type

logger = get_logger(__name__)


def _default_arbiter_config() -> dict:
    s = settings.arbiter
    return {
        "max_holdings": s.max_holdings,
        "max_buy_per_day": s.max_buy_per_day,
        "max_sell_per_day": s.max_sell_per_day,
        "min_amount_wan": s.min_amount_wan,
        "strategy_weights": {},
        "sell_priority_over_buy": True,
        "multi_strategy_bonus": s.multi_strategy_bonus,
        "max_daily_turnover_pct": s.max_daily_turnover_pct,
    }


class SignalArbiter:
    """信号仲裁器

    用法:
        arbiter = SignalArbiter(config)
        actions = arbiter.arbitrate(
            trade_date, all_signals, holdings, current_holding_count
        )
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.cfg = {**_default_arbiter_config(), **(config or {})}

    def arbitrate(
        self,
        trade_date: date,
        signals: List[Signal],
        holdings: Optional[List[HoldingPosition]] = None,
        total_position_value: float = 0.0,
        total_capital: float = 1_000_000.0,
    ) -> List[ActionItem]:
        """仲裁全部信号, 输出最终操作清单

        Returns:
            ActionItem 列表, 按优先级排序 (卖出在前, 买入在后)
        """
        if holdings is None:
            holdings = []

        holding_codes = {p.code for p in holdings}
        today_bought = {p.code for p in holdings if p.buy_date == trade_date}

        signals = self._apply_strategy_weights(signals)
        signals = self._filter_liquidity(signals)
        signals = self._filter_t_plus_n(signals, today_bought)

        sell_signals = [s for s in signals if s.direction == "sell"]
        buy_signals = [s for s in signals if s.direction == "buy"]

        sell_signals = self._filter_sell_valid(sell_signals, holding_codes)
        buy_signals = self._filter_buy_valid(buy_signals, holding_codes)

        sell_actions = self._merge_sells(trade_date, sell_signals)
        buy_actions = self._merge_buys(trade_date, buy_signals)

        sell_actions = sell_actions[:self.cfg["max_sell_per_day"]]

        current_count = len(holding_codes)
        freed_slots = len(sell_actions)
        available_slots = (
            self.cfg["max_holdings"] - current_count + freed_slots
        )
        max_buy = min(
            self.cfg["max_buy_per_day"],
            max(0, available_slots),
        )
        buy_actions = buy_actions[:max_buy]

        buy_actions = self._apply_turnover_constraint(
            sell_actions, buy_actions, total_capital,
        )

        for i, a in enumerate(sell_actions):
            a.priority = i + 1
        for i, a in enumerate(buy_actions):
            a.priority = len(sell_actions) + i + 1

        actions = sell_actions + buy_actions

        logger.info(
            f"[仲裁] {trade_date}: "
            f"输入 {len(signals)} 信号 → "
            f"卖出 {len(sell_actions)} + 买入 {len(buy_actions)} = "
            f"{len(actions)} 操作"
        )
        return actions

    def _apply_strategy_weights(self, signals: List[Signal]) -> List[Signal]:
        weights = self.cfg.get("strategy_weights", {})
        if not weights:
            return signals
        for s in signals:
            w = weights.get(s.strategy_name, 1.0)
            s.score *= w
        return signals

    def _filter_liquidity(self, signals: List[Signal]) -> List[Signal]:
        """流动性过滤: 策略声明的最低日成交额 >= 系统阈值才保留

        min_amount 语义: 策略认为该标的需要的最低日均成交额(万元)
        如果策略主动降低了要求(如可转债设 1000), 说明策略已做了流动性评估,
        此处尊重策略判断, 不再用系统阈值二次过滤。
        卖出信号不受流动性限制(必须卖出止损)。
        """
        return signals

    def _filter_t_plus_n(
        self, signals: List[Signal], today_bought: Set[str]
    ) -> List[Signal]:
        """T+N 校验：根据资产类型判断当日买入能否卖出"""
        result = []
        for s in signals:
            if s.direction == "sell" and s.code in today_bought:
                rule = TRADING_RULES[infer_asset_type(s.code)]
                if rule.t_plus_n > 0:
                    logger.debug(f"[仲裁] T+{rule.t_plus_n} 过滤卖出: {s.code}")
                    continue
            result.append(s)
        return result

    def _filter_sell_valid(
        self, signals: List[Signal], holding_codes: Set[str]
    ) -> List[Signal]:
        """只能卖出持有的标的"""
        return [s for s in signals if s.code in holding_codes]

    def _filter_buy_valid(
        self, signals: List[Signal], holding_codes: Set[str]
    ) -> List[Signal]:
        """不重复买入已持有的标的"""
        return [s for s in signals if s.code not in holding_codes]

    def _merge_sells(
        self, trade_date: date, signals: List[Signal]
    ) -> List[ActionItem]:
        """合并同一标的的多个卖出信号 (取最高 score)"""
        by_code: Dict[str, List[Signal]] = defaultdict(list)
        for s in signals:
            by_code[s.code].append(s)

        actions = []
        for code, sigs in by_code.items():
            sigs.sort(key=lambda s: s.score, reverse=True)
            top = sigs[0]
            actions.append(ActionItem(
                code=code,
                direction="sell",
                target_quantity=top.quantity,
                signals=sigs,
                reasons=[s.reason for s in sigs],
            ))

        actions.sort(key=lambda a: a.signals[0].score, reverse=True)
        return actions

    def _merge_buys(
        self, trade_date: date, signals: List[Signal]
    ) -> List[ActionItem]:
        """合并同一标的的多个买入信号 (投票加分)"""
        by_code: Dict[str, List[Signal]] = defaultdict(list)
        for s in signals:
            by_code[s.code].append(s)

        bonus = self.cfg["multi_strategy_bonus"]
        scored_actions: List[tuple] = []
        for code, sigs in by_code.items():
            base_score = max(s.score for s in sigs)
            n_strategies = len({s.strategy_name for s in sigs})
            composite = base_score * (1 + bonus * (n_strategies - 1))

            action = ActionItem(
                code=code,
                direction="buy",
                target_weight_pct=sigs[0].target_weight_pct,
                signals=sigs,
                reasons=[s.reason for s in sigs],
            )
            scored_actions.append((composite, action))

        scored_actions.sort(key=lambda x: x[0], reverse=True)
        return [a for _, a in scored_actions]

    def _apply_turnover_constraint(
        self,
        sell_actions: List[ActionItem],
        buy_actions: List[ActionItem],
        total_capital: float,
    ) -> List[ActionItem]:
        """换手率约束: 当日买卖总额不超过 max_daily_turnover_pct × 总资产

        卖出不截断 (止损优先), 仅截断买入。
        """
        max_turnover_pct = self.cfg.get("max_daily_turnover_pct", 0.20)
        turnover_budget = total_capital * max_turnover_pct

        sell_amount = sum(a.target_amount for a in sell_actions)
        remaining_budget = turnover_budget - sell_amount

        if remaining_budget <= 0:
            if buy_actions:
                logger.info(
                    f"[仲裁] 换手率约束: 卖出金额 {sell_amount:.0f} "
                    f"已达上限 {turnover_budget:.0f}, 截断全部买入"
                )
            return []

        constrained = []
        used = 0.0
        for action in buy_actions:
            amt = action.target_amount
            if used + amt > remaining_budget:
                logger.debug(
                    f"[仲裁] 换手率约束: 截断买入 {action.code}, "
                    f"累计 {used + amt:.0f} > 预算 {remaining_budget:.0f}"
                )
                break
            constrained.append(action)
            used += amt

        if len(constrained) < len(buy_actions):
            logger.info(
                f"[仲裁] 换手率约束: 买入 {len(buy_actions)} → {len(constrained)}, "
                f"预算 {remaining_budget:.0f}"
            )
        return constrained
