"""合成财务数据工厂

Tables: stock_financial_report, stock_financial_indicator
50 只股票 × 4 个季度报告期, 数值与行情走势关联:
  上涨股 (1~10): ROE 高, 利润正增长
  下跌股 (11~20): ROE 低, 利润负增长
"""
from datetime import date
from typing import List

import numpy as np

from src.data.models import StockFinancialReport, StockFinancialIndicator, Stock

SEED = 42
REPORT_PERIODS = [
    ("2024Q1", date(2024, 4, 25)),
    ("2024Q2", date(2024, 8, 28)),
    ("2024Q3", date(2024, 10, 30)),
    ("2024Q4", date(2025, 3, 28)),
]


def create_financial_reports(session, stocks: List[Stock]) -> List[StockFinancialReport]:
    rng = np.random.RandomState(SEED)
    reports = []

    for stock in stocks:
        num = int(stock.code[:6])
        base_revenue = 50.0 + rng.uniform(-5, 15)
        base_profit = base_revenue * (0.15 if num <= 10 else 0.05 if num <= 20 else 0.10)

        for period, report_date in REPORT_PERIODS:
            growth = 1.0 + rng.uniform(0.02, 0.08) if num <= 10 else (
                1.0 + rng.uniform(-0.08, -0.01) if num <= 20 else
                1.0 + rng.uniform(-0.02, 0.04)
            )
            revenue = round(base_revenue * growth, 2)
            net_profit = round(base_profit * growth, 2)
            total_assets = round(revenue * rng.uniform(3.0, 5.0), 2)
            total_liabilities = round(total_assets * rng.uniform(0.3, 0.6), 2)
            total_equity = round(total_assets - total_liabilities, 2)

            r = StockFinancialReport(
                code=stock.code,
                report_type="annual" if "Q4" in period else "quarterly",
                report_period=period,
                report_date=report_date,
                total_assets=total_assets,
                total_liabilities=total_liabilities,
                total_equity=total_equity,
                total_revenue=revenue,
                operating_profit=round(net_profit * 1.15, 2),
                net_profit=net_profit,
                gross_profit=round(revenue * 0.35, 2),
                net_cash_flow=round(net_profit * rng.uniform(0.8, 1.3), 2),
                operating_cash_flow=round(net_profit * rng.uniform(0.9, 1.5), 2),
                gross_margin=round(35 + rng.uniform(-5, 5), 2),
                net_margin=round(net_profit / revenue * 100, 2) if revenue > 0 else 0,
                roe=round(net_profit / total_equity * 100, 2) if total_equity > 0 else 0,
                roa=round(net_profit / total_assets * 100, 2) if total_assets > 0 else 0,
                debt_ratio=round(total_liabilities / total_assets * 100, 2),
                current_ratio=round(rng.uniform(1.2, 2.5), 2),
            )
            reports.append(r)
            base_revenue = revenue

    session.bulk_save_objects(reports)
    session.flush()
    return reports


def create_financial_indicators(session, stocks: List[Stock]) -> List[StockFinancialIndicator]:
    rng = np.random.RandomState(SEED + 1)
    indicators = []

    for stock in stocks:
        num = int(stock.code[:6])
        for _, report_date in REPORT_PERIODS:
            rev_growth = round(rng.uniform(5, 20), 2) if num <= 10 else (
                round(rng.uniform(-15, -2), 2) if num <= 20 else
                round(rng.uniform(-3, 8), 2)
            )
            profit_growth = round(rev_growth * rng.uniform(0.8, 1.5), 2)

            ind = StockFinancialIndicator(
                code=stock.code,
                report_date=report_date,
                eps_basic=round(rng.uniform(0.3, 2.0), 4),
                bps=round(rng.uniform(3.0, 15.0), 4),
                roe_weighted=round(rng.uniform(8, 25), 2) if num <= 10 else round(rng.uniform(2, 10), 2),
                net_profit_margin=round(rng.uniform(8, 20), 2),
                gross_profit_margin=round(rng.uniform(25, 45), 2),
                debt_asset_ratio=round(rng.uniform(30, 60), 2),
                current_ratio=round(rng.uniform(1.2, 2.5), 2),
                revenue_growth=rev_growth,
                profit_growth=profit_growth,
            )
            indicators.append(ind)

    session.bulk_save_objects(indicators)
    session.flush()
    return indicators
