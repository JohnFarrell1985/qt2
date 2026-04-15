"""合成行情数据工厂

50 stocks × 252 trading days, 确定性种子, 分组行为:
- 000001~000010: 稳定上涨 (+0.3%/日)   → 动量策略应选中
- 000011~000020: 稳定下跌 (-0.2%/日)   → 止损应触发
- 000021~000030: 均值回归 (振荡 ±2%)   → 反转策略目标
- 000031~000040: 高波动 (随机游走, vol=3%) → 低波红利应排除
- 000041~000050: 低波稳定 (+0.05%/日)  → 红利策略目标
"""
from datetime import date, timedelta
from typing import List

import numpy as np

from src.data.models import Stock, StockDaily, TradingDate


SEED = 42
N_STOCKS = 50
INITIAL_PRICE = 10.0
START_DATE = date(2024, 1, 2)
YEAR = 2024


def _generate_trading_dates(year: int = YEAR) -> List[date]:
    """生成 ~252 个交易日 (排除周末)"""
    dates = []
    d = date(year, 1, 2)
    end = date(year, 12, 31)
    while d <= end:
        if d.weekday() < 5:
            dates.append(d)
        d += timedelta(days=1)
    return dates[:252]


def create_stocks(session, count: int = N_STOCKS) -> List[Stock]:
    industries = ["银行", "电子", "医药", "食品饮料", "新能源",
                  "房地产", "计算机", "通信", "汽车", "化工"]
    stocks = []
    for i in range(1, count + 1):
        code = f"{i:06d}.SZ"
        s = Stock(
            code=code,
            name=f"测试股票{i:03d}",
            exchange="SZ",
            industry=industries[(i - 1) % len(industries)],
            sector="主板",
            pe_ttm=15.0 + i * 0.5,
            pb=1.5 + i * 0.1,
            roe=10.0 + (i % 20),
            market_cap=100.0 + i * 10,
        )
        stocks.append(s)
    session.add_all(stocks)
    session.flush()
    return stocks


def create_trading_dates(session, year: int = YEAR) -> List[TradingDate]:
    dates = _generate_trading_dates(year)
    td_objs = []
    for d in dates:
        td = TradingDate(market="SZ", trade_date=d, is_holiday=False)
        td_objs.append(td)
    session.add_all(td_objs)
    session.flush()
    return td_objs


def create_stock_daily(
    session, stocks: List[Stock], trading_dates: List[TradingDate],
) -> List[StockDaily]:
    rng = np.random.RandomState(SEED)
    dates = [td.trade_date for td in trading_dates]
    n_days = len(dates)
    all_rows: List[StockDaily] = []

    for idx, stock in enumerate(stocks):
        stock_num = idx + 1
        prices = np.zeros(n_days)
        prices[0] = INITIAL_PRICE

        if stock_num <= 10:
            daily_ret = 0.003
            noise_std = 0.005
        elif stock_num <= 20:
            daily_ret = -0.002
            noise_std = 0.005
        elif stock_num <= 30:
            daily_ret = 0.0
            noise_std = 0.02
        elif stock_num <= 40:
            daily_ret = 0.0
            noise_std = 0.03
        else:
            daily_ret = 0.0005
            noise_std = 0.005

        for j in range(1, n_days):
            ret = daily_ret + rng.normal(0, noise_std)
            prices[j] = prices[j - 1] * (1 + ret)
            prices[j] = max(prices[j], 1.0)

        for j in range(n_days):
            close = round(float(prices[j]), 2)
            prev_close = round(float(prices[j - 1]), 2) if j > 0 else close
            noise_h = abs(float(rng.normal(0, 0.005))) * close
            noise_l = abs(float(rng.normal(0, 0.005))) * close
            high = round(max(close, prev_close) + noise_h, 2)
            low = round(min(close, prev_close) - noise_l, 2)
            low = max(low, 0.5)
            open_p = round(prev_close + float(rng.normal(0, 0.003)) * prev_close, 2)
            open_p = max(open_p, 0.5)

            volume = int(rng.uniform(1_000_000, 5_000_000))
            amount = round(close * volume, 2)
            change = round(close - prev_close, 4)
            change_pct = round(change / prev_close * 100, 4) if prev_close > 0 else 0.0
            turnover = round(float(rng.uniform(0.5, 5.0)), 4)
            amplitude = round((high - low) / prev_close * 100, 4) if prev_close > 0 else 0.0

            row = StockDaily(
                code=stock.code,
                trade_date=dates[j],
                open=open_p,
                high=high,
                low=low,
                close=close,
                pre_close=prev_close,
                volume=volume,
                amount=amount,
                turnover_rate=turnover,
                change=change,
                change_pct=change_pct,
                amplitude=amplitude,
            )
            all_rows.append(row)

    session.bulk_save_objects(all_rows)
    session.flush()
    return all_rows
