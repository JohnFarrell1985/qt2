"""
策略回测引擎

支持两种模式:
1. run_strategy       — 简单隔日卖出 (T日选股 → T+1买 → T+2卖)
2. run_continuous     — 连续持仓 (重复选中则续持, 不再选中才卖出)

连续持仓流程 (run_continuous):
  每个交易日T收盘后:
    1. 调用 picker 获取选股结果 new_picks
    2. 次日(T+1) 9:30:
       a. 卖出: 持仓中不在 new_picks 里的股票, 以开盘价卖出
       b. 续持: 持仓中仍在 new_picks 里的股票, 不动
       c. 买入: new_picks 中不在持仓里的股票, 以开盘价买入 (涨停放弃)
  回测结束时, 以最后一个交易日收盘价清仓所有持仓
"""
import logging
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional, Dict, Any

from .stock_picker import StockPicker
from .data_loader import (
    get_open_price_exact, get_trading_dates, get_next_trading_date,
)
from .fees import FeeConfig, calc_buy_fees, calc_sell_fees

logger = logging.getLogger(__name__)

LIMIT_UP_THRESHOLD = 9.8


@dataclass
class DayTrade:
    """单笔交易记录"""
    code: str
    pick_date: date        # 选股日
    buy_date: date         # 买入日
    sell_date: date        # 卖出日
    buy_price: float
    sell_price: float
    quantity: int
    buy_amount: float      # 买入总成本 (含手续费)
    sell_amount: float     # 卖出净收入 (扣手续费)
    fees: float
    profit: float
    profit_pct: float
    holding_days: int = 1  # 持仓天数
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class _Holding:
    """内部持仓状态"""
    code: str
    buy_date: date
    buy_price: float
    quantity: int
    buy_cost: float        # 含手续费的买入总成本
    buy_fees: float


@dataclass
class StrategyConfig:
    """策略配置"""
    initial_capital: float = 1_000_000.0    # 初始资金 100万
    max_position_pct: float = 0.30          # 单只个股最大仓位 30%
    max_total_position_pct: float = 0.80    # 总仓位上限 80%
    max_holdings: int = 3                   # 最大同时持仓数
    limit_up_threshold: float = 9.8         # 涨停阈值%
    fee_config: FeeConfig = field(default_factory=FeeConfig)
    fixed_amount_per_stock: Optional[float] = None  # 每只股票固定买入金额 (如 100_000)


@dataclass
class StrategyResult:
    """策略回测结果"""
    config: StrategyConfig
    start_date: date
    end_date: date

    # 汇总
    initial_capital: float
    final_capital: float
    total_return: float           # 绝对收益
    total_return_pct: float       # 收益率%
    annualized_return_pct: float  # 年化收益率%

    total_trades: int
    win_trades: int
    lose_trades: int
    skipped_trades: int           # 涨停放弃笔数
    win_rate: float

    total_fees: float
    max_single_profit: float
    max_single_loss: float
    avg_profit_per_trade: float
    avg_holding_days: float

    # 净值曲线
    equity_curve: List[Dict[str, Any]] = field(default_factory=list)
    # 全部交易明细
    trades: List[DayTrade] = field(default_factory=list)
    # 被跳过的交易
    skipped: List[DayTrade] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "period": f"{self.start_date} ~ {self.end_date}",
            "initial_capital": self.initial_capital,
            "final_capital": round(self.final_capital, 2),
            "total_return": round(self.total_return, 2),
            "total_return_pct": f"{self.total_return_pct:.2f}%",
            "annualized_return_pct": f"{self.annualized_return_pct:.2f}%",
            "total_trades": self.total_trades,
            "win_trades": self.win_trades,
            "lose_trades": self.lose_trades,
            "skipped_trades": self.skipped_trades,
            "win_rate": f"{self.win_rate:.1f}%",
            "total_fees": round(self.total_fees, 2),
            "max_single_profit": round(self.max_single_profit, 2),
            "max_single_loss": round(self.max_single_loss, 2),
            "avg_profit_per_trade": round(self.avg_profit_per_trade, 2),
        }


def _is_limit_up(open_price: float, pre_close: float, threshold: float) -> bool:
    """判断是否涨停开盘"""
    if pre_close is None or pre_close <= 0:
        return False
    pct = (open_price - pre_close) / pre_close * 100
    return pct >= threshold


def run_strategy(
    picker: StockPicker,
    start_date: date = date(2025, 1, 1),
    end_date: date = date(2025, 12, 31),
    config: StrategyConfig = None,
) -> StrategyResult:
    """
    执行策略回测

    Args:
        picker: 选股器实例
        start_date: 回测起始日期
        end_date: 回测结束日期
        config: 策略配置

    Returns:
        StrategyResult
    """
    if config is None:
        config = StrategyConfig()

    trading_dates = get_trading_dates(start_date, end_date)
    if not trading_dates:
        raise ValueError(f"区间 {start_date}~{end_date} 内没有交易日数据")

    capital = config.initial_capital
    all_trades: List[DayTrade] = []
    skipped_trades: List[DayTrade] = []
    equity_curve: List[Dict[str, Any]] = []

    logger.info(f"策略回测: {start_date} ~ {end_date}, 初始资金: {capital:.0f}")
    logger.info(f"交易日数量: {len(trading_dates)}")

    for i, pick_date in enumerate(trading_dates):
        # 资金耗尽检查
        min_buy = config.fixed_amount_per_stock or 1000
        if capital < min_buy:
            logger.info(f"资金不足 (余额{capital:.2f} < 最低买入{min_buy:.0f}), 提前退出")
            equity_curve.append({"date": pick_date.isoformat(), "capital": round(capital, 2)})
            break

        # T日: 收盘后选股
        pick_result = picker.pick(pick_date)
        if not pick_result.codes:
            equity_curve.append({"date": pick_date.isoformat(), "capital": round(capital, 2)})
            continue

        # T+1日: 开盘买入
        buy_date = get_next_trading_date(pick_date)
        if buy_date is None or buy_date > end_date:
            equity_curve.append({"date": pick_date.isoformat(), "capital": round(capital, 2)})
            continue

        # T+2日: 开盘卖出
        sell_date = get_next_trading_date(buy_date)
        if sell_date is None or sell_date > end_date:
            equity_curve.append({"date": pick_date.isoformat(), "capital": round(capital, 2)})
            continue

        # 分配仓位
        if config.fixed_amount_per_stock:
            per_stock_budget = config.fixed_amount_per_stock
        else:
            available = capital * config.max_total_position_pct
            per_stock_max = capital * config.max_position_pct
            n_stocks = min(len(pick_result.codes), config.max_holdings)
            per_stock_budget = min(available / max(n_stocks, 1), per_stock_max)

        day_trades_executed = 0

        for code in pick_result.codes[:config.max_holdings]:
            if per_stock_budget < 1000:
                continue

            # 获取T+1日开盘数据
            buy_data = get_open_price_exact(code, buy_date)
            if buy_data is None or buy_data["open"] is None:
                skipped_trades.append(DayTrade(
                    code=code, pick_date=pick_date, buy_date=buy_date, sell_date=sell_date,
                    buy_price=0, sell_price=0, quantity=0,
                    buy_amount=0, sell_amount=0, fees=0, profit=0, profit_pct=0,
                    skipped=True, skip_reason=f"{code} 在 {buy_date} 无交易数据",
                ))
                continue

            buy_open = buy_data["open"]
            buy_pre_close = buy_data["pre_close"]

            # 涨停开盘检测
            if buy_pre_close and _is_limit_up(buy_open, buy_pre_close, config.limit_up_threshold):
                skipped_trades.append(DayTrade(
                    code=code, pick_date=pick_date, buy_date=buy_date, sell_date=sell_date,
                    buy_price=buy_open, sell_price=0, quantity=0,
                    buy_amount=0, sell_amount=0, fees=0, profit=0, profit_pct=0,
                    skipped=True,
                    skip_reason=f"涨停开盘 开盘{buy_open:.2f} 前收{buy_pre_close:.2f} "
                                f"涨{(buy_open-buy_pre_close)/buy_pre_close*100:.1f}%",
                ))
                continue

            # 计算买入数量
            quantity = int(per_stock_budget / buy_open / 100) * 100
            if quantity == 0:
                continue

            # 计算买入费用
            buy_fees = calc_buy_fees(buy_open, quantity, code, config.fee_config)
            total_buy_cost = buy_open * quantity + buy_fees.total

            if total_buy_cost > capital:
                quantity = int(capital / buy_open / 100) * 100
                if quantity == 0:
                    continue
                buy_fees = calc_buy_fees(buy_open, quantity, code, config.fee_config)
                total_buy_cost = buy_open * quantity + buy_fees.total

            # 获取T+2日开盘数据（卖出）
            sell_data = get_open_price_exact(code, sell_date)
            if sell_data is None or sell_data["open"] is None:
                skipped_trades.append(DayTrade(
                    code=code, pick_date=pick_date, buy_date=buy_date, sell_date=sell_date,
                    buy_price=buy_open, sell_price=0, quantity=quantity,
                    buy_amount=total_buy_cost, sell_amount=0, fees=buy_fees.total,
                    profit=0, profit_pct=0,
                    skipped=True, skip_reason=f"{code} 在 {sell_date} 无交易数据",
                ))
                continue

            sell_open = sell_data["open"]
            sell_fees = calc_sell_fees(sell_open, quantity, code, config.fee_config)
            total_sell_return = sell_open * quantity - sell_fees.total

            total_fees = buy_fees.total + sell_fees.total
            profit = total_sell_return - total_buy_cost
            profit_pct = (profit / total_buy_cost) * 100 if total_buy_cost > 0 else 0

            trade = DayTrade(
                code=code, pick_date=pick_date,
                buy_date=buy_date, sell_date=sell_date,
                buy_price=buy_open, sell_price=sell_open,
                quantity=quantity,
                buy_amount=round(total_buy_cost, 2),
                sell_amount=round(total_sell_return, 2),
                fees=round(total_fees, 2),
                profit=round(profit, 2),
                profit_pct=round(profit_pct, 2),
            )
            all_trades.append(trade)
            capital += profit
            day_trades_executed += 1

            logger.debug(
                f"  {pick_date} -> 买{code}@{buy_open:.2f}x{quantity} "
                f"卖@{sell_open:.2f} 盈亏{profit:+.2f} ({profit_pct:+.2f}%)"
            )

        equity_curve.append({"date": pick_date.isoformat(), "capital": round(capital, 2)})

    # 汇总
    total_return = capital - config.initial_capital
    total_return_pct = (total_return / config.initial_capital) * 100
    days = (end_date - start_date).days or 1
    annualized = ((capital / config.initial_capital) ** (365.0 / days) - 1) * 100

    profits = [t.profit for t in all_trades]
    win = [t for t in all_trades if t.profit > 0]
    lose = [t for t in all_trades if t.profit <= 0]

    return StrategyResult(
        config=config,
        start_date=start_date,
        end_date=end_date,
        initial_capital=config.initial_capital,
        final_capital=round(capital, 2),
        total_return=round(total_return, 2),
        total_return_pct=round(total_return_pct, 2),
        annualized_return_pct=round(annualized, 2),
        total_trades=len(all_trades),
        win_trades=len(win),
        lose_trades=len(lose),
        skipped_trades=len(skipped_trades),
        win_rate=round(len(win) / len(all_trades) * 100, 1) if all_trades else 0,
        total_fees=round(sum(t.fees for t in all_trades), 2),
        max_single_profit=round(max(profits), 2) if profits else 0,
        max_single_loss=round(min(profits), 2) if profits else 0,
        avg_profit_per_trade=round(sum(profits) / len(profits), 2) if profits else 0,
        avg_holding_days=1.0,
        equity_curve=equity_curve,
        trades=all_trades,
        skipped=skipped_trades,
    )


# ======================================================================
#  连续持仓策略  —  选股重复则续持，不再选中才卖出
# ======================================================================

def run_continuous(
    picker: StockPicker,
    start_date: date = date(2025, 1, 1),
    end_date: date = date(2025, 12, 31),
    config: StrategyConfig = None,
) -> StrategyResult:
    """
    连续持仓策略回测

    每个交易日T收盘后选股, T+1日 9:30 执行:
      - 卖出持仓中不在今日选股的股票
      - 续持仍在选股列表中的股票
      - 买入新选中但未持仓的股票 (涨停放弃)

    Args:
        picker: 选股器
        start_date: 回测起始
        end_date: 回测结束
        config: 策略配置
    """

    if config is None:
        config = StrategyConfig()

    trading_dates = get_trading_dates(start_date, end_date)
    if not trading_dates:
        raise ValueError(f"区间 {start_date}~{end_date} 内没有交易日数据")

    cash = config.initial_capital
    holdings: Dict[str, _Holding] = {}  # code → _Holding
    all_trades: List[DayTrade] = []
    skipped_trades: List[DayTrade] = []
    equity_curve: List[Dict[str, Any]] = []
    held_count = 0   # 续持次数统计
    total_pick_days = 0

    logger.info(f"连续持仓策略: {start_date} ~ {end_date}, 初始资金: {config.initial_capital:.0f}")
    logger.info(f"交易日数量: {len(trading_dates)}")

    for i, pick_date in enumerate(trading_dates):
        # 资金耗尽检查: 现金不足且无持仓 → 提前退出
        min_buy = config.fixed_amount_per_stock or 1000
        if cash < min_buy and not holdings:
            logger.info(f"资金耗尽 (余额{cash:.2f} < 最低买入{min_buy:.0f}), 且无持仓, 提前退出")
            equity_curve.append({
                "date": pick_date.isoformat(),
                "capital": round(cash, 2),
                "holdings": [],
            })
            break

        # ---- 1. 选股 (T日收盘后) ----
        pick_result = picker.pick(pick_date)
        new_codes = set(pick_result.codes[:config.max_holdings])
        total_pick_days += 1

        # ---- 2. T+1日 9:30 执行交易 ----
        exec_date = get_next_trading_date(pick_date)
        if exec_date is None or exec_date > end_date:
            # 记录当前净值 (现金 + 持仓市值用买入价估算)
            pos_value = sum(h.buy_price * h.quantity for h in holdings.values())
            equity_curve.append({
                "date": pick_date.isoformat(),
                "capital": round(cash + pos_value, 2),
                "holdings": list(holdings.keys()),
            })
            continue

        # ---- 2a. 卖出: 持仓中不在新选股列表里的 ----
        to_sell = [code for code in list(holdings.keys()) if code not in new_codes]
        for code in to_sell:
            h = holdings[code]
            sell_data = get_open_price_exact(code, exec_date)
            if sell_data is None or sell_data["open"] is None:
                logger.warning(f"  {exec_date} 卖出 {code} 失败: 无交易数据, 强制按买入价平仓")
                sell_price = h.buy_price
            else:
                sell_price = sell_data["open"]

            sell_fees_obj = calc_sell_fees(sell_price, h.quantity, code, config.fee_config)
            sell_return = sell_price * h.quantity - sell_fees_obj.total
            total_fees = h.buy_fees + sell_fees_obj.total
            profit = sell_return - h.buy_cost
            profit_pct = (profit / h.buy_cost) * 100 if h.buy_cost > 0 else 0
            holding_days = (exec_date - h.buy_date).days

            trade = DayTrade(
                code=code, pick_date=pick_date,
                buy_date=h.buy_date, sell_date=exec_date,
                buy_price=h.buy_price, sell_price=sell_price,
                quantity=h.quantity,
                buy_amount=round(h.buy_cost, 2),
                sell_amount=round(sell_return, 2),
                fees=round(total_fees, 2),
                profit=round(profit, 2),
                profit_pct=round(profit_pct, 2),
                holding_days=holding_days,
            )
            all_trades.append(trade)
            cash += sell_return

            logger.debug(
                f"  {exec_date} 卖出 {code}@{sell_price:.2f}x{h.quantity} "
                f"持{holding_days}天 盈亏{profit:+.2f}"
            )
            del holdings[code]

        # ---- 2b. 续持: 持仓中仍在选股列表的 ----
        for code in list(holdings.keys()):
            if code in new_codes:
                held_count += 1
                logger.debug(f"  {exec_date} 续持 {code}")

        # ---- 2c. 买入: 新选中但未持仓的 ----
        to_buy = [c for c in pick_result.codes[:config.max_holdings] if c not in holdings]
        if to_buy:
            current_held = len(holdings)
            slots = config.max_holdings - current_held
            to_buy = to_buy[:slots]

            for code in to_buy:
                if config.fixed_amount_per_stock:
                    budget = config.fixed_amount_per_stock
                else:
                    pos_value = sum(h.buy_price * h.quantity for h in holdings.values())
                    total_value = cash + pos_value
                    per_stock_max = total_value * config.max_position_pct
                    budget = min(cash * 0.95, per_stock_max)
                if budget < 1000:
                    continue

                buy_data = get_open_price_exact(code, exec_date)
                if buy_data is None or buy_data["open"] is None:
                    skipped_trades.append(DayTrade(
                        code=code, pick_date=pick_date,
                        buy_date=exec_date, sell_date=exec_date,
                        buy_price=0, sell_price=0, quantity=0,
                        buy_amount=0, sell_amount=0, fees=0,
                        profit=0, profit_pct=0,
                        skipped=True, skip_reason=f"{code} 在 {exec_date} 无交易数据",
                    ))
                    continue

                buy_open = buy_data["open"]
                buy_pre_close = buy_data["pre_close"]

                if buy_pre_close and _is_limit_up(buy_open, buy_pre_close, config.limit_up_threshold):
                    skipped_trades.append(DayTrade(
                        code=code, pick_date=pick_date,
                        buy_date=exec_date, sell_date=exec_date,
                        buy_price=buy_open, sell_price=0, quantity=0,
                        buy_amount=0, sell_amount=0, fees=0,
                        profit=0, profit_pct=0,
                        skipped=True,
                        skip_reason=f"涨停开盘 {buy_open:.2f}/{buy_pre_close:.2f} "
                                    f"+{(buy_open-buy_pre_close)/buy_pre_close*100:.1f}%",
                    ))
                    continue

                quantity = int(budget / buy_open / 100) * 100
                if quantity == 0:
                    continue

                buy_fees_obj = calc_buy_fees(buy_open, quantity, code, config.fee_config)
                buy_cost = buy_open * quantity + buy_fees_obj.total

                if buy_cost > cash:
                    quantity = int(cash / buy_open / 100) * 100
                    if quantity == 0:
                        continue
                    buy_fees_obj = calc_buy_fees(buy_open, quantity, code, config.fee_config)
                    buy_cost = buy_open * quantity + buy_fees_obj.total

                holdings[code] = _Holding(
                    code=code, buy_date=exec_date,
                    buy_price=buy_open, quantity=quantity,
                    buy_cost=buy_cost, buy_fees=buy_fees_obj.total,
                )
                cash -= buy_cost

                logger.debug(
                    f"  {exec_date} 买入 {code}@{buy_open:.2f}x{quantity} "
                    f"成本{buy_cost:.2f} 剩余现金{cash:.2f}"
                )

        # ---- 记录净值 ----
        pos_value = sum(h.buy_price * h.quantity for h in holdings.values())
        equity_curve.append({
            "date": pick_date.isoformat(),
            "capital": round(cash + pos_value, 2),
            "holdings": list(holdings.keys()),
        })

    # ---- 回测结束: 清仓所有持仓 (以最后交易日数据估算) ----
    if holdings:
        last_date = trading_dates[-1]
        final_exec = get_next_trading_date(last_date)
        for code in list(holdings.keys()):
            h = holdings[code]
            sell_price = h.buy_price  # 默认按买入价
            sell_date = final_exec or last_date

            if final_exec:
                sell_data = get_open_price_exact(code, final_exec)
                if sell_data and sell_data["open"]:
                    sell_price = sell_data["open"]
                    sell_date = final_exec

            sell_fees_obj = calc_sell_fees(sell_price, h.quantity, code, config.fee_config)
            sell_return = sell_price * h.quantity - sell_fees_obj.total
            total_fees = h.buy_fees + sell_fees_obj.total
            profit = sell_return - h.buy_cost
            profit_pct = (profit / h.buy_cost) * 100 if h.buy_cost > 0 else 0
            holding_days = (sell_date - h.buy_date).days

            trade = DayTrade(
                code=code, pick_date=last_date,
                buy_date=h.buy_date, sell_date=sell_date,
                buy_price=h.buy_price, sell_price=sell_price,
                quantity=h.quantity,
                buy_amount=round(h.buy_cost, 2),
                sell_amount=round(sell_return, 2),
                fees=round(total_fees, 2),
                profit=round(profit, 2),
                profit_pct=round(profit_pct, 2),
                holding_days=holding_days,
            )
            all_trades.append(trade)
            cash += sell_return
            del holdings[code]

    # ---- 汇总 ----
    total_return = cash - config.initial_capital
    total_return_pct = (total_return / config.initial_capital) * 100
    days = (end_date - start_date).days or 1
    annualized = ((cash / config.initial_capital) ** (365.0 / days) - 1) * 100

    profits = [t.profit for t in all_trades]
    win = [t for t in all_trades if t.profit > 0]
    lose = [t for t in all_trades if t.profit <= 0]

    avg_hd = round(sum(t.holding_days for t in all_trades) / len(all_trades), 1) if all_trades else 0

    logger.info(f"回测完成: 交易{len(all_trades)}笔, 续持{held_count}次, "
                f"跳过{len(skipped_trades)}笔, 收益{total_return_pct:+.2f}%")

    return StrategyResult(
        config=config,
        start_date=start_date,
        end_date=end_date,
        initial_capital=config.initial_capital,
        final_capital=round(cash, 2),
        total_return=round(total_return, 2),
        total_return_pct=round(total_return_pct, 2),
        annualized_return_pct=round(annualized, 2),
        total_trades=len(all_trades),
        win_trades=len(win),
        lose_trades=len(lose),
        skipped_trades=len(skipped_trades),
        win_rate=round(len(win) / len(all_trades) * 100, 1) if all_trades else 0,
        total_fees=round(sum(t.fees for t in all_trades), 2),
        max_single_profit=round(max(profits), 2) if profits else 0,
        max_single_loss=round(min(profits), 2) if profits else 0,
        avg_profit_per_trade=round(sum(profits) / len(profits), 2) if profits else 0,
        avg_holding_days=avg_hd,
        equity_curve=equity_curve,
        trades=all_trades,
        skipped=skipped_trades,
    )
