"""分钟线回测引擎

支持基于分钟级K线的策略回测。
"""
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import List, Dict, Any, Optional, Callable

from .data_loader import get_minute_data, get_trading_dates
from .fees import FeeConfig, calc_buy_fees, calc_sell_fees

logger = logging.getLogger(__name__)


@dataclass
class MinuteTrade:
    """分钟线交易记录"""
    code: str
    buy_time: datetime
    sell_time: datetime
    buy_price: float
    sell_price: float
    quantity: int
    buy_amount: float
    sell_amount: float
    fees: float
    profit: float
    profit_pct: float


@dataclass
class MinuteBacktestResult:
    """分钟线回测结果"""
    start_date: date
    end_date: date
    period: str
    initial_capital: float
    final_capital: float
    total_return_pct: float
    total_trades: int
    win_trades: int
    lose_trades: int
    win_rate: float
    total_fees: float
    trades: List[MinuteTrade] = field(default_factory=list)
    equity_curve: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "period": f"{self.start_date} ~ {self.end_date}",
            "bar_period": self.period,
            "initial_capital": self.initial_capital,
            "final_capital": round(self.final_capital, 2),
            "total_return_pct": round(self.total_return_pct, 2),
            "total_trades": self.total_trades,
            "win_rate": round(self.win_rate, 2),
            "total_fees": round(self.total_fees, 2),
        }


class MinuteBacktestEngine:
    """分钟线回测引擎

    用法:
        engine = MinuteBacktestEngine(strategy_fn, period="5m")
        result = engine.run("000001", start_date, end_date, capital=1_000_000)
    """

    def __init__(
        self,
        strategy_fn: Callable,
        period: str = "5m",
        fee_config: Optional[FeeConfig] = None,
    ):
        """
        Args:
            strategy_fn: 策略函数，签名 (bars, position, cash) -> signal
                         signal: "buy" / "sell" / None
            period: K线周期 "1m"/"5m"/"15m"/"30m"
        """
        self.strategy_fn = strategy_fn
        self.period = period
        self.fee_config = fee_config or FeeConfig()

    def run(
        self,
        code: str,
        start_date: date,
        end_date: date,
        initial_capital: float = 1_000_000,
        max_position_pct: float = 1.0,
    ) -> MinuteBacktestResult:
        """执行分钟线回测"""
        trading_dates = get_trading_dates(start_date, end_date)
        if not trading_dates:
            raise ValueError(f"区间 {start_date}~{end_date} 无交易日数据")

        capital = initial_capital
        position = 0
        cost_price = 0.0
        trades: List[MinuteTrade] = []
        equity_curve: List[Dict] = []

        start_str = f"{start_date} 09:30:00"
        end_str = f"{end_date} 15:00:00"
        bars = get_minute_data(code, start_str, end_str, self.period)

        if not bars:
            raise ValueError(f"{code} 在 {start_date}~{end_date} 无{self.period}分钟线数据")

        logger.info(f"分钟线回测: {code} {self.period} {start_date}~{end_date}, {len(bars)} bars")

        history = []
        for bar in bars:
            history.append(bar)
            price = bar["close"]
            if price is None or price <= 0:
                continue

            signal = self.strategy_fn(history, position, capital)

            if signal == "buy" and position == 0:
                max_amount = capital * max_position_pct
                quantity = int(max_amount / price / 100) * 100
                if quantity <= 0:
                    continue
                buy_fees = calc_buy_fees(price, quantity, code, self.fee_config)
                buy_cost = price * quantity + buy_fees.total
                if buy_cost > capital:
                    quantity = int(capital / price / 100) * 100
                    if quantity <= 0:
                        continue
                    buy_fees = calc_buy_fees(price, quantity, code, self.fee_config)
                    buy_cost = price * quantity + buy_fees.total

                capital -= buy_cost
                position = quantity
                cost_price = price
                buy_time = bar["trade_time"]
                buy_amount = buy_cost
                buy_fees_total = buy_fees.total

            elif signal == "sell" and position > 0:
                sell_fees = calc_sell_fees(price, position, code, self.fee_config)
                sell_return = price * position - sell_fees.total
                total_fees = buy_fees_total + sell_fees.total
                profit = sell_return - buy_amount
                profit_pct = (profit / buy_amount) * 100 if buy_amount > 0 else 0

                trade = MinuteTrade(
                    code=code,
                    buy_time=buy_time,
                    sell_time=bar["trade_time"],
                    buy_price=cost_price,
                    sell_price=price,
                    quantity=position,
                    buy_amount=round(buy_amount, 2),
                    sell_amount=round(sell_return, 2),
                    fees=round(total_fees, 2),
                    profit=round(profit, 2),
                    profit_pct=round(profit_pct, 2),
                )
                trades.append(trade)
                capital += sell_return
                position = 0
                cost_price = 0.0

            pos_value = position * price if position > 0 else 0
            equity_curve.append({
                "time": str(bar["trade_time"]),
                "capital": round(capital + pos_value, 2),
            })

        if position > 0 and bars:
            last_price = bars[-1]["close"] or cost_price
            pos_value = position * last_price
            capital += pos_value
            position = 0

        total_return_pct = (capital - initial_capital) / initial_capital * 100
        win = [t for t in trades if t.profit > 0]

        return MinuteBacktestResult(
            start_date=start_date,
            end_date=end_date,
            period=self.period,
            initial_capital=initial_capital,
            final_capital=round(capital, 2),
            total_return_pct=round(total_return_pct, 2),
            total_trades=len(trades),
            win_trades=len(win),
            lose_trades=len(trades) - len(win),
            win_rate=round(len(win) / len(trades) * 100, 1) if trades else 0,
            total_fees=round(sum(t.fees for t in trades), 2),
            trades=trades,
            equity_curve=equity_curve,
        )
