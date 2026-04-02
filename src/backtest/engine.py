"""
回溯计算引擎

方法一: 单笔交易盈亏 - 输入买卖点，计算盈亏
方法二: 区间统计 - 多笔交易汇总统计
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional, Dict, Any

from .fees import (
    FeeConfig, TradeFees, calc_buy_fees, calc_sell_fees,
    HKFeeConfig, HKTradeFees, calc_hk_buy_fees, calc_hk_sell_fees,
    detect_market,
)
from .data_loader import get_close_price, get_daily_data, get_stock_name, get_data_range


@dataclass
class TradeResult:
    """单笔交易结果"""
    code: str
    name: Optional[str]

    # 买入
    buy_date: date
    buy_price: float
    buy_quantity: int
    buy_amount: float
    buy_fees: TradeFees

    # 卖出
    sell_date: date
    sell_price: float
    sell_quantity: int
    sell_amount: float
    sell_fees: TradeFees

    # 盈亏
    total_fees: float
    net_profit: float
    profit_pct: float
    holding_days: int

    # 区间行情参考
    period_high: Optional[float] = None
    period_low: Optional[float] = None
    max_drawdown_pct: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "buy_date": self.buy_date.isoformat(),
            "buy_price": self.buy_price,
            "buy_quantity": self.buy_quantity,
            "buy_amount": self.buy_amount,
            "buy_fees": {
                "commission": self.buy_fees.commission,
                "stamp_tax": self.buy_fees.stamp_tax,
                "transfer_fee": self.buy_fees.transfer_fee,
                "total": self.buy_fees.total,
            },
            "sell_date": self.sell_date.isoformat(),
            "sell_price": self.sell_price,
            "sell_quantity": self.sell_quantity,
            "sell_amount": self.sell_amount,
            "sell_fees": {
                "commission": self.sell_fees.commission,
                "stamp_tax": self.sell_fees.stamp_tax,
                "transfer_fee": self.sell_fees.transfer_fee,
                "total": self.sell_fees.total,
            },
            "total_fees": self.total_fees,
            "net_profit": self.net_profit,
            "profit_pct": self.profit_pct,
            "holding_days": self.holding_days,
            "period_high": self.period_high,
            "period_low": self.period_low,
            "max_drawdown_pct": self.max_drawdown_pct,
        }


@dataclass
class PortfolioSummary:
    """多笔交易汇总统计"""
    start_date: date
    end_date: date
    total_trades: int
    win_trades: int
    lose_trades: int
    win_rate: float

    total_invested: float       # 总投入金额
    total_returned: float       # 总收回金额
    total_fees: float           # 总手续费
    net_profit: float           # 净盈亏
    profit_pct: float           # 总收益率 (基于总投入)

    max_single_profit: float    # 单笔最大盈利
    max_single_loss: float      # 单笔最大亏损
    avg_profit_per_trade: float # 平均每笔盈亏
    avg_holding_days: float     # 平均持仓天数

    trades: List[TradeResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "period": f"{self.start_date.isoformat()} ~ {self.end_date.isoformat()}",
            "total_trades": self.total_trades,
            "win_trades": self.win_trades,
            "lose_trades": self.lose_trades,
            "win_rate": f"{self.win_rate:.1f}%",
            "total_invested": self.total_invested,
            "total_returned": self.total_returned,
            "total_fees": self.total_fees,
            "net_profit": self.net_profit,
            "profit_pct": f"{self.profit_pct:.2f}%",
            "max_single_profit": self.max_single_profit,
            "max_single_loss": self.max_single_loss,
            "avg_profit_per_trade": self.avg_profit_per_trade,
            "avg_holding_days": self.avg_holding_days,
        }


def calc_single_trade(
    code: str,
    buy_date: date,
    sell_date: date,
    quantity: int = 0,
    buy_amount: float = 0.0,
    fee_config: FeeConfig = None,
    hk_fee_config: HKFeeConfig = None,
) -> TradeResult:
    """
    方法一: 计算单笔交易盈亏 (自动检测A股/港股通)

    参数:
        code: 股票代码 (A股如'000001', 港股通如'00700'或'HK00700')
        buy_date: 买入日期
        sell_date: 卖出日期
        quantity: 买入股数 (与 buy_amount 二选一, quantity优先)
        buy_amount: 买入金额 (用于按金额计算可买股数)
        fee_config: A股手续费配置
        hk_fee_config: 港股通手续费配置

    返回:
        TradeResult 交易结果
    """
    market = detect_market(code)

    if sell_date <= buy_date:
        raise ValueError(f"卖出日期 {sell_date} 必须晚于买入日期 {buy_date}")

    # 查询买卖日收盘价
    buy_price = get_close_price(code, buy_date)
    if buy_price is None:
        raise ValueError(f"无法获取 {code} 在 {buy_date} 附近的收盘价，请检查数据库")

    sell_price = get_close_price(code, sell_date)
    if sell_price is None:
        raise ValueError(f"无法获取 {code} 在 {sell_date} 附近的收盘价，请检查数据库")

    # 计算实际股数
    # A股最小交易单位100股; 港股按手数交易(每手不同,此处简化为1股)
    if market == "HK":
        lot_size = 1  # 港股不强制整手(碎股可卖), 简化处理
    else:
        lot_size = 100

    if quantity > 0:
        if lot_size > 1:
            actual_qty = (quantity // lot_size) * lot_size
            if actual_qty == 0:
                actual_qty = lot_size
        else:
            actual_qty = quantity
    elif buy_amount > 0:
        if lot_size > 1:
            actual_qty = int(buy_amount / buy_price / lot_size) * lot_size
        else:
            actual_qty = int(buy_amount / buy_price)
        if actual_qty == 0:
            raise ValueError(
                f"金额 {buy_amount:.2f} 不足以买入 {code} (需 {buy_price * lot_size:.2f})"
            )
    else:
        raise ValueError("必须指定 quantity(股数) 或 buy_amount(金额) 之一")

    # 费用计算 - 按市场类型分别计算
    if market == "HK":
        if hk_fee_config is None:
            hk_fee_config = HKFeeConfig()
        hk_buy = calc_hk_buy_fees(buy_price, actual_qty, code, hk_fee_config)
        hk_sell = calc_hk_sell_fees(sell_price, actual_qty, code, hk_fee_config)
        # 统一映射到 TradeFees (commission=佣金, stamp_tax=印花税, transfer_fee=其余杂费)
        buy_fees = TradeFees(
            commission=hk_buy.commission,
            stamp_tax=hk_buy.stamp_tax,
            transfer_fee=round(hk_buy.trading_fee + hk_buy.transaction_levy
                               + hk_buy.frc_levy + hk_buy.settlement_fee, 2),
        )
        sell_fees = TradeFees(
            commission=hk_sell.commission,
            stamp_tax=hk_sell.stamp_tax,
            transfer_fee=round(hk_sell.trading_fee + hk_sell.transaction_levy
                               + hk_sell.frc_levy + hk_sell.settlement_fee, 2),
        )
    else:
        if fee_config is None:
            fee_config = FeeConfig()
        buy_fees = calc_buy_fees(buy_price, actual_qty, code, fee_config)
        sell_fees = calc_sell_fees(sell_price, actual_qty, code, fee_config)

    total_buy = buy_price * actual_qty + buy_fees.total
    total_sell = sell_price * actual_qty - sell_fees.total
    total_fees = buy_fees.total + sell_fees.total
    net_profit = total_sell - total_buy
    profit_pct = (net_profit / total_buy) * 100

    # 持仓期间行情
    daily = get_daily_data(code, buy_date, sell_date)
    period_high = max((d["high"] for d in daily), default=None) if daily else None
    period_low = min((d["low"] for d in daily), default=None) if daily else None

    # 最大回撤 (从持仓期间最高点到最低点)
    max_drawdown_pct = None
    if period_high and period_low and period_high > 0:
        peak = 0.0
        max_dd = 0.0
        for d in daily:
            if d["close"] and d["close"] > peak:
                peak = d["close"]
            if peak > 0 and d["close"]:
                dd = (peak - d["close"]) / peak * 100
                if dd > max_dd:
                    max_dd = dd
        max_drawdown_pct = round(max_dd, 2)

    holding_days = (sell_date - buy_date).days
    name = get_stock_name(code)

    return TradeResult(
        code=code,
        name=name,
        buy_date=buy_date,
        buy_price=buy_price,
        buy_quantity=actual_qty,
        buy_amount=round(total_buy, 2),
        buy_fees=buy_fees,
        sell_date=sell_date,
        sell_price=sell_price,
        sell_quantity=actual_qty,
        sell_amount=round(total_sell, 2),
        sell_fees=sell_fees,
        total_fees=round(total_fees, 2),
        net_profit=round(net_profit, 2),
        profit_pct=round(profit_pct, 2),
        holding_days=holding_days,
        period_high=period_high,
        period_low=period_low,
        max_drawdown_pct=max_drawdown_pct,
    )


def calc_portfolio(trades: List[TradeResult]) -> PortfolioSummary:
    """
    方法二: 多笔交易汇总统计

    参数:
        trades: 单笔交易结果列表

    返回:
        PortfolioSummary 汇总统计
    """
    if not trades:
        raise ValueError("交易列表不能为空")

    win = [t for t in trades if t.net_profit > 0]
    lose = [t for t in trades if t.net_profit <= 0]

    total_invested = sum(t.buy_amount for t in trades)
    total_returned = sum(t.sell_amount for t in trades)
    total_fees = sum(t.total_fees for t in trades)
    net_profit = total_returned - total_invested

    all_dates = [t.buy_date for t in trades] + [t.sell_date for t in trades]
    profits = [t.net_profit for t in trades]

    return PortfolioSummary(
        start_date=min(all_dates),
        end_date=max(all_dates),
        total_trades=len(trades),
        win_trades=len(win),
        lose_trades=len(lose),
        win_rate=(len(win) / len(trades)) * 100 if trades else 0,
        total_invested=round(total_invested, 2),
        total_returned=round(total_returned, 2),
        total_fees=round(total_fees, 2),
        net_profit=round(net_profit, 2),
        profit_pct=round((net_profit / total_invested) * 100, 2) if total_invested > 0 else 0,
        max_single_profit=round(max(profits), 2),
        max_single_loss=round(min(profits), 2),
        avg_profit_per_trade=round(sum(profits) / len(profits), 2),
        avg_holding_days=round(sum(t.holding_days for t in trades) / len(trades), 1),
        trades=trades,
    )
