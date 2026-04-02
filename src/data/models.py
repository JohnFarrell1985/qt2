"""数据库 ORM 模型"""
from datetime import datetime
from typing import Dict, Any

from sqlalchemy import (
    Column, String, Float, Date, DateTime, Integer, BigInteger,
    Text, Index, UniqueConstraint, Boolean,
)

from src.common.db import Base


# ============ 行情数据 ============

class Stock(Base):
    """股票基础信息表"""
    __tablename__ = "stocks"

    code = Column(String(10), primary_key=True, comment="股票代码")
    name = Column(String(50), nullable=False, comment="股票名称")
    exchange = Column(String(10), comment="交易所: SH/SZ/BJ")
    industry = Column(String(50), comment="所属行业")
    sector = Column(String(50), comment="所属板块")
    list_date = Column(Date, comment="上市日期")
    pe_ttm = Column(Float, comment="市盈率TTM")
    pb = Column(Float, comment="市净率")
    roe = Column(Float, comment="净资产收益率")
    market_cap = Column(Float, comment="总市值(亿)")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code, "name": self.name,
            "exchange": self.exchange, "industry": self.industry,
            "pe_ttm": self.pe_ttm, "pb": self.pb,
            "market_cap": self.market_cap,
        }


class StockDaily(Base):
    """股票日线历史数据表"""
    __tablename__ = "stock_daily"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False, comment="股票代码")
    trade_date = Column(Date, nullable=False, comment="交易日期")
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    pre_close = Column(Float)
    volume = Column(BigInteger, comment="成交量(股)")
    amount = Column(Float, comment="成交额(元)")
    turnover_rate = Column(Float, comment="换手率")
    change = Column(Float, comment="涨跌额")
    change_pct = Column(Float, comment="涨跌幅%")
    amplitude = Column(Float, comment="振幅%")

    __table_args__ = (
        Index("idx_daily_code_date", "code", "trade_date", unique=True),
        Index("idx_daily_trade_date", "trade_date"),
        Index("idx_daily_code", "code"),
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "trade_date": self.trade_date.isoformat() if self.trade_date else None,
            "open": self.open, "high": self.high,
            "low": self.low, "close": self.close,
            "volume": self.volume, "amount": self.amount,
            "change_pct": self.change_pct,
            "turnover_rate": self.turnover_rate,
        }


class StockMinute(Base):
    """分钟线行情表"""
    __tablename__ = "stock_minute"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False)
    trade_time = Column(DateTime, nullable=False)
    period = Column(String(5), nullable=False, comment="1m/5m/15m/30m/60m")
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(BigInteger)
    amount = Column(Float)

    __table_args__ = (
        Index("idx_minute_code_time", "code", "trade_time"),
        UniqueConstraint("code", "trade_time", "period", name="uq_minute"),
    )


class MarketIndex(Base):
    """大盘指数数据表"""
    __tablename__ = "market_index"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    index_code = Column(String(10), nullable=False)
    index_name = Column(String(30))
    trade_date = Column(Date, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    change_pct = Column(Float)
    volume = Column(BigInteger)
    amount = Column(Float)

    __table_args__ = (
        Index("idx_index_code_date", "index_code", "trade_date", unique=True),
    )


# ============ 日历与板块 ============

class TradingDate(Base):
    """交易日历表"""
    __tablename__ = "trading_date"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    market = Column(String(10), nullable=False, comment="市场: SH/SZ")
    trade_date = Column(Date, nullable=False, comment="交易日期")
    is_holiday = Column(Boolean, default=False, comment="是否节假日")

    __table_args__ = (
        UniqueConstraint("market", "trade_date", name="uq_trading_date"),
        Index("idx_td_date", "trade_date"),
    )


class SectorStock(Base):
    """板块成分股关系表"""
    __tablename__ = "sector_stock"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    sector_name = Column(String(100), nullable=False, comment="板块名称")
    stock_code = Column(String(20), nullable=False, comment="QMT格式代码如000001.SZ")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint("sector_name", "stock_code", name="uq_sector_stock"),
        Index("idx_ss_sector", "sector_name"),
        Index("idx_ss_stock", "stock_code"),
    )


class IndexWeight(Base):
    """指数成分权重表"""
    __tablename__ = "index_weight"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    index_code = Column(String(20), nullable=False, comment="指数代码如000300.SH")
    stock_code = Column(String(20), nullable=False, comment="成分股代码")
    weight = Column(Float, comment="权重(%)")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint("index_code", "stock_code", name="uq_index_weight"),
        Index("idx_iw_index", "index_code"),
    )


# ============ 因子数据 ============

class FactorMeta(Base):
    """因子元信息表"""
    __tablename__ = "factor_meta"

    factor_id = Column(Integer, primary_key=True, autoincrement=True)
    factor_name = Column(String(100), nullable=False, unique=True)
    category = Column(String(50), comment="因子分类")
    description = Column(Text)
    data_source = Column(String(50), comment="qmt/calculated")
    qmt_field = Column(String(200), comment="QMT字段映射")
    created_at = Column(DateTime, default=datetime.now)


class FactorValue(Base):
    """因子值时序数据"""
    __tablename__ = "factor_values"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False)
    code = Column(String(10), nullable=False)
    factor_id = Column(Integer, nullable=False)
    value = Column(Float)

    __table_args__ = (
        UniqueConstraint("trade_date", "code", "factor_id", name="uq_factor_value"),
        Index("idx_fv_date_code", "trade_date", "code"),
        Index("idx_fv_factor", "factor_id", "trade_date"),
    )


# ============ 财务数据 ============

class StockFinancialReport(Base):
    """财务报表数据表"""
    __tablename__ = "stock_financial_report"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False)
    report_type = Column(String(20), nullable=False)
    report_period = Column(String(20), nullable=False)
    report_date = Column(Date, nullable=False)
    total_assets = Column(Float)
    total_liabilities = Column(Float)
    total_equity = Column(Float)
    total_revenue = Column(Float)
    operating_profit = Column(Float)
    net_profit = Column(Float)
    gross_profit = Column(Float)
    net_cash_flow = Column(Float)
    operating_cash_flow = Column(Float)
    gross_margin = Column(Float)
    net_margin = Column(Float)
    roe = Column(Float)
    roa = Column(Float)
    debt_ratio = Column(Float)
    current_ratio = Column(Float)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("idx_fin_code_date", "code", "report_date"),
    )


class StockFinancialIndicator(Base):
    """财务分析指标表"""
    __tablename__ = "stock_financial_indicator"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False)
    report_date = Column(Date, nullable=False)
    eps_basic = Column(Float)
    bps = Column(Float)
    roe_weighted = Column(Float)
    net_profit_margin = Column(Float)
    gross_profit_margin = Column(Float)
    debt_asset_ratio = Column(Float)
    current_ratio = Column(Float)
    revenue_growth = Column(Float)
    profit_growth = Column(Float)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("idx_indicator_code_date", "code", "report_date", unique=True),
    )


# ============ ML 模型 ============

class MLModelLog(Base):
    """ML模型训练记录"""
    __tablename__ = "ml_model_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    model_name = Column(String(100), nullable=False)
    train_start = Column(Date)
    train_end = Column(Date)
    n_features = Column(Integer)
    n_samples = Column(Integer)
    ic_mean = Column(Float, comment="IC均值")
    icir = Column(Float, comment="信息比率")
    mse = Column(Float)
    model_path = Column(String(500))
    params_json = Column(Text)
    created_at = Column(DateTime, default=datetime.now)


class MLPrediction(Base):
    """模型预测结果"""
    __tablename__ = "ml_prediction"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    model_id = Column(BigInteger)
    trade_date = Column(Date, nullable=False)
    code = Column(String(10), nullable=False)
    predicted_return = Column(Float)
    rank_score = Column(Integer)
    signal = Column(String(10), comment="buy/sell/hold")
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_pred_date_code", "trade_date", "code"),
    )


# ============ 交易记录 ============

class TradeOrder(Base):
    """交易委托记录"""
    __tablename__ = "trade_order"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    order_id = Column(String(50))
    account_type = Column(String(20), comment="paper/live")
    code = Column(String(10), nullable=False)
    direction = Column(String(10), comment="buy/sell")
    quantity = Column(Integer)
    price = Column(Float)
    price_type = Column(String(20))
    status = Column(String(20), comment="pending/filled/cancelled/failed")
    filled_quantity = Column(Integer, default=0)
    filled_price = Column(Float)
    fees = Column(Float, default=0)
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class TradePosition(Base):
    """持仓快照"""
    __tablename__ = "trade_position"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    snapshot_date = Column(Date, nullable=False)
    account_type = Column(String(20))
    code = Column(String(10), nullable=False)
    quantity = Column(Integer)
    cost_price = Column(Float)
    market_price = Column(Float)
    market_value = Column(Float)
    profit = Column(Float)
    profit_pct = Column(Float)
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_pos_date", "snapshot_date", "account_type"),
    )


class TradeDailyReport(Base):
    """每日绩效报告"""
    __tablename__ = "trade_daily_report"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    report_date = Column(Date, nullable=False)
    account_type = Column(String(20))
    total_assets = Column(Float)
    cash = Column(Float)
    market_value = Column(Float)
    daily_return = Column(Float)
    cumulative_return = Column(Float)
    max_drawdown = Column(Float)
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_report_date", "report_date", "account_type", unique=True),
    )


class DataSyncLog(Base):
    """数据同步日志表"""
    __tablename__ = "data_sync_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    sync_type = Column(String(30), nullable=False)
    start_time = Column(DateTime, default=datetime.now)
    end_time = Column(DateTime)
    status = Column(String(20))
    records_count = Column(Integer)
    message = Column(String(500))


# ============ 策略池 / 标的池 / 宏观环境 ============

class Strategy(Base):
    """策略定义表"""
    __tablename__ = "strategy"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    strategy_name = Column(String(100), nullable=False, unique=True)
    description = Column(Text)
    factor_names_json = Column(Text, comment="因子列表 JSON")
    factor_weights_json = Column(Text, comment="因子权重 JSON")
    model_params_json = Column(Text, comment="LGB模型参数 JSON")
    model_path = Column(String(500), comment="训练好的模型文件路径")
    backtest_sharpe = Column(Float)
    backtest_annual_return = Column(Float)
    backtest_max_drawdown = Column(Float)
    ic_mean = Column(Float)
    icir = Column(Float)
    status = Column(String(20), default="active", comment="active/paused/archived")
    applicable_macro = Column(String(200), comment="适用宏观环境key, 逗号分隔")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class InstrumentPool(Base):
    """标的池表"""
    __tablename__ = "instrument_pool"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    pool_name = Column(String(100), nullable=False, unique=True)
    description = Column(Text)
    codes_json = Column(Text, comment="股票代码列表 JSON")
    filter_rules_json = Column(Text, comment="筛选规则 JSON")
    n_stocks = Column(Integer, default=0)
    status = Column(String(20), default="active")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class StrategyAllocation(Base):
    """策略-标的池-宏观环境 关联表"""
    __tablename__ = "strategy_allocation"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    strategy_id = Column(BigInteger, nullable=False)
    pool_id = Column(BigInteger, nullable=False)
    macro_state = Column(String(50), comment="宏观环境状态key")
    weight = Column(Float, default=1.0, comment="该策略的资金权重")
    is_active = Column(String(5), default="true")
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_alloc_strategy", "strategy_id"),
        Index("idx_alloc_pool", "pool_id"),
        Index("idx_alloc_macro", "macro_state"),
    )


class MacroStateLog(Base):
    """宏观环境状态变更日志"""
    __tablename__ = "macro_state_log"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    state_key = Column(String(50), nullable=False, comment="当前宏观状态key")
    state_detail_json = Column(Text, comment="状态详细指标 JSON")
    determined_by = Column(String(100), comment="判定方法/来源")
    effective_date = Column(Date, nullable=False)
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_macro_date", "effective_date"),
    )
