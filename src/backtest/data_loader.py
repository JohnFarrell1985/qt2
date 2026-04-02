"""从PostgreSQL加载历史行情数据 (重构: 使用 src.common.db 共享连接)"""
from datetime import date
from typing import Optional, List, Dict, Any

from sqlalchemy import text

from src.common.db import get_session


def get_close_price(code: str, trade_date: date) -> Optional[float]:
    """获取指定日期的收盘价。非交易日向前查找。"""
    with get_session() as session:
        row = session.execute(
            text("""
                SELECT close, trade_date FROM stock_daily
                WHERE code = :code AND trade_date <= :dt
                ORDER BY trade_date DESC LIMIT 1
            """),
            {"code": code, "dt": trade_date},
        ).fetchone()
        if row:
            return float(row.close)
        return None


def get_daily_data(code: str, start_date: date, end_date: date) -> List[Dict[str, Any]]:
    """获取区间内的日线数据，按日期升序"""
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT code, trade_date, open, high, low, close, volume, amount,
                       change_pct, turnover_rate, pre_close
                FROM stock_daily
                WHERE code = :code AND trade_date >= :start AND trade_date <= :end
                ORDER BY trade_date ASC
            """),
            {"code": code, "start": start_date, "end": end_date},
        ).fetchall()
        return [
            {
                "code": r.code,
                "trade_date": r.trade_date,
                "open": float(r.open) if r.open else None,
                "high": float(r.high) if r.high else None,
                "low": float(r.low) if r.low else None,
                "close": float(r.close) if r.close else None,
                "volume": int(r.volume) if r.volume else 0,
                "amount": float(r.amount) if r.amount else 0,
                "change_pct": float(r.change_pct) if r.change_pct else 0,
                "pre_close": float(r.pre_close) if r.pre_close else None,
            }
            for r in rows
        ]


def get_stock_name(code: str) -> Optional[str]:
    """查询股票名称"""
    with get_session() as session:
        row = session.execute(
            text("SELECT name FROM stocks WHERE code = :code"),
            {"code": code},
        ).fetchone()
        return row.name if row else None


def get_open_price(code: str, trade_date: date) -> Optional[float]:
    """获取指定日期的开盘价。非交易日向后查找。"""
    with get_session() as session:
        row = session.execute(
            text("""
                SELECT open, trade_date FROM stock_daily
                WHERE code = :code AND trade_date >= :dt
                ORDER BY trade_date ASC LIMIT 1
            """),
            {"code": code, "dt": trade_date},
        ).fetchone()
        if row:
            return float(row.open)
        return None


def get_open_price_exact(code: str, trade_date: date) -> Optional[Dict[str, Any]]:
    """获取精确日期的开盘价和前收盘价（用于判断涨停开盘）"""
    with get_session() as session:
        row = session.execute(
            text("""
                SELECT open, close, pre_close, high, low, change_pct, trade_date
                FROM stock_daily
                WHERE code = :code AND trade_date = :dt
            """),
            {"code": code, "dt": trade_date},
        ).fetchone()
        if row:
            return {
                "open": float(row.open) if row.open else None,
                "close": float(row.close) if row.close else None,
                "pre_close": float(row.pre_close) if row.pre_close else None,
                "high": float(row.high) if row.high else None,
                "low": float(row.low) if row.low else None,
                "change_pct": float(row.change_pct) if row.change_pct else None,
                "trade_date": row.trade_date,
            }
        return None


def get_trading_dates(start_date: date, end_date: date) -> List[date]:
    """获取区间内所有交易日列表"""
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT DISTINCT trade_date FROM stock_daily
                WHERE trade_date >= :start AND trade_date <= :end
                ORDER BY trade_date ASC
            """),
            {"start": start_date, "end": end_date},
        ).fetchall()
        return [r.trade_date for r in rows]


def get_next_trading_date(from_date: date) -> Optional[date]:
    """获取指定日期之后的下一个交易日"""
    with get_session() as session:
        row = session.execute(
            text("""
                SELECT DISTINCT trade_date FROM stock_daily
                WHERE trade_date > :dt
                ORDER BY trade_date ASC LIMIT 1
            """),
            {"dt": from_date},
        ).fetchone()
        return row.trade_date if row else None


def get_data_range(code: str) -> Optional[Dict[str, Any]]:
    """查询某只股票的数据覆盖范围"""
    with get_session() as session:
        row = session.execute(
            text("""
                SELECT MIN(trade_date) as min_date, MAX(trade_date) as max_date,
                       COUNT(*) as total_days
                FROM stock_daily WHERE code = :code
            """),
            {"code": code},
        ).fetchone()
        if row and row.min_date:
            return {
                "min_date": row.min_date,
                "max_date": row.max_date,
                "total_days": row.total_days,
            }
        return None


def get_minute_data(
    code: str, start_time: str, end_time: str, period: str = "5m"
) -> List[Dict[str, Any]]:
    """获取分钟线数据"""
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT code, trade_time, period, open, high, low, close, volume, amount
                FROM stock_minute
                WHERE code = :code AND period = :period
                  AND trade_time >= :start AND trade_time <= :end
                ORDER BY trade_time ASC
            """),
            {"code": code, "period": period, "start": start_time, "end": end_time},
        ).fetchall()
        return [
            {
                "code": r.code,
                "trade_time": r.trade_time,
                "period": r.period,
                "open": float(r.open) if r.open else None,
                "high": float(r.high) if r.high else None,
                "low": float(r.low) if r.low else None,
                "close": float(r.close) if r.close else None,
                "volume": int(r.volume) if r.volume else 0,
                "amount": float(r.amount) if r.amount else 0,
            }
            for r in rows
        ]
