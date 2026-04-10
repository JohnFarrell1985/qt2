"""编排器回测引擎

复用实盘 StrategyOrchestrator 完整管道:
  PositionMonitor → Strategy.generate_signals → SignalArbiter → PositionSizer

确保回测和实盘使用同一套信号生成、仲裁和仓位分配逻辑。

A 股特有约束:
- T+1: 当日买入次日才能卖出
- 涨跌停: 涨停板不可买入 (一字板), 跌停板不可卖出 (一字板)
- 停牌: volume==0 的股票不可交易, 市值按停牌前收盘价冻结
- 整手: 买入/卖出均为 100 股的整数倍
"""
from datetime import date, timedelta
from typing import Optional

import pandas as pd
from sqlalchemy import text

from src.common.config import settings
from src.common.db import get_session
from src.common.logger import get_logger
from src.strategy.base import HoldingPosition, ActionItem
from src.strategy.orchestrator import StrategyOrchestrator
from src.backtest.fees import FeeConfig, calc_buy_fees, calc_sell_fees
from src.backtest.performance import full_performance_report

logger = get_logger(__name__)


class OrchestratorBacktester:
    """编排器回测引擎 — 复用实盘完整管道"""

    def __init__(
        self,
        initial_capital: float = 0,
        fee_config: Optional[FeeConfig] = None,
        orchestrator: Optional[StrategyOrchestrator] = None,
    ):
        self.initial_capital = initial_capital or settings.backtest.initial_capital
        self.fee_config = fee_config or FeeConfig()
        self.orchestrator = orchestrator or StrategyOrchestrator()

        self.cash: float = self.initial_capital
        self.holdings: dict[str, _Position] = {}
        self.equity_curve: list[dict] = []
        self.trades: list[dict] = []
        self.daily_log: list[dict] = []

    def run(
        self,
        start_date: date,
        end_date: date,
    ) -> dict:
        """执行回测

        Args:
            start_date: 回测起始日期
            end_date: 回测结束日期

        Returns:
            包含 equity_curve, trades, performance, daily_log 的结果 dict
        """
        calendar = self._load_trading_calendar(start_date, end_date)
        if not calendar:
            logger.error(f"[回测] {start_date}~{end_date} 无交易日历数据")
            return self._empty_result()

        ohlc_cache = self._preload_ohlc(start_date, end_date)
        limit_cache = self._preload_limit_status(ohlc_cache)

        self.cash = self.initial_capital
        self.holdings.clear()
        self.equity_curve.clear()
        self.trades.clear()
        self.daily_log.clear()

        logger.info(
            f"[回测] 开始: {start_date}~{end_date}, "
            f"共 {len(calendar)} 个交易日, 初始资金 {self.initial_capital:,.0f}"
        )

        for trade_date in calendar:
            self._simulate_one_day(trade_date, ohlc_cache, limit_cache)

        performance = full_performance_report(self.equity_curve, self.trades)

        logger.info(
            f"[回测] 完成: 年化={performance.get('annualized_return_pct', 0):.2f}%, "
            f"Sharpe={performance.get('sharpe_ratio', 0):.2f}, "
            f"MaxDD={performance.get('max_drawdown', {}).get('max_drawdown_pct', 0):.2f}%, "
            f"交易={len(self.trades)}笔"
        )

        return {
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "initial_capital": self.initial_capital,
            "final_capital": self.equity_curve[-1]["capital"] if self.equity_curve else self.initial_capital,
            "performance": performance,
            "equity_curve": self.equity_curve,
            "trades": self.trades,
            "daily_log": self.daily_log,
        }

    def _simulate_one_day(
        self,
        trade_date: date,
        ohlc_cache: dict,
        limit_cache: dict,
    ) -> None:
        """模拟单个交易日"""
        today_ohlc = ohlc_cache.get(trade_date, {})
        today_limits = limit_cache.get(trade_date, {})

        self._update_holdings_price(today_ohlc)

        holdings_list = self._to_holding_positions(trade_date)
        price_map = {code: data["close"] for code, data in today_ohlc.items()}

        total_capital = self._total_value(price_map)
        result = self.orchestrator.execute(
            trade_date=trade_date,
            holdings=holdings_list,
            total_capital=total_capital,
            available_cash=self.cash,
            price_map=price_map,
        )

        actions = result.get("actions", [])
        sell_actions = [a for a in actions if a.direction == "sell"]
        buy_actions = [a for a in actions if a.direction == "buy"]

        for action in sell_actions:
            self._execute_sell(action, trade_date, today_ohlc, today_limits)

        for action in buy_actions:
            self._execute_buy(action, trade_date, today_ohlc, today_limits)

        self._advance_t1(trade_date)

        total = self._total_value(price_map)
        self.equity_curve.append({
            "date": trade_date.isoformat(),
            "capital": round(total, 2),
            "cash": round(self.cash, 2),
            "n_holdings": len(self.holdings),
        })

        self.daily_log.append({
            "date": trade_date.isoformat(),
            "macro_state": result.get("macro_state", ""),
            "n_signals": result.get("summary", {}).get("total_signals", 0),
            "n_sells": len(sell_actions),
            "n_buys": len(buy_actions),
            "capital": round(total, 2),
        })

    def _execute_sell(
        self,
        action: ActionItem,
        trade_date: date,
        ohlc: dict,
        limits: dict,
    ) -> None:
        """执行卖出, 含 A 股约束检查"""
        code = action.code
        pos = self.holdings.get(code)
        if not pos:
            return

        if not pos.can_sell:
            return

        lim = limits.get(code, {})
        if lim.get("is_suspended"):
            return
        if lim.get("is_one_word_limit") and lim.get("is_limit_down"):
            return

        bar = ohlc.get(code)
        if not bar:
            return

        sell_price = bar["close"]
        qty = action.target_quantity or pos.quantity
        qty = min(qty, pos.quantity)
        if qty <= 0:
            return

        amount = sell_price * qty
        fees = calc_sell_fees(amount, self.fee_config)
        net = amount - fees.total

        self.cash += net
        profit = (sell_price - pos.buy_price) * qty - fees.total
        profit_pct = (sell_price / pos.buy_price - 1) * 100 if pos.buy_price > 0 else 0

        self.trades.append({
            "code": code,
            "direction": "sell",
            "date": trade_date.isoformat(),
            "price": sell_price,
            "quantity": qty,
            "amount": round(amount, 2),
            "fees": round(fees.total, 2),
            "profit": round(profit, 2),
            "profit_pct": round(profit_pct, 2),
            "hold_days": pos.hold_days,
        })

        if qty >= pos.quantity:
            del self.holdings[code]
        else:
            pos.quantity -= qty

    def _execute_buy(
        self,
        action: ActionItem,
        trade_date: date,
        ohlc: dict,
        limits: dict,
    ) -> None:
        """执行买入, 含 A 股约束检查"""
        code = action.code
        lim = limits.get(code, {})
        if lim.get("is_suspended"):
            return
        if lim.get("is_one_word_limit") and lim.get("is_limit_up"):
            return

        bar = ohlc.get(code)
        if not bar:
            return

        buy_price = bar["close"]
        if buy_price <= 0:
            return

        lot = settings.sizer.lot_size
        qty = action.target_quantity
        if qty <= 0 and action.target_amount > 0:
            qty = int(action.target_amount / buy_price / lot) * lot

        if qty < lot:
            return

        amount = buy_price * qty
        fees = calc_buy_fees(amount, self.fee_config)
        total_cost = amount + fees.total

        if total_cost > self.cash:
            qty = int(self.cash / (buy_price * (1 + self.fee_config.commission_rate)) / lot) * lot
            if qty < lot:
                return
            amount = buy_price * qty
            fees = calc_buy_fees(amount, self.fee_config)
            total_cost = amount + fees.total

        self.cash -= total_cost

        if code in self.holdings:
            old = self.holdings[code]
            total_qty = old.quantity + qty
            avg_price = (old.buy_price * old.quantity + buy_price * qty) / total_qty
            old.buy_price = avg_price
            old.quantity = total_qty
            old.can_sell = False
        else:
            self.holdings[code] = _Position(
                code=code,
                buy_date=trade_date,
                buy_price=buy_price,
                quantity=qty,
                current_price=buy_price,
                highest_price=buy_price,
                can_sell=False,
            )

        self.trades.append({
            "code": code,
            "direction": "buy",
            "date": trade_date.isoformat(),
            "price": buy_price,
            "quantity": qty,
            "amount": round(amount, 2),
            "fees": round(fees.total, 2),
        })

    def _advance_t1(self, trade_date: date) -> None:
        """T+1: 当日买入的标记为可卖"""
        for pos in self.holdings.values():
            if not pos.can_sell:
                pos.can_sell = True
            pos.hold_days += 1

    def _update_holdings_price(self, ohlc: dict) -> None:
        """更新持仓当前价格和最高价"""
        for code, pos in self.holdings.items():
            bar = ohlc.get(code)
            if bar:
                pos.current_price = bar["close"]
                pos.highest_price = max(pos.highest_price, bar["high"])

    def _to_holding_positions(self, trade_date: date) -> list[HoldingPosition]:
        """将内部持仓转换为 Orchestrator 所需的 HoldingPosition 列表"""
        result = []
        for pos in self.holdings.values():
            profit_pct = ((pos.current_price / pos.buy_price) - 1) * 100 if pos.buy_price > 0 else 0
            result.append(HoldingPosition(
                code=pos.code,
                buy_date=pos.buy_date,
                buy_price=pos.buy_price,
                quantity=pos.quantity,
                current_price=pos.current_price,
                highest_price=pos.highest_price,
                hold_days=pos.hold_days,
                profit_pct=profit_pct,
                can_sell=pos.can_sell,
            ))
        return result

    def _total_value(self, price_map: dict) -> float:
        """计算账户总市值"""
        market_value = sum(
            price_map.get(code, pos.current_price) * pos.quantity
            for code, pos in self.holdings.items()
        )
        return self.cash + market_value

    @staticmethod
    def _load_trading_calendar(start_date: date, end_date: date) -> list[date]:
        """从 stock_daily 提取交易日历"""
        with get_session() as session:
            sql = text("""
                SELECT DISTINCT trade_date FROM stock_daily
                WHERE trade_date BETWEEN :start AND :end
                ORDER BY trade_date
            """)
            rows = session.execute(sql, {"start": start_date, "end": end_date}).fetchall()
        return [r[0] for r in rows]

    @staticmethod
    def _preload_ohlc(
        start_date: date, end_date: date,
    ) -> dict[date, dict[str, dict]]:
        """预加载全量 OHLCV 数据到内存, 避免逐日查询"""
        with get_session() as session:
            sql = text("""
                SELECT code, trade_date, open, high, low, close,
                       pre_close, volume, amount, change_pct
                FROM stock_daily
                WHERE trade_date BETWEEN :start AND :end
                ORDER BY trade_date, code
            """)
            rows = session.execute(sql, {"start": start_date, "end": end_date}).fetchall()

        cache: dict[date, dict[str, dict]] = {}
        for r in rows:
            td = r[1]
            if td not in cache:
                cache[td] = {}
            cache[td][r[0]] = {
                "open": r[2], "high": r[3], "low": r[4], "close": r[5],
                "pre_close": r[6], "volume": r[7], "amount": r[8],
                "change_pct": r[9],
            }
        return cache

    @staticmethod
    def _preload_limit_status(
        ohlc_cache: dict[date, dict[str, dict]],
    ) -> dict[date, dict[str, dict]]:
        """从预加载的 OHLCV 计算涨跌停/停牌状态"""
        limit_cache: dict[date, dict[str, dict]] = {}

        for td, day_data in ohlc_cache.items():
            limit_cache[td] = {}
            for code, bar in day_data.items():
                volume = bar.get("volume", 0) or 0
                change_pct = bar.get("change_pct", 0) or 0
                open_p = bar.get("open", 0) or 0
                high = bar.get("high", 0) or 0
                low = bar.get("low", 0) or 0
                close = bar.get("close", 0) or 0

                if code.startswith("688") or code.startswith("300"):
                    threshold = 20.0
                else:
                    threshold = 10.0

                is_suspended = volume == 0
                is_limit_up = (
                    abs(close - high) < 0.01
                    and change_pct >= threshold - 1.0
                    and not is_suspended
                )
                is_limit_down = (
                    abs(close - low) < 0.01
                    and change_pct <= -(threshold - 1.0)
                    and not is_suspended
                )
                is_one_word = (
                    abs(open_p - close) < 0.01
                    and abs(high - low) < 0.01
                    and abs(open_p - high) < 0.01
                    and not is_suspended
                )

                limit_cache[td][code] = {
                    "is_suspended": is_suspended,
                    "is_limit_up": is_limit_up,
                    "is_limit_down": is_limit_down,
                    "is_one_word_limit": is_one_word,
                    "threshold": threshold,
                }

        return limit_cache

    def _empty_result(self) -> dict:
        return {
            "start_date": "", "end_date": "",
            "initial_capital": self.initial_capital,
            "final_capital": self.initial_capital,
            "performance": {},
            "equity_curve": [],
            "trades": [],
            "daily_log": [],
        }


class _Position:
    """回测内部持仓对象"""
    __slots__ = (
        "code", "buy_date", "buy_price", "quantity",
        "current_price", "highest_price", "hold_days", "can_sell",
    )

    def __init__(
        self,
        code: str,
        buy_date: date,
        buy_price: float,
        quantity: int,
        current_price: float = 0.0,
        highest_price: float = 0.0,
        can_sell: bool = True,
    ):
        self.code = code
        self.buy_date = buy_date
        self.buy_price = buy_price
        self.quantity = quantity
        self.current_price = current_price
        self.highest_price = highest_price
        self.hold_days = 0
        self.can_sell = can_sell
