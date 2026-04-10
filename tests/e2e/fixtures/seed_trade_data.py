"""合成交易记录数据工厂

Tables: trade_order, trade_position, trade_daily_report
模拟 1 个月 (2024-06-03 ~ 2024-06-28) 的模拟盘交易:
- 10 笔委托 (buy/sell, filled/cancelled)
- 每日持仓快照
- 每日绩效报告
"""
from datetime import date, datetime, timedelta
from typing import List

import numpy as np

from src.data.models import TradeOrder, TradePosition, TradeDailyReport


SEED = 42
TRADE_START = date(2024, 6, 3)


def create_trade_orders(session) -> List[TradeOrder]:
    orders = [
        TradeOrder(
            order_id="E2E-ORD-001", account_type="paper",
            code="000001.SZ", direction="buy", quantity=1000,
            price=15.20, price_type="limit", status="filled",
            filled_quantity=1000, filled_price=15.18, fees=15.18,
            created_at=datetime(2024, 6, 3, 9, 35),
        ),
        TradeOrder(
            order_id="E2E-ORD-002", account_type="paper",
            code="000005.SZ", direction="buy", quantity=500,
            price=12.50, price_type="limit", status="filled",
            filled_quantity=500, filled_price=12.48, fees=6.24,
            created_at=datetime(2024, 6, 3, 10, 10),
        ),
        TradeOrder(
            order_id="E2E-ORD-003", account_type="paper",
            code="000041.SZ", direction="buy", quantity=2000,
            price=10.30, price_type="market", status="filled",
            filled_quantity=2000, filled_price=10.32, fees=20.64,
            created_at=datetime(2024, 6, 4, 9, 32),
        ),
        TradeOrder(
            order_id="E2E-ORD-004", account_type="paper",
            code="000001.SZ", direction="sell", quantity=1000,
            price=16.00, price_type="limit", status="filled",
            filled_quantity=1000, filled_price=16.02, fees=16.02,
            created_at=datetime(2024, 6, 10, 14, 30),
        ),
        TradeOrder(
            order_id="E2E-ORD-005", account_type="paper",
            code="000015.SZ", direction="buy", quantity=800,
            price=8.00, price_type="limit", status="cancelled",
            filled_quantity=0, filled_price=0, fees=0,
            created_at=datetime(2024, 6, 11, 10, 0),
        ),
        TradeOrder(
            order_id="E2E-ORD-006", account_type="paper",
            code="000015.SZ", direction="buy", quantity=800,
            price=7.80, price_type="limit", status="filled",
            filled_quantity=800, filled_price=7.82, fees=6.26,
            created_at=datetime(2024, 6, 12, 9, 45),
        ),
        TradeOrder(
            order_id="E2E-ORD-007", account_type="paper",
            code="000015.SZ", direction="sell", quantity=800,
            price=7.20, price_type="market", status="filled",
            filled_quantity=800, filled_price=7.18, fees=5.74,
            created_at=datetime(2024, 6, 18, 14, 50),
        ),
        TradeOrder(
            order_id="E2E-ORD-008", account_type="paper",
            code="000025.SZ", direction="buy", quantity=1500,
            price=10.00, price_type="limit", status="filled",
            filled_quantity=1500, filled_price=9.98, fees=14.97,
            created_at=datetime(2024, 6, 20, 9, 40),
        ),
    ]
    session.add_all(orders)
    session.flush()
    return orders


def create_trade_positions(session) -> List[TradePosition]:
    rng = np.random.RandomState(SEED + 30)
    positions = []
    d = TRADE_START
    end = date(2024, 6, 28)

    holdings = {
        "000005.SZ": {"qty": 500, "cost": 12.48},
        "000041.SZ": {"qty": 2000, "cost": 10.32},
    }

    while d <= end:
        if d.weekday() < 5:
            for code, info in holdings.items():
                price_change = float(rng.normal(0, 0.02))
                market_price = round(info["cost"] * (1 + price_change), 2)
                market_value = round(market_price * info["qty"], 2)
                profit = round((market_price - info["cost"]) * info["qty"], 2)
                profit_pct = round((market_price / info["cost"] - 1) * 100, 2)

                positions.append(TradePosition(
                    snapshot_date=d, account_type="paper",
                    code=code, quantity=info["qty"],
                    cost_price=info["cost"], market_price=market_price,
                    market_value=market_value, profit=profit,
                    profit_pct=profit_pct,
                ))
        d += timedelta(days=1)

    session.bulk_save_objects(positions)
    session.flush()
    return positions


def create_trade_daily_reports(session) -> List[TradeDailyReport]:
    rng = np.random.RandomState(SEED + 31)
    reports = []
    d = TRADE_START
    end = date(2024, 6, 28)
    initial_assets = 1_000_000.0
    total_assets = initial_assets
    max_assets = total_assets
    max_dd = 0.0

    while d <= end:
        if d.weekday() < 5:
            daily_ret = float(rng.normal(0.0003, 0.008))
            total_assets *= (1 + daily_ret)
            max_assets = max(max_assets, total_assets)
            drawdown = (max_assets - total_assets) / max_assets
            max_dd = max(max_dd, drawdown)
            cum_return = (total_assets - initial_assets) / initial_assets

            market_val = round(total_assets * 0.6, 2)
            cash = round(total_assets - market_val, 2)

            reports.append(TradeDailyReport(
                report_date=d, account_type="paper",
                total_assets=round(total_assets, 2),
                cash=cash, market_value=market_val,
                daily_return=round(daily_ret * 100, 4),
                cumulative_return=round(cum_return * 100, 4),
                max_drawdown=round(max_dd * 100, 4),
            ))
        d += timedelta(days=1)

    session.bulk_save_objects(reports)
    session.flush()
    return reports
