"""合成可转债数据工厂

Tables: convertible_bond, cb_daily
5 只可转债 × 60 交易日行情
"""
from datetime import date
from typing import List

import numpy as np

from src.data.models import ConvertibleBond, CBDaily, TradingDate

SEED = 42

CB_DEFS = [
    ("123001.SZ", "测试转债A", "000001.SZ", 15.0, "AA+", 10.0),
    ("123002.SZ", "测试转债B", "000005.SZ", 12.0, "AA", 5.0),
    ("123003.SZ", "测试转债C", "000010.SZ", 18.0, "AA+", 8.0),
    ("127001.SZ", "测试转债D", "000025.SZ", 10.0, "A+", 3.0),
    ("127002.SZ", "测试转债E", "000041.SZ", 11.0, "AAA", 15.0),
]


def create_convertible_bonds(session) -> List[ConvertibleBond]:
    bonds = []
    for code, name, stock_code, conv_price, level, issue_amt in CB_DEFS:
        bonds.append(ConvertibleBond(
            code=code,
            bond_name=name,
            stock_code=stock_code,
            convert_price=conv_price,
            convert_start_date="20240601",
            convert_end_date="20300101",
            maturity_date="20300601",
            issue_amount=issue_amt,
            remain_amount=round(issue_amt * 0.8, 2),
            level=level,
            analConvpremiumratio=round(5.0 + issue_amt * 0.3, 2),
            pure_bond_value=round(95 + issue_amt * 0.2, 2),
        ))
    session.add_all(bonds)
    session.flush()
    return bonds


def create_cb_daily(
    session, bonds: List[ConvertibleBond], trading_dates: List[TradingDate],
) -> List[CBDaily]:
    rng = np.random.RandomState(SEED + 50)
    dates = [td.trade_date for td in trading_dates][:60]
    all_rows = []

    for bond in bonds:
        price = 100.0 + rng.uniform(-5, 10)
        for d in dates:
            ret = rng.normal(0.0002, 0.008)
            price *= (1 + ret)
            price = max(price, 80.0)
            close = round(price, 2)
            high = round(close * (1 + abs(rng.normal(0, 0.005))), 2)
            low = round(close * (1 - abs(rng.normal(0, 0.005))), 2)
            open_p = round(close * (1 + rng.normal(0, 0.003)), 2)

            all_rows.append(CBDaily(
                code=bond.code,
                trade_date=d,
                open=open_p, high=high, low=low, close=close,
                volume=int(rng.uniform(10_000, 500_000)),
                amount=round(close * rng.uniform(10_000, 500_000), 2),
            ))

    session.bulk_save_objects(all_rows)
    session.flush()
    return all_rows
