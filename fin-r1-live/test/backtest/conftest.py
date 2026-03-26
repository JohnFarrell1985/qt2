"""
backtest 测试公共 fixtures

engine/cli/strategy_runner/strategy_cli 中的数据库调用通过 mock 替代，无需真实数据库连接。
data_loader 测试在各自文件中直接 mock SessionLocal。
"""
import sys
import os
from datetime import date
from unittest.mock import patch
from typing import Dict, List, Optional, Any

import pytest

DATA_HUB_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data-hub"))
if DATA_HUB_DIR not in sys.path:
    sys.path.insert(0, DATA_HUB_DIR)


# ======== 模拟行情数据 ========

MOCK_DAILY_DATA: Dict[str, List[Dict[str, Any]]] = {
    "000001": [
        {"code": "000001", "trade_date": date(2025, 1, 2), "open": 10.0, "high": 10.5,
         "low": 9.8, "close": 10.2, "volume": 500000, "amount": 5100000.0,
         "change_pct": 1.0, "pre_close": 10.1},
        {"code": "000001", "trade_date": date(2025, 1, 3), "open": 10.2, "high": 10.8,
         "low": 10.0, "close": 10.5, "volume": 600000, "amount": 6300000.0,
         "change_pct": 2.94, "pre_close": 10.2},
        {"code": "000001", "trade_date": date(2025, 1, 6), "open": 10.5, "high": 11.0,
         "low": 10.3, "close": 10.8, "volume": 700000, "amount": 7560000.0,
         "change_pct": 2.86, "pre_close": 10.5},
        {"code": "000001", "trade_date": date(2025, 1, 7), "open": 10.8, "high": 10.9,
         "low": 10.1, "close": 10.3, "volume": 550000, "amount": 5665000.0,
         "change_pct": -4.63, "pre_close": 10.8},
        {"code": "000001", "trade_date": date(2025, 1, 8), "open": 10.3, "high": 10.6,
         "low": 10.2, "close": 10.5, "volume": 480000, "amount": 5040000.0,
         "change_pct": 1.94, "pre_close": 10.3},
    ],
    "600519": [
        {"code": "600519", "trade_date": date(2025, 1, 2), "open": 1500.0, "high": 1520.0,
         "low": 1490.0, "close": 1510.0, "volume": 30000, "amount": 45300000.0,
         "change_pct": 0.67, "pre_close": 1500.0},
        {"code": "600519", "trade_date": date(2025, 1, 3), "open": 1510.0, "high": 1550.0,
         "low": 1505.0, "close": 1540.0, "volume": 35000, "amount": 53900000.0,
         "change_pct": 1.99, "pre_close": 1510.0},
        {"code": "600519", "trade_date": date(2025, 1, 6), "open": 1540.0, "high": 1560.0,
         "low": 1530.0, "close": 1555.0, "volume": 32000, "amount": 49760000.0,
         "change_pct": 0.97, "pre_close": 1540.0},
        {"code": "600519", "trade_date": date(2025, 1, 7), "open": 1555.0, "high": 1560.0,
         "low": 1540.0, "close": 1545.0, "volume": 28000, "amount": 43260000.0,
         "change_pct": -0.64, "pre_close": 1555.0},
        {"code": "600519", "trade_date": date(2025, 1, 8), "open": 1545.0, "high": 1570.0,
         "low": 1542.0, "close": 1565.0, "volume": 34000, "amount": 53210000.0,
         "change_pct": 1.29, "pre_close": 1545.0},
        {"code": "600519", "trade_date": date(2025, 2, 5), "open": 1500.0, "high": 1520.0,
         "low": 1490.0, "close": 1510.0, "volume": 30000, "amount": 45300000.0,
         "change_pct": 0.67, "pre_close": 1500.0},
        {"code": "600519", "trade_date": date(2025, 2, 6), "open": 1510.0, "high": 1550.0,
         "low": 1505.0, "close": 1540.0, "volume": 35000, "amount": 53900000.0,
         "change_pct": 1.99, "pre_close": 1510.0},
    ],
    "000002": [
        {"code": "000002", "trade_date": date(2025, 1, 2), "open": 8.0, "high": 8.3,
         "low": 7.9, "close": 8.2, "volume": 800000, "amount": 6560000.0,
         "change_pct": 2.5, "pre_close": 8.0},
        {"code": "000002", "trade_date": date(2025, 1, 3), "open": 8.2, "high": 8.5,
         "low": 8.1, "close": 8.4, "volume": 750000, "amount": 6300000.0,
         "change_pct": 2.44, "pre_close": 8.2},
        {"code": "000002", "trade_date": date(2025, 1, 6), "open": 8.4, "high": 8.6,
         "low": 8.3, "close": 8.5, "volume": 700000, "amount": 5950000.0,
         "change_pct": 1.19, "pre_close": 8.4},
        {"code": "000002", "trade_date": date(2025, 1, 7), "open": 8.5, "high": 8.5,
         "low": 8.0, "close": 8.1, "volume": 900000, "amount": 7290000.0,
         "change_pct": -4.71, "pre_close": 8.5},
        {"code": "000002", "trade_date": date(2025, 1, 8), "open": 8.1, "high": 8.3,
         "low": 8.0, "close": 8.2, "volume": 650000, "amount": 5330000.0,
         "change_pct": 1.23, "pre_close": 8.1},
    ],
    # 涨停测试 — 000099 在 1/3 涨停开盘
    "000099": [
        {"code": "000099", "trade_date": date(2025, 1, 2), "open": 20.0, "high": 20.5,
         "low": 19.8, "close": 20.0, "volume": 200000, "amount": 4000000.0,
         "change_pct": 0.0, "pre_close": 20.0},
        {"code": "000099", "trade_date": date(2025, 1, 3), "open": 22.0, "high": 22.0,
         "low": 22.0, "close": 22.0, "volume": 50000, "amount": 1100000.0,
         "change_pct": 10.0, "pre_close": 20.0},
        {"code": "000099", "trade_date": date(2025, 1, 6), "open": 21.5, "high": 22.0,
         "low": 21.0, "close": 21.8, "volume": 300000, "amount": 6540000.0,
         "change_pct": -0.91, "pre_close": 22.0},
    ],
    "00700": [
        {"code": "00700", "trade_date": date(2025, 3, 3), "open": 380.0, "high": 390.0,
         "low": 375.0, "close": 385.0, "volume": 100000, "amount": 38500000.0,
         "change_pct": 1.32, "pre_close": 380.0},
        {"code": "00700", "trade_date": date(2025, 3, 4), "open": 385.0, "high": 395.0,
         "low": 380.0, "close": 392.0, "volume": 120000, "amount": 47040000.0,
         "change_pct": 1.82, "pre_close": 385.0},
        {"code": "00700", "trade_date": date(2025, 3, 5), "open": 392.0, "high": 400.0,
         "low": 388.0, "close": 398.0, "volume": 110000, "amount": 43780000.0,
         "change_pct": 1.53, "pre_close": 392.0},
    ],
    "HK00700": [
        {"code": "HK00700", "trade_date": date(2025, 3, 3), "open": 380.0, "high": 390.0,
         "low": 375.0, "close": 385.0, "volume": 100000, "amount": 38500000.0,
         "change_pct": 1.32, "pre_close": 380.0},
        {"code": "HK00700", "trade_date": date(2025, 3, 5), "open": 392.0, "high": 400.0,
         "low": 388.0, "close": 398.0, "volume": 110000, "amount": 43780000.0,
         "change_pct": 1.53, "pre_close": 392.0},
    ],
}

MOCK_STOCK_NAMES = {
    "000001": "平安银行",
    "000002": "万科A",
    "000099": "涨停测试",
    "600519": "贵州茅台",
    "00700": "腾讯控股",
    "HK00700": "腾讯控股",
}

MOCK_DATA_RANGES = {
    "000001": {"min_date": date(2024, 1, 2), "max_date": date(2025, 12, 31), "total_days": 480},
    "600519": {"min_date": date(2024, 1, 2), "max_date": date(2025, 12, 31), "total_days": 480},
    "00700": {"min_date": date(2025, 1, 2), "max_date": date(2025, 12, 31), "total_days": 240},
}

# 全局交易日集合 (用于 strategy_runner 的 get_trading_dates / get_next_trading_date)
ALL_TRADING_DATES: List[date] = sorted({
    row["trade_date"]
    for code_data in MOCK_DAILY_DATA.values()
    for row in code_data
})


def mock_get_close_price(code: str, trade_date: date) -> Optional[float]:
    rows = MOCK_DAILY_DATA.get(code, [])
    candidates = [r for r in rows if r["trade_date"] <= trade_date]
    if candidates:
        candidates.sort(key=lambda r: r["trade_date"], reverse=True)
        return candidates[0]["close"]
    return None


def mock_get_daily_data(code: str, start_date: date, end_date: date) -> List[Dict[str, Any]]:
    rows = MOCK_DAILY_DATA.get(code, [])
    return [r for r in rows if start_date <= r["trade_date"] <= end_date]


def mock_get_stock_name(code: str) -> Optional[str]:
    return MOCK_STOCK_NAMES.get(code)


def mock_get_data_range(code: str) -> Optional[Dict]:
    return MOCK_DATA_RANGES.get(code)


def mock_get_open_price_exact(code: str, trade_date: date) -> Optional[Dict[str, Any]]:
    rows = MOCK_DAILY_DATA.get(code, [])
    for r in rows:
        if r["trade_date"] == trade_date:
            return {
                "open": r["open"],
                "close": r["close"],
                "pre_close": r.get("pre_close"),
                "high": r["high"],
                "low": r["low"],
                "change_pct": r.get("change_pct"),
                "trade_date": r["trade_date"],
            }
    return None


def mock_get_trading_dates(start_date: date, end_date: date) -> List[date]:
    return [d for d in ALL_TRADING_DATES if start_date <= d <= end_date]


def mock_get_next_trading_date(from_date: date) -> Optional[date]:
    future = [d for d in ALL_TRADING_DATES if d > from_date]
    return future[0] if future else None


def mock_load_prompt(name="prompt1.txt", trade_date=None, **kwargs):
    """Mock load_prompt — 返回含日期的简单字符串"""
    if trade_date is None:
        trade_date = date.today()
    cn = f"{trade_date.year}年{trade_date.month}月{trade_date.day}日"
    return f"测试提示词 日期={cn}"


@pytest.fixture(autouse=True)
def patch_engine_and_cli():
    """Mock engine/cli/strategy_runner/strategy_cli 中的数据库调用"""
    with patch("backtest.engine.get_close_price", side_effect=mock_get_close_price), \
         patch("backtest.engine.get_daily_data", side_effect=mock_get_daily_data), \
         patch("backtest.engine.get_stock_name", side_effect=mock_get_stock_name), \
         patch("backtest.engine.get_data_range", side_effect=mock_get_data_range), \
         patch("backtest.cli.get_stock_name", side_effect=mock_get_stock_name), \
         patch("backtest.cli.get_data_range", side_effect=mock_get_data_range), \
         patch("backtest.strategy_runner.get_open_price_exact", side_effect=mock_get_open_price_exact), \
         patch("backtest.strategy_runner.get_trading_dates", side_effect=mock_get_trading_dates), \
         patch("backtest.strategy_runner.get_next_trading_date", side_effect=mock_get_next_trading_date), \
         patch("backtest.stock_picker.load_prompt", side_effect=mock_load_prompt), \
         patch("backtest.strategy_cli.get_trading_dates", side_effect=mock_get_trading_dates):
        yield
