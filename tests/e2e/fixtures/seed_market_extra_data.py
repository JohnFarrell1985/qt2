"""合成市场扩展数据工厂

Tables: market_index, sector_stock, index_weight
- 3 只指数 × 252 交易日
- 10 个行业板块, 每板块 5 只成分股
- 沪深300 成分权重
"""
from typing import List

import numpy as np

from src.data.models import MarketIndex, SectorStock, IndexWeight, Stock, TradingDate


SEED = 42
INDICES = [
    ("000001.SH", "上证指数", 3000.0, 0.0005),
    ("399001.SZ", "深证成指", 10000.0, 0.0003),
    ("000300.SH", "沪深300", 4000.0, 0.0004),
]


def create_market_index(session, trading_dates: List[TradingDate]) -> List[MarketIndex]:
    rng = np.random.RandomState(SEED + 10)
    dates = [td.trade_date for td in trading_dates]
    all_rows = []

    for code, name, start_price, daily_drift in INDICES:
        prices = np.zeros(len(dates))
        prices[0] = start_price

        for j in range(1, len(dates)):
            ret = daily_drift + rng.normal(0, 0.01)
            prices[j] = prices[j - 1] * (1 + ret)

        for j, d in enumerate(dates):
            close = round(float(prices[j]), 2)
            prev = round(float(prices[j - 1]), 2) if j > 0 else close
            high = round(close * (1 + abs(rng.normal(0, 0.005))), 2)
            low = round(close * (1 - abs(rng.normal(0, 0.005))), 2)
            open_p = round(prev * (1 + rng.normal(0, 0.003)), 2)
            change_pct = round((close - prev) / prev * 100, 4) if prev > 0 else 0

            row = MarketIndex(
                index_code=code,
                index_name=name,
                trade_date=d,
                open=open_p,
                high=high,
                low=low,
                close=close,
                change_pct=change_pct,
                volume=int(rng.uniform(100_000_000, 500_000_000)),
                amount=round(float(rng.uniform(1e10, 5e10)), 2),
            )
            all_rows.append(row)

    session.bulk_save_objects(all_rows)
    session.flush()
    return all_rows


def create_sector_stocks(session, stocks: List[Stock]) -> List[SectorStock]:
    industries = ["银行", "电子", "医药", "食品饮料", "新能源",
                  "房地产", "计算机", "通信", "汽车", "化工"]
    rows = []
    for stock in stocks:
        idx = (int(stock.code[:6]) - 1) % len(industries)
        rows.append(SectorStock(
            sector_name=industries[idx],
            stock_code=stock.code,
        ))
    session.add_all(rows)
    session.flush()
    return rows


def create_index_weights(session, stocks: List[Stock]) -> List[IndexWeight]:
    rng = np.random.RandomState(SEED + 20)
    selected = stocks[:30]
    raw_weights = rng.dirichlet(np.ones(len(selected))) * 100
    rows = []
    for i, stock in enumerate(selected):
        rows.append(IndexWeight(
            index_code="000300.SH",
            stock_code=stock.code,
            weight=round(float(raw_weights[i]), 4),
        ))
    session.add_all(rows)
    session.flush()
    return rows
