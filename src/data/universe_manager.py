"""股票全域管理器 — 幸存者偏差 / Point-in-Time (PIT) 数据

核心功能:
- PIT 查询: "T 日哪些股票是可交易的?" 而非 "今天的列表回溯过去"
- SCD Type 2: 记录每只股票的生命周期变更
- 同步来源: akshare / xtquant

避免幸存者偏差的关键:
- 只用当前存活股票回测 → 年化收益虚高 1.5-4.5%
- 遗漏退市股 (暴跌 80%+) → Sharpe 虚高 20-30%
"""
from datetime import date, datetime

import pandas as pd
from sqlalchemy import Column, String, Date, DateTime, BigInteger, Index, text

from src.common.db import Base, get_session
from src.common.logger import get_logger

logger = get_logger(__name__)


class StockUniverse(Base):
    """股票全域表 — SCD Type 2 缓慢变化维度"""
    __tablename__ = "stock_universe"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False, comment="股票代码")
    name = Column(String(50), comment="股票名称")
    exchange = Column(String(10), comment="交易所: SH/SZ/BJ")
    board = Column(String(20), comment="板块: main/star/chinext/bse")
    start_date = Column(Date, nullable=False, comment="上市日期 / 本条记录生效日期")
    end_date = Column(Date, comment="退市日期 / 本条记录失效日期, NULL=存续中")
    status = Column(String(20), default="active",
                    comment="active/suspended/delisted/st")
    status_reason = Column(String(200), comment="状态变更原因")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("idx_universe_code", "code"),
        Index("idx_universe_dates", "start_date", "end_date"),
        Index("idx_universe_status", "status"),
    )


class UniverseManager:
    """股票全域管理器"""

    def get_tradable(
        self,
        trade_date: date,
        exclude_st: bool = True,
        exclude_suspended: bool = True,
    ) -> list[str]:
        """PIT 查询: 返回指定日期可交易的股票代码列表

        Args:
            trade_date: 查询日期
            exclude_st: 排除 ST 股票
            exclude_suspended: 排除停牌股票
        """
        excluded_statuses = ["delisted"]
        if exclude_st:
            excluded_statuses.append("st")
        if exclude_suspended:
            excluded_statuses.append("suspended")

        with get_session() as session:
            sql = text("""
                SELECT DISTINCT code FROM stock_universe
                WHERE start_date <= :td
                  AND (end_date IS NULL OR end_date >= :td)
                  AND status NOT IN :excluded
                ORDER BY code
            """)
            rows = session.execute(sql, {
                "td": trade_date,
                "excluded": tuple(excluded_statuses),
            }).fetchall()

        codes = [r[0] for r in rows]
        logger.debug(f"[Universe] {trade_date}: {len(codes)} 只可交易标的")
        return codes

    def get_tradable_between(
        self,
        start_date: date,
        end_date: date,
    ) -> pd.DataFrame:
        """批量 PIT 查询: 返回日期范围内每日可交易标的

        Returns:
            DataFrame(trade_date, code) — 笛卡尔积中存续的部分
        """
        with get_session() as session:
            sql = text("""
                SELECT u.code, td.trade_date
                FROM stock_universe u
                CROSS JOIN (
                    SELECT DISTINCT trade_date FROM stock_daily
                    WHERE trade_date BETWEEN :start AND :end
                ) td
                WHERE u.start_date <= td.trade_date
                  AND (u.end_date IS NULL OR u.end_date >= td.trade_date)
                  AND u.status NOT IN ('delisted', 'suspended')
                ORDER BY td.trade_date, u.code
            """)
            rows = session.execute(sql, {
                "start": start_date, "end": end_date,
            }).fetchall()

        return pd.DataFrame(rows, columns=["code", "trade_date"])

    def sync_from_stocks_table(self) -> int:
        """从已有 stocks 表同步到 stock_universe (首次初始化)

        将 stocks 表中每只股票视为一条 SCD Type 2 记录。
        """
        with get_session() as session:
            sql = text("""
                INSERT INTO stock_universe (code, name, exchange, start_date, status)
                SELECT s.code, s.name, s.exchange,
                       COALESCE(s.list_date, '2000-01-01'),
                       'active'
                FROM stocks s
                WHERE NOT EXISTS (
                    SELECT 1 FROM stock_universe u WHERE u.code = s.code
                )
            """)
            result = session.execute(sql)
            count = result.rowcount

        logger.info(f"[Universe] 从 stocks 表同步 {count} 条记录")
        return count

    def mark_delisted(self, code: str, delist_date: date, reason: str = "") -> None:
        """标记股票退市"""
        with get_session() as session:
            sql = text("""
                UPDATE stock_universe
                SET end_date = :delist_date, status = 'delisted',
                    status_reason = :reason, updated_at = NOW()
                WHERE code = :code AND end_date IS NULL
            """)
            session.execute(sql, {
                "code": code, "delist_date": delist_date, "reason": reason,
            })
        logger.info(f"[Universe] {code} 标记退市 @ {delist_date}: {reason}")

    def mark_st(self, code: str, effective_date: date, reason: str = "") -> None:
        """标记 ST 状态"""
        with get_session() as session:
            sql = text("""
                UPDATE stock_universe
                SET status = 'st', status_reason = :reason, updated_at = NOW()
                WHERE code = :code AND end_date IS NULL
            """)
            session.execute(sql, {
                "code": code, "reason": reason,
            })
        logger.info(f"[Universe] {code} 标记 ST @ {effective_date}: {reason}")
