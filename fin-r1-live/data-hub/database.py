"""
Fin-R1 Data Hub - Database Module
PostgreSQL数据库连接与ORM模型

表结构:
- stocks: 股票基础信息
- stock_daily: 日线历史数据
- stock_realtime: 实时数据缓存
- market_index: 大盘指数
- sector_data: 板块数据
- data_sync_log: 同步日志
"""
import os
from datetime import datetime, date
from typing import List, Optional, Dict, Any
from contextlib import contextmanager

from sqlalchemy import (
    create_engine, Column, String, Float, Date, DateTime,
    Integer, BigInteger, Index, text
)
from sqlalchemy.orm import declarative_base, sessionmaker, Session
from sqlalchemy.pool import QueuePool
import logging

logger = logging.getLogger(__name__)

# 数据库配置 - 使用现有的 PostgreSQL 服务器
# 默认连接到 123.60.11.74:5432，数据库名为 finr1_data
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data"
)

# 创建引擎
engine = create_engine(
    DATABASE_URL,
    poolclass=QueuePool,
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


# ============ ORM Models ============

class Stock(Base):
    """股票基础信息表"""
    __tablename__ = "stocks"

    code = Column(String(10), primary_key=True, comment="股票代码")
    name = Column(String(50), nullable=False, comment="股票名称")
    exchange = Column(String(10), comment="交易所: SH/SZ/BJ")
    industry = Column(String(50), comment="所属行业")
    sector = Column(String(50), comment="所属板块")
    list_date = Column(Date, comment="上市日期")

    # 财务指标
    pe_ttm = Column(Float, comment="市盈率TTM")
    pb = Column(Float, comment="市净率")
    roe = Column(Float, comment="净资产收益率")
    market_cap = Column(Float, comment="总市值(亿)")

    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "exchange": self.exchange,
            "industry": self.industry,
            "pe_ttm": self.pe_ttm,
            "pb": self.pb,
            "market_cap": self.market_cap
        }


class StockDaily(Base):
    """股票日线历史数据表"""
    __tablename__ = "stock_daily"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False, comment="股票代码")
    trade_date = Column(Date, nullable=False, comment="交易日期")

    # 价格数据
    open = Column(Float, nullable=False, comment="开盘价")
    high = Column(Float, nullable=False, comment="最高价")
    low = Column(Float, nullable=False, comment="最低价")
    close = Column(Float, nullable=False, comment="收盘价")
    pre_close = Column(Float, comment="昨收价")

    # 成交量数据
    volume = Column(BigInteger, comment="成交量(股)")
    amount = Column(Float, comment="成交额(元)")
    turnover_rate = Column(Float, comment="换手率")

    # 涨跌幅
    change = Column(Float, comment="涨跌额")
    change_pct = Column(Float, comment="涨跌幅%")

    # 技术指标（新增）
    amplitude = Column(Float, comment="振幅%")

    __table_args__ = (
        # 主键约束：防止重复数据
        Index('idx_code_date', 'code', 'trade_date', unique=True),
        # 按日期查询（大盘分析、定时任务）
        Index('idx_trade_date', 'trade_date'),
        # 单独code索引（单只股票历史查询，覆盖索引优化）
        Index('idx_code_only', 'code'),
        # code+date降序索引（查询某只股票最新数据，避免排序）
        Index('idx_code_date_desc', 'code', trade_date.desc()),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "trade_date": self.trade_date.isoformat() if self.trade_date else None,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "amount": self.amount,
            "change": self.change,
            "change_pct": self.change_pct,
            "turnover_rate": self.turnover_rate,
            "amplitude": self.amplitude
        }


class StockRealtime(Base):
    """股票实时行情数据缓存表 - 包含完整实时数据字段"""
    __tablename__ = "stock_realtime"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False, comment="股票代码")
    timestamp = Column(DateTime, nullable=False, comment="数据时间戳")

    # 基础价格数据
    price = Column(Float, comment="当前价格")
    change = Column(Float, comment="涨跌额")
    change_pct = Column(Float, comment="涨跌幅%")
    volume = Column(BigInteger, comment="当日累计成交量(股)")
    amount = Column(Float, comment="当日累计成交额(元)")

    # 扩展实时数据字段（来自akshare stock_zh_a_spot_em）
    amplitude = Column(Float, comment="振幅%")
    turnover_rate = Column(Float, comment="换手率%")
    rise_speed = Column(Float, comment="涨速")
    change_5min = Column(Float, comment="5分钟涨跌%")
    change_60d = Column(Float, comment="60日涨跌幅%")
    change_ytd = Column(Float, comment="年初至今涨跌幅%")

    # 市值数据
    market_cap = Column(Float, comment="总市值(元)")
    float_market_cap = Column(Float, comment="流通市值(元)")

    # 财务指标（实时）
    pe_dynamic = Column(Float, comment="市盈率(动态)")
    pb = Column(Float, comment="市净率")

    __table_args__ = (
        Index('idx_realtime_code_ts', 'code', 'timestamp'),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
            "price": self.price,
            "change": self.change,
            "change_pct": self.change_pct,
            "volume": self.volume,
            "amount": self.amount,
            "amplitude": self.amplitude,
            "turnover_rate": self.turnover_rate,
            "rise_speed": self.rise_speed,
            "change_5min": self.change_5min,
            "change_60d": self.change_60d,
            "change_ytd": self.change_ytd,
            "market_cap": self.market_cap,
            "float_market_cap": self.float_market_cap,
            "pe": self.pe_dynamic,
            "pb": self.pb
        }


class MarketIndex(Base):
    """大盘指数数据表"""
    __tablename__ = "market_index"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    index_code = Column(String(10), nullable=False, comment="指数代码")
    index_name = Column(String(30), comment="指数名称")
    trade_date = Column(Date, nullable=False, comment="交易日期")

    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    change = Column(Float)
    change_pct = Column(Float)
    volume = Column(BigInteger)
    amount = Column(Float)

    __table_args__ = (
        Index('idx_index_code_date', 'index_code', 'trade_date', unique=True),
    )


class SectorData(Base):
    """板块/行业数据表"""
    __tablename__ = "sector_data"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    sector_name = Column(String(50), nullable=False, comment="板块名称")
    trade_date = Column(Date, nullable=False, comment="交易日期")

    change_pct = Column(Float, comment="涨跌幅%")
    net_inflow = Column(Float, comment="资金净流入(亿)")
    leading_stock = Column(String(50), comment="领涨股")

    __table_args__ = (
        Index('idx_sector_date', 'sector_name', 'trade_date', unique=True),
    )


class DataSyncLog(Base):
    """数据同步日志表"""
    __tablename__ = "data_sync_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    sync_type = Column(String(30), nullable=False, comment="同步类型")
    start_time = Column(DateTime, default=datetime.now)
    end_time = Column(DateTime)
    status = Column(String(20), comment="状态: running/success/failed")
    records_count = Column(Integer)
    message = Column(String(500))


class StockDownloadProgress(Base):
    """股票下载进度表 - 用于断点续传"""
    __tablename__ = "stock_download_progress"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False, comment="股票代码")
    sync_type = Column(String(20), nullable=False, comment="同步类型: history_full/history_inc/fundamental")

    # 下载进度
    status = Column(String(20), default="pending", comment="状态: pending/running/success/failed")
    start_date = Column(Date, comment="计划开始日期")
    end_date = Column(Date, comment="计划结束日期")
    actual_start_date = Column(Date, comment="实际最早数据日期")
    actual_end_date = Column(Date, comment="实际最晚数据日期")
    records_count = Column(Integer, default=0, comment="已下载记录数")
    expected_count = Column(Integer, comment="预期记录数")

    # 重试机制
    retry_count = Column(Integer, default=0, comment="重试次数")
    max_retries = Column(Integer, default=3, comment="最大重试次数")

    # 时间戳
    created_at = Column(DateTime, default=datetime.now, comment="创建时间")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, comment="更新时间")
    completed_at = Column(DateTime, comment="完成时间")

    # 错误信息
    error_message = Column(String(500), comment="错误信息")

    __table_args__ = (
        Index('idx_progress_code_type', 'code', 'sync_type', unique=True),
        Index('idx_progress_status', 'status'),
    )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            'id': self.id,
            'code': self.code,
            'sync_type': self.sync_type,
            'status': self.status,
            'date_range': {
                'start': self.start_date.isoformat() if self.start_date else None,
                'end': self.end_date.isoformat() if self.end_date else None,
                'actual_start': self.actual_start_date.isoformat() if self.actual_start_date else None,
                'actual_end': self.actual_end_date.isoformat() if self.actual_end_date else None,
            },
            'records': {
                'downloaded': self.records_count,
                'expected': self.expected_count,
                'progress': round(self.records_count / self.expected_count * 100, 2) if self.expected_count else 0
            },
            'retry': {
                'count': self.retry_count,
                'max': self.max_retries
            },
            'timestamps': {
                'created': self.created_at.isoformat() if self.created_at else None,
                'updated': self.updated_at.isoformat() if self.updated_at else None,
                'completed': self.completed_at.isoformat() if self.completed_at else None
            },
            'error': self.error_message
        }


# ============ 财务报表相关表 ============

class StockFinancialReport(Base):
    """财务报表数据表 - 三大报表"""
    __tablename__ = "stock_financial_report"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False, comment="股票代码")
    report_type = Column(String(20), nullable=False, comment="报表类型: balance_sheet/income_statement/cash_flow")
    report_period = Column(String(20), nullable=False, comment="报告期: 年报/半年报/季报")
    report_date = Column(Date, nullable=False, comment="报告日期")

    # 资产负债表关键指标
    total_assets = Column(Float, comment="总资产(元)")
    total_liabilities = Column(Float, comment="总负债(元)")
    total_equity = Column(Float, comment="股东权益(元)")
    current_assets = Column(Float, comment="流动资产(元)")
    current_liabilities = Column(Float, comment="流动负债(元)")
    inventory = Column(Float, comment="存货(元)")
    accounts_receivable = Column(Float, comment="应收账款(元)")
    cash_and_equivalents = Column(Float, comment="货币资金(元)")
    fixed_assets = Column(Float, comment="固定资产(元)")

    # 利润表关键指标
    total_revenue = Column(Float, comment="营业收入(元)")
    operating_profit = Column(Float, comment="营业利润(元)")
    net_profit = Column(Float, comment="净利润(元)")
    gross_profit = Column(Float, comment="毛利润(元)")
    operating_cost = Column(Float, comment="营业成本(元)")
    selling_expenses = Column(Float, comment="销售费用(元)")
    admin_expenses = Column(Float, comment="管理费用(元)")
    financial_expenses = Column(Float, comment="财务费用(元)")
    rd_expenses = Column(Float, comment="研发费用(元)")

    # 现金流量表关键指标
    net_cash_flow = Column(Float, comment="净现金流(元)")
    operating_cash_flow = Column(Float, comment="经营活动现金流(元)")
    investing_cash_flow = Column(Float, comment="投资活动现金流(元)")
    financing_cash_flow = Column(Float, comment="筹资活动现金流(元)")

    # 财务比率(计算得出)
    gross_margin = Column(Float, comment="毛利率%")
    net_margin = Column(Float, comment="净利率%")
    roe = Column(Float, comment="净资产收益率ROE%")
    roa = Column(Float, comment="总资产收益率ROA%")
    debt_ratio = Column(Float, comment="资产负债率%")
    current_ratio = Column(Float, comment="流动比率")
    quick_ratio = Column(Float, comment="速动比率")

    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index('idx_financial_code_date', 'code', 'report_date'),
        Index('idx_financial_type_period', 'report_type', 'report_period'),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "report_type": self.report_type,
            "report_period": self.report_period,
            "report_date": self.report_date.isoformat() if self.report_date else None,
            "balance_sheet": {
                "total_assets": self.total_assets,
                "total_liabilities": self.total_liabilities,
                "total_equity": self.total_equity,
                "current_assets": self.current_assets,
                "current_liabilities": self.current_liabilities,
                "inventory": self.inventory,
                "accounts_receivable": self.accounts_receivable,
                "cash_and_equivalents": self.cash_and_equivalents,
                "fixed_assets": self.fixed_assets
            },
            "income_statement": {
                "total_revenue": self.total_revenue,
                "operating_profit": self.operating_profit,
                "net_profit": self.net_profit,
                "gross_profit": self.gross_profit,
                "operating_cost": self.operating_cost,
                "selling_expenses": self.selling_expenses,
                "admin_expenses": self.admin_expenses,
                "financial_expenses": self.financial_expenses,
                "rd_expenses": self.rd_expenses
            },
            "cash_flow": {
                "net_cash_flow": self.net_cash_flow,
                "operating_cash_flow": self.operating_cash_flow,
                "investing_cash_flow": self.investing_cash_flow,
                "financing_cash_flow": self.financing_cash_flow
            },
            "financial_ratios": {
                "gross_margin": self.gross_margin,
                "net_margin": self.net_margin,
                "roe": self.roe,
                "roa": self.roa,
                "debt_ratio": self.debt_ratio,
                "current_ratio": self.current_ratio,
                "quick_ratio": self.quick_ratio
            }
        }


class StockFinancialIndicator(Base):
    """财务分析指标表 - 主要财务指标"""
    __tablename__ = "stock_financial_indicator"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False, comment="股票代码")
    report_date = Column(Date, nullable=False, comment="报告日期")

    # 每股指标
    eps_basic = Column(Float, comment="基本每股收益(元)")
    eps_diluted = Column(Float, comment="稀释每股收益(元)")
    bps = Column(Float, comment="每股净资产(元)")
    dps = Column(Float, comment="每股股息(元)")
    cfps = Column(Float, comment="每股现金流(元)")

    # 盈利能力
    roe_weighted = Column(Float, comment="加权净资产收益率%")
    roe_diluted = Column(Float, comment="摊薄净资产收益率%")
    roa = Column(Float, comment="总资产报酬率%")
    net_profit_margin = Column(Float, comment="销售净利率%")
    gross_profit_margin = Column(Float, comment="销售毛利率%")
    core_profit_margin = Column(Float, comment="主营业务利润率%")

    # 运营效率
    total_asset_turnover = Column(Float, comment="总资产周转率(次)")
    inventory_turnover = Column(Float, comment="存货周转率(次)")
    receivable_turnover = Column(Float, comment="应收账款周转率(次)")
    inventory_turnover_days = Column(Float, comment="存货周转天数(天)")
    receivable_turnover_days = Column(Float, comment="应收账款周转天数(天)")

    # 偿债能力
    debt_asset_ratio = Column(Float, comment="资产负债率%")
    equity_ratio = Column(Float, comment="股东权益比率%")
    current_ratio = Column(Float, comment="流动比率")
    quick_ratio = Column(Float, comment="速动比率")
    cash_ratio = Column(Float, comment="现金比率")
    interest_coverage = Column(Float, comment="利息保障倍数")

    # 成长能力
    revenue_growth = Column(Float, comment="营业收入增长率%")
    profit_growth = Column(Float, comment="净利润增长率%")
    asset_growth = Column(Float, comment="总资产增长率%")
    equity_growth = Column(Float, comment="净资产增长率%")

    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index('idx_indicator_code_date', 'code', 'report_date', unique=True),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "report_date": self.report_date.isoformat() if self.report_date else None,
            "per_share": {
                "eps_basic": self.eps_basic,
                "eps_diluted": self.eps_diluted,
                "bps": self.bps,
                "dps": self.dps,
                "cfps": self.cfps
            },
            "profitability": {
                "roe_weighted": self.roe_weighted,
                "roe_diluted": self.roe_diluted,
                "roa": self.roa,
                "net_profit_margin": self.net_profit_margin,
                "gross_profit_margin": self.gross_profit_margin,
                "core_profit_margin": self.core_profit_margin
            },
            "efficiency": {
                "total_asset_turnover": self.total_asset_turnover,
                "inventory_turnover": self.inventory_turnover,
                "receivable_turnover": self.receivable_turnover,
                "inventory_turnover_days": self.inventory_turnover_days,
                "receivable_turnover_days": self.receivable_turnover_days
            },
            "solvency": {
                "debt_asset_ratio": self.debt_asset_ratio,
                "equity_ratio": self.equity_ratio,
                "current_ratio": self.current_ratio,
                "quick_ratio": self.quick_ratio,
                "cash_ratio": self.cash_ratio,
                "interest_coverage": self.interest_coverage
            },
            "growth": {
                "revenue_growth": self.revenue_growth,
                "profit_growth": self.profit_growth,
                "asset_growth": self.asset_growth,
                "equity_growth": self.equity_growth
            }
        }


# ============ 工具函数 ============

def init_database():
    """初始化数据库，创建所有表"""
    Base.metadata.create_all(bind=engine)
    logger.info("数据库表初始化完成")


@contextmanager
def get_db_session() -> Session:
    """获取数据库会话的上下文管理器"""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception as e:
        session.rollback()
        raise e
    finally:
        session.close()


# ============ DAO Classes ============

class StockDAO:
    """股票数据访问对象"""

    @staticmethod
    def bulk_upsert_stocks(session: Session, stocks_data: List[Dict]):
        """批量插入或更新股票基础信息"""
        for data in stocks_data:
            stock = session.query(Stock).filter_by(code=data['code']).first()
            if stock:
                for key, value in data.items():
                    if hasattr(stock, key):
                        setattr(stock, key, value)
            else:
                session.add(Stock(**data))

    @staticmethod
    def get_stock_by_code(session: Session, code: str) -> Optional[Stock]:
        return session.query(Stock).filter_by(code=code).first()

    @staticmethod
    def search_stocks_by_name(session: Session, keyword: str, limit: int = 20) -> List[Stock]:
        return session.query(Stock).filter(
            Stock.name.ilike(f"%{keyword}%")
        ).limit(limit).all()

    @staticmethod
    def get_all_stock_codes(session: Session) -> List[str]:
        """获取所有股票代码，按代码排序"""
        return [row[0] for row in session.query(Stock.code).order_by(Stock.code).all()]


class StockDailyDAO:
    """日线数据访问对象"""

    @staticmethod
    def bulk_insert_daily_data(session: Session, data_list: List[Dict], batch_size: int = 1000) -> int:
        """批量插入日线数据（使用UPSERT）"""
        from sqlalchemy.dialects.postgresql import insert

        if not data_list:
            return 0

        count = 0
        for i in range(0, len(data_list), batch_size):
            batch = data_list[i:i + batch_size]
            stmt = insert(StockDaily).values(batch)

            update_dict = {
                c.name: c for c in stmt.excluded
                if c.name not in ['id', 'code', 'trade_date']
            }

            upsert_stmt = stmt.on_conflict_do_update(
                index_elements=['code', 'trade_date'],
                set_=update_dict
            )

            session.execute(upsert_stmt)
            count += len(batch)

        return count

    @staticmethod
    def get_stock_history(
        session: Session,
        code: str,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        limit: int = 100
    ) -> List[StockDaily]:
        """获取股票历史数据"""
        query = session.query(StockDaily).filter_by(code=code)

        if start_date:
            query = query.filter(StockDaily.trade_date >= start_date)
        if end_date:
            query = query.filter(StockDaily.trade_date <= end_date)

        return query.order_by(StockDaily.trade_date.desc()).limit(limit).all()

    @staticmethod
    def get_latest_trade_date(session: Session, code: Optional[str] = None) -> Optional[date]:
        """获取最新的交易日期"""
        query = session.query(StockDaily.trade_date)
        if code:
            query = query.filter_by(code=code)
        result = query.order_by(StockDaily.trade_date.desc()).first()
        return result[0] if result else None

    @staticmethod
    def get_date_range_statistics(session: Session, code: str, days: int = 30) -> Dict[str, Any]:
        """获取股票统计信息"""
        end_date = StockDailyDAO.get_latest_trade_date(session, code)
        if not end_date:
            return {}

        from datetime import timedelta
        start_date = end_date - timedelta(days=days)
        rows = StockDailyDAO.get_stock_history(session, code, start_date, end_date, limit=days)

        if not rows:
            return {}

        closes = [r.close for r in rows]
        changes = [r.change_pct for r in rows if r.change_pct is not None]
        volumes = [r.volume for r in rows if r.volume is not None]

        return {
            "code": code,
            "period": f"{rows[-1].trade_date} to {rows[0].trade_date}",
            "days": len(rows),
            "current_price": closes[0],
            "period_high": max([r.high for r in rows]),
            "period_low": min([r.low for r in rows]),
            "avg_price": sum(closes) / len(closes) if closes else 0,
            "total_volume": sum(volumes) if volumes else 0,
            "avg_change_pct": sum(changes) / len(changes) if changes else 0,
            "max_change_pct": max(changes) if changes else 0,
            "min_change_pct": min(changes) if changes else 0,
            "up_days": len([c for c in changes if c > 0]),
            "down_days": len([c for c in changes if c < 0])
        }


class StockDownloadProgressDAO:
    """股票下载进度DAO - 支持断点续传"""

    @staticmethod
    def init_progress(session: Session, code: str, sync_type: str,
                      start_date: date, end_date: date, expected_count: int = 250):
        """初始化股票下载进度记录"""
        from sqlalchemy.dialects.postgresql import insert

        stmt = insert(StockDownloadProgress).values(
            code=code,
            sync_type=sync_type,
            status='pending',
            start_date=start_date,
            end_date=end_date,
            expected_count=expected_count,
            retry_count=0,
            created_at=datetime.now(),
            updated_at=datetime.now()
        ).on_conflict_do_update(
            index_elements=['code', 'sync_type'],
            set_={
                'status': 'pending',
                'start_date': start_date,
                'end_date': end_date,
                'expected_count': expected_count,
                'retry_count': StockDownloadProgress.retry_count + 1,
                'updated_at': datetime.now(),
                'error_message': None
            }
        )
        session.execute(stmt)

    @staticmethod
    def update_progress(session: Session, code: str, sync_type: str,
                       records_count: int, actual_start: Optional[date] = None,
                       actual_end: Optional[date] = None, status: str = 'running'):
        """更新下载进度"""
        progress = session.query(StockDownloadProgress).filter_by(
            code=code, sync_type=sync_type
        ).first()

        if progress:
            progress.status = status
            progress.records_count = records_count
            if actual_start:
                progress.actual_start_date = actual_start
            if actual_end:
                progress.actual_end_date = actual_end
            progress.updated_at = datetime.now()

            if status == 'success':
                progress.completed_at = datetime.now()

            session.commit()

    @staticmethod
    def mark_failed(session: Session, code: str, sync_type: str, error_message: str):
        """标记下载失败"""
        progress = session.query(StockDownloadProgress).filter_by(
            code=code, sync_type=sync_type
        ).first()

        if progress:
            progress.status = 'failed'
            progress.error_message = error_message[:500]
            progress.retry_count += 1
            progress.updated_at = datetime.now()
            session.commit()

    @staticmethod
    def get_progress(session: Session, code: str, sync_type: str) -> Optional[StockDownloadProgress]:
        """获取单个股票的下载进度"""
        return session.query(StockDownloadProgress).filter_by(
            code=code, sync_type=sync_type
        ).first()

    @staticmethod
    def get_incomplete_stocks(session: Session, sync_type: str) -> List[StockDownloadProgress]:
        """获取未完成的股票列表（用于断点续传）"""
        return session.query(StockDownloadProgress).filter(
            StockDownloadProgress.sync_type == sync_type,
            StockDownloadProgress.status.in_(['pending', 'running', 'failed']),
            StockDownloadProgress.retry_count < StockDownloadProgress.max_retries
        ).order_by(StockDownloadProgress.code).all()

    @staticmethod
    def get_failed_stocks(session: Session, sync_type: str) -> List[StockDownloadProgress]:
        """获取下载失败的股票列表"""
        return session.query(StockDownloadProgress).filter_by(
            sync_type=sync_type,
            status='failed'
        ).order_by(StockDownloadProgress.code).all()

    @staticmethod
    def get_download_summary(session: Session, sync_type: str) -> Dict[str, Any]:
        """获取下载进度汇总统计"""
        from sqlalchemy import func

        total = session.query(func.count(StockDownloadProgress.id)).filter(
            StockDownloadProgress.sync_type == sync_type
        ).scalar()

        pending = session.query(func.count(StockDownloadProgress.id)).filter(
            StockDownloadProgress.sync_type == sync_type,
            StockDownloadProgress.status == 'pending'
        ).scalar()

        running = session.query(func.count(StockDownloadProgress.id)).filter(
            StockDownloadProgress.sync_type == sync_type,
            StockDownloadProgress.status == 'running'
        ).scalar()

        success = session.query(func.count(StockDownloadProgress.id)).filter(
            StockDownloadProgress.sync_type == sync_type,
            StockDownloadProgress.status == 'success'
        ).scalar()

        failed = session.query(func.count(StockDownloadProgress.id)).filter(
            StockDownloadProgress.sync_type == sync_type,
            StockDownloadProgress.status == 'failed'
        ).scalar()

        total_records = session.query(func.sum(StockDownloadProgress.records_count)).filter(
            StockDownloadProgress.sync_type == sync_type
        ).scalar() or 0

        return {
            'total': total,
            'pending': pending,
            'running': running,
            'success': success,
            'failed': failed,
            'completion_rate': round(success / total * 100, 2) if total > 0 else 0,
            'total_records': total_records
        }

    @staticmethod
    def reset_failed_progress(session: Session, sync_type: str) -> int:
        """重置失败的任务（用于重试）"""
        failed_stocks = StockDownloadProgressDAO.get_failed_stocks(session, sync_type)
        count = 0

        for progress in failed_stocks:
            if progress.retry_count < progress.max_retries:
                progress.status = 'pending'
                progress.error_message = None
                progress.updated_at = datetime.now()
                count += 1

        session.commit()
        return count

    @staticmethod
    def clear_progress(session: Session, sync_type: str):
        """清除指定类型的所有进度记录"""
        session.query(StockDownloadProgress).filter_by(
            sync_type=sync_type
        ).delete()
        session.commit()
