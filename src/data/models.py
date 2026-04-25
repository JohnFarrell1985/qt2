"""数据库 ORM 模型"""
from __future__ import annotations

from datetime import datetime
from typing import Dict, Any

from sqlalchemy import (
    JSON, Column, String, Float, Date, DateTime, Integer, BigInteger,
    Text, Index, UniqueConstraint, Boolean, func,
)
from sqlalchemy.dialects.postgresql import JSONB

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
    change = Column(Float, comment="涨跌额")
    change_pct = Column(Float, comment="涨跌幅%")
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


# ============ 可转债 ============

class ConvertibleBond(Base):
    """可转债基础信息表 — 字段对齐 xtdata.get_cb_info()"""
    __tablename__ = "convertible_bond"

    code = Column(String(20), primary_key=True, comment="可转债代码如 123001.SZ")
    bond_name = Column(String(100), comment="转债简称")
    stock_code = Column(String(20), comment="正股代码")
    convert_price = Column(Float, comment="最新转股价")
    convert_start_date = Column(String(20), comment="转股起始日 YYYYMMDD")
    convert_end_date = Column(String(20), comment="转股截止日")
    maturity_date = Column(String(20), comment="到期日")
    issue_amount = Column(Float, comment="发行规模(亿)")
    remain_amount = Column(Float, comment="剩余规模(亿)")
    level = Column(String(20), comment="信用评级")
    analConvpremiumratio = Column(Float, comment="转股溢价率(%)")
    pure_bond_value = Column(Float, comment="纯债价值")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        Index("idx_cb_stock", "stock_code"),
    )


class CBDaily(Base):
    """可转债日线行情表"""
    __tablename__ = "cb_daily"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(20), nullable=False, comment="可转债代码")
    trade_date = Column(Date, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(BigInteger)
    amount = Column(Float)

    __table_args__ = (
        Index("idx_cbd_code_date", "code", "trade_date", unique=True),
    )


# ============ ETF 数据 ============

class ETFInfo(Base):
    """ETF 基础信息表"""
    __tablename__ = "etf_info"

    code = Column(String(20), primary_key=True, comment="ETF代码如 510300.SH")
    name = Column(String(100), comment="ETF名称")
    tracking_index = Column(String(100), comment="跟踪指数")
    management_fee = Column(Float, comment="管理费率%")
    establish_date = Column(Date, comment="成立日期")
    latest_scale = Column(Float, comment="最新规模(亿)")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)


class ETFDaily(Base):
    """ETF 日线行情表"""
    __tablename__ = "etf_daily"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(20), nullable=False, comment="ETF代码")
    trade_date = Column(Date, nullable=False)
    open = Column(Float)
    high = Column(Float)
    low = Column(Float)
    close = Column(Float)
    volume = Column(BigInteger, comment="成交量")
    amount = Column(Float, comment="成交额")

    __table_args__ = (
        Index("idx_etf_code_date", "code", "trade_date", unique=True),
    )


# ============ 因子数据 ============

class FactorMeta(Base):
    """因子元信息表 (P2-36: 支持版本追溯)

    维度说明 (常见特征库/量化平台惯例):
    - factor_kind: 语义域 — fundamental 财报科目 / per_share 每股与主要指标 / price_volume 价量
      / capital 股本 / shareholder 股东户 / top10 十大股东 / unknown
    - update_freq: 更新节奏 — daily 日频 / quarterly 财报季 / per_report 按报告披露
    - storage_hint: 是否默认写入 ``factor_values`` 长表 — factor_values / not_stored (价量仅元数据)
    """

    __tablename__ = "factor_meta"

    factor_id = Column(Integer, primary_key=True, autoincrement=True)
    factor_name = Column(String(100), nullable=False)
    version = Column(Integer, nullable=False, default=1, comment="因子版本号")
    category = Column(String(50), comment="因子分类(含 qmt_* / qlib_alpha158 等业务分桶)")
    description = Column(Text, comment="中文说明(主展示)")
    data_source = Column(String(50), comment="qmt / calculated / joinquant / …")
    qmt_field = Column(String(200), comment="QMT 表.列, 价量类可为空")
    factor_kind = Column(
        String(40), comment="fundamental|per_share|price_volume|capital|shareholder|top10|unknown",
    )
    update_freq = Column(
        String(32), comment="daily|quarterly|per_report|unknown",
    )
    storage_hint = Column(
        String(32), comment="factor_values|not_stored",
    )
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint("factor_name", "version", name="uq_factor_name_version"),
    )


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
    """财务报表数据表 (资产负债 + 利润 + 现金流)"""
    __tablename__ = "stock_financial_report"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False)
    report_type = Column(String(20), nullable=False, comment="Balance/Income/CashFlow")
    report_period = Column(String(20), nullable=False, comment="报告期 如 20240331")
    report_date = Column(Date, nullable=False, comment="公告日期")
    # 资产负债表
    total_assets = Column(Float, comment="总资产")
    total_liabilities = Column(Float, comment="总负债")
    total_equity = Column(Float, comment="股东权益")
    current_assets = Column(Float, comment="流动资产")
    current_liabilities = Column(Float, comment="流动负债")
    inventory = Column(Float, comment="存货")
    accounts_receivable = Column(Float, comment="应收账款")
    cash_and_equivalents = Column(Float, comment="货币资金")
    fixed_assets = Column(Float, comment="固定资产")
    # 利润表
    total_revenue = Column(Float, comment="营业总收入")
    operating_profit = Column(Float, comment="营业利润")
    net_profit = Column(Float, comment="净利润")
    gross_profit = Column(Float, comment="毛利润")
    operating_cost = Column(Float, comment="营业成本")
    selling_expenses = Column(Float, comment="销售费用")
    admin_expenses = Column(Float, comment="管理费用")
    financial_expenses = Column(Float, comment="财务费用")
    rd_expenses = Column(Float, comment="研发费用")
    # 现金流量表
    net_cash_flow = Column(Float, comment="现金净增加额")
    operating_cash_flow = Column(Float, comment="经营活动现金流净额")
    investing_cash_flow = Column(Float, comment="投资活动现金流净额")
    financing_cash_flow = Column(Float, comment="筹资活动现金流净额")
    # 衍生比率
    gross_margin = Column(Float, comment="毛利率%")
    net_margin = Column(Float, comment="净利率%")
    roe = Column(Float, comment="净资产收益率%")
    roa = Column(Float, comment="总资产收益率%")
    debt_ratio = Column(Float, comment="资产负债率%")
    current_ratio = Column(Float, comment="流动比率")
    quick_ratio = Column(Float, comment="速动比率")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint("code", "report_type", "report_period", name="uq_fin_code_type_period"),
        Index("idx_fin_code_date", "code", "report_date"),
        Index("idx_financial_type_period", "report_type", "report_period"),
    )


class StockFinancialIndicator(Base):
    """财务分析指标表 (每股/盈利/营运/偿债/成长)"""
    __tablename__ = "stock_financial_indicator"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False)
    report_date = Column(Date, nullable=False)
    # 每股指标
    eps_basic = Column(Float, comment="基本每股收益")
    eps_diluted = Column(Float, comment="稀释每股收益")
    bps = Column(Float, comment="每股净资产")
    dps = Column(Float, comment="每股股利")
    cfps = Column(Float, comment="每股经营现金流")
    # 盈利能力
    roe_weighted = Column(Float, comment="加权ROE%")
    roe_diluted = Column(Float, comment="摊薄ROE%")
    roa = Column(Float, comment="总资产收益率%")
    net_profit_margin = Column(Float, comment="净利率%")
    gross_profit_margin = Column(Float, comment="毛利率%")
    core_profit_margin = Column(Float, comment="核心利润率%")
    # 营运能力
    total_asset_turnover = Column(Float, comment="总资产周转率")
    inventory_turnover = Column(Float, comment="存货周转率")
    receivable_turnover = Column(Float, comment="应收账款周转率")
    inventory_turnover_days = Column(Float, comment="存货周转天数")
    receivable_turnover_days = Column(Float, comment="应收账款周转天数")
    # 偿债能力
    debt_asset_ratio = Column(Float, comment="资产负债率%")
    equity_ratio = Column(Float, comment="产权比率")
    current_ratio = Column(Float, comment="流动比率")
    quick_ratio = Column(Float, comment="速动比率")
    cash_ratio = Column(Float, comment="现金比率")
    interest_coverage = Column(Float, comment="利息保障倍数")
    # 成长能力
    revenue_growth = Column(Float, comment="营收同比增长率%")
    profit_growth = Column(Float, comment="净利润同比增长率%")
    asset_growth = Column(Float, comment="总资产增长率%")
    equity_growth = Column(Float, comment="净资产增长率%")
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

    __table_args__ = (
        Index("idx_trade_order_code_status_created", "code", "status", "created_at"),
    )


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
    strategy_tier = Column(String(20), default="ml", comment="rule/scoring/ml")
    strategy_class = Column(String(100), comment="策略实现类名, 对应 registry key")
    config_json = Column(Text, comment="策略运行时参数 JSON")
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


# ============ 板块行情 / 下载进度 / 实时快照 ============

class SectorData(Base):
    """板块行情数据表"""
    __tablename__ = "sector_data"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    sector_name = Column(String(50), nullable=False, comment="板块名称")
    trade_date = Column(Date, nullable=False, comment="交易日期")
    change_pct = Column(Float, comment="涨跌幅%")
    net_inflow = Column(Float, comment="资金净流入(亿)")
    leading_stock = Column(String(50), comment="领涨股")

    __table_args__ = (
        Index("idx_sd_sector_date", "sector_name", "trade_date", unique=True),
        Index("idx_sd_trade_date", "trade_date"),
    )


class StockDownloadProgress(Base):
    """股票数据下载进度表"""
    __tablename__ = "stock_download_progress"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False, comment="股票代码")
    sync_type = Column(String(20), nullable=False, comment="同步类型: history_full/history_inc/fundamental")
    status = Column(String(20), comment="状态: pending/running/success/failed")
    start_date = Column(Date, comment="计划开始日期")
    end_date = Column(Date, comment="计划结束日期")
    actual_start_date = Column(Date, comment="实际开始日期")
    actual_end_date = Column(Date, comment="实际结束日期")
    records_count = Column(Integer, comment="已下载记录数")
    expected_count = Column(Integer, comment="预期记录数")
    retry_count = Column(Integer, comment="重试次数")
    max_retries = Column(Integer, comment="最大重试次数")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    completed_at = Column(DateTime, comment="完成时间")
    error_message = Column(String(500), comment="错误信息")

    __table_args__ = (
        Index("idx_sdp_code_type", "code", "sync_type"),
        Index("idx_sdp_status", "status"),
    )


class AltDatacollectProgress(Base):
    """另类日频/区间采集进度 — 与 ``stock_download_progress``/``etf_download_progress`` 同思路:
    按 (种类, 范围键, 源 id) 记录已成功拉取, 避免多源级联中同一源对同一日/段重复请求。
    - ``scope_key`` 对按日表为 ``YYYYMMDD``; 对区间型调研可为 ``YYYYMMDD_YYYYMMDD``。
    """

    __tablename__ = "alt_datacollect_progress"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    category = Column(
        String(40), nullable=False,
        comment="hsgt_market|lhb|mf|survey|index_weight|sector_stock|sector_data",
    )
    scope_key = Column(String(64), nullable=False, comment="日/区间/指数快照键, 如 YYYYMMDD 或 000300.SH_20260422_l5 或 ind_map_20260422")
    source_id = Column(String(64), nullable=False, comment="级联源名, 如 tushare_hsgt / tushare_top_list")
    status = Column(String(16), nullable=False, default="ok", comment="ok: 有有效行; empty: 已尝试无行(可选手动清理后重试)")
    row_count = Column(Integer, comment="本段写入/命中行数")
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)

    __table_args__ = (
        UniqueConstraint("category", "scope_key", "source_id", name="uq_alt_dcp_cat_scope_src"),
        Index("idx_alt_dcp_cat_scope", "category", "scope_key"),
    )


class EtfDownloadProgress(Base):
    """ETF 数据下载进度表 (与 ``stock_download_progress`` 字段对齐, 供 ``etf_daily`` 断点续下)."""

    __tablename__ = "etf_download_progress"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(20), nullable=False, comment="ETF 代码 如 510300.SH")
    sync_type = Column(String(20), nullable=False, comment="同步类型, 现用 etf_daily")
    status = Column(String(20), comment="状态: pending/running/success/failed")
    start_date = Column(Date, comment="计划开始日期(全局地板/本轮)")
    end_date = Column(Date, comment="计划结束日期(本轮截止)")
    actual_start_date = Column(Date, comment="当前/最近段实际起始")
    actual_end_date = Column(Date, comment="当前/最近段实际结束")
    records_count = Column(Integer, comment="本标的已落入 etf_daily 的累计行数(本轮各段合计)")
    expected_count = Column(Integer, comment="预期记录数(保留)")
    retry_count = Column(Integer, comment="重试次数")
    max_retries = Column(Integer, comment="最大重试次数")
    created_at = Column(DateTime, default=datetime.now)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    completed_at = Column(DateTime, comment="完成时间")
    error_message = Column(String(500), comment="错误信息")

    __table_args__ = (
        UniqueConstraint("code", "sync_type", name="uq_edp_code_sync_type"),
        Index("idx_edp_code_type", "code", "sync_type"),
        Index("idx_edp_status", "status"),
    )


class StockRealtime(Base):
    """股票实时行情快照表"""
    __tablename__ = "stock_realtime"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False, comment="股票代码")
    timestamp = Column(DateTime, nullable=False, comment="快照时间戳")
    price = Column(Float, comment="当前价格")
    change = Column(Float, comment="涨跌额")
    change_pct = Column(Float, comment="涨跌幅%")
    volume = Column(BigInteger, comment="当日累计成交量(股)")
    amount = Column(Float, comment="当日累计成交额(元)")
    amplitude = Column(Float, comment="振幅%")
    turnover_rate = Column(Float, comment="换手率%")
    rise_speed = Column(Float, comment="涨速%")
    change_5min = Column(Float, comment="5分钟涨跌幅%")
    change_60d = Column(Float, comment="60日涨跌幅%")
    change_ytd = Column(Float, comment="年初至今涨跌幅%")
    market_cap = Column(Float, comment="总市值(亿)")
    float_market_cap = Column(Float, comment="流通市值(亿)")
    pe_dynamic = Column(Float, comment="动态市盈率")
    pb = Column(Float, comment="市净率")

    __table_args__ = (
        Index("idx_rt_code_ts", "code", "timestamp"),
        Index("idx_rt_timestamp", "timestamp"),
    )


# ============ 自选股 / 情报 ============

class WatchlistStock(Base):
    """自选股列表"""
    __tablename__ = "watchlist_stock"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(20), nullable=False, comment="股票代码 (如 000001.SZ)")
    name = Column(String(100), nullable=False, default="", comment="股票名称")
    source = Column(String(30), nullable=False, default="qmt", comment="来源: qmt/csv/manual")
    added_at = Column(DateTime, default=func.now(), comment="加入时间")
    removed_at = Column(DateTime, nullable=True, comment="移除时间")
    is_active = Column(Boolean, default=True, comment="是否活跃")

    __table_args__ = (
        Index("idx_watchlist_code", "code"),
        Index("idx_watchlist_active", "is_active"),
    )


class WatchlistIntel(Base):
    """自选股情报 — 新闻/公告/讨论/资金异动等原始数据"""
    __tablename__ = "watchlist_intel"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(20), nullable=False, comment="股票代码")
    intel_type = Column(String(30), nullable=False, comment="情报类型: news/announcement/discussion/capital_flow")
    title = Column(String(500), nullable=False, default="", comment="标题")
    content = Column(Text, comment="内容摘要或全文")
    source = Column(String(50), nullable=False, comment="数据来源: eastmoney/akshare/xueqiu/rss")
    url = Column(String(1000), comment="原始链接")
    raw_data = Column(JSON().with_variant(JSONB, "postgresql"), comment="原始结构化数据")
    published_at = Column(DateTime, comment="发布时间")
    collected_at = Column(DateTime, default=func.now(), comment="采集时间")

    __table_args__ = (
        Index("idx_wintel_code_type", "code", "intel_type"),
        Index("idx_wintel_collected", "collected_at"),
    )


# ============ 全球市场快照 ============

class GlobalMarketSnapshot(Base):
    """全球市场快照 — 存储外围市场原始数据, 供情绪引擎合成 global_mood"""
    __tablename__ = "global_market_snapshot"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, comment="交易日期")
    symbol = Column(String(30), nullable=False, comment="标的符号 (SPX/XAUUSD/USDCNY/...)")
    asset_class = Column(String(20), nullable=False, comment="资产类别: global_index/forex/commodity/bond/vix")
    close_price = Column(Float, comment="收盘价/最新价")
    change_pct = Column(Float, comment="涨跌幅 (%)")
    source = Column(String(30), nullable=False, comment="数据来源: yfinance/sina/akshare")
    raw_data = Column(JSON().with_variant(JSONB, "postgresql"), default=dict, comment="原始完整数据")
    collected_at = Column(DateTime, default=func.now(), comment="采集时间")

    __table_args__ = (
        Index("idx_gms_date_symbol", "trade_date", "symbol"),
        UniqueConstraint("trade_date", "symbol", "source", name="uq_gms_date_symbol_source"),
    )


# ============ 资金 / 事件 / 调研 (Tushare / AkShare 多源) ============
# 与 ETF/股票日线下载同思路: 限流、按日/区间批拉、on_conflict 落库


class HsgtMarketDaily(Base):
    """沪深港通北向(及分项)日度资金 — 市场级, 无个股"""

    __tablename__ = "hsgt_market_daily"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    trade_date = Column(Date, nullable=False, comment="交易日期")
    hgt = Column(Float, comment="沪股通(或沪)(万元/亿, 见 source 口径说明)")
    sgt = Column(Float, comment="深股通(或深)")
    north_net = Column(Float, comment="北向净买入合计(同口径下)")
    raw_data = Column(JSON().with_variant(JSONB, "postgresql"), default=dict, comment="原始行 JSON")
    source = Column(String(20), nullable=False, default="tushare", comment="tushare/akshare")
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint("trade_date", "source", name="uq_hsgt_date_source"),
        Index("idx_hsgt_trade_date", "trade_date"),
    )


class StockMoneyflowDaily(Base):
    """个股日度资金流向 — 东财/ Tushare moneyflow 口径"""

    __tablename__ = "stock_moneyflow_daily"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False, comment="6 位股票代码")
    trade_date = Column(Date, nullable=False, comment="交易日期")
    buy_sm = Column(Float, comment="小单买")
    buy_md = Column(Float, comment="中单买")
    buy_lg = Column(Float, comment="大单买")
    buy_elg = Column(Float, comment="超大单买")
    sell_sm = Column(Float, comment="小单卖")
    sell_md = Column(Float, comment="中单卖")
    sell_lg = Column(Float, comment="大单卖")
    sell_elg = Column(Float, comment="超大单卖")
    net_mf = Column(Float, comment="主力净额(若接口提供)")
    net_mf_rate = Column(Float, comment="主力净占比%")
    raw_data = Column(JSON().with_variant(JSONB, "postgresql"), default=dict)
    source = Column(String(20), nullable=False, default="tushare")
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        UniqueConstraint("code", "trade_date", name="uq_smd_code_date"),
        Index("idx_smd_code_date", "code", "trade_date"),
        Index("idx_smd_date", "trade_date"),
    )


class StockLhbDaily(Base):
    """龙虎榜日明细 (可按同一日多行: 买卖方向/原因不同)"""

    __tablename__ = "stock_lhb_daily"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False, comment="6 位股票代码")
    name = Column(String(50), default="", comment="股票名称")
    trade_date = Column(Date, nullable=False, comment="交易日期")
    reason = Column(String(200), default="", comment="上榜原因/解读")
    side = Column(String(10), default="", comment="买/卖/等")
    buy = Column(Float, comment="买额(万)")
    sell = Column(Float, comment="卖额(万)")
    net = Column(Float, comment="净额(万)")
    amount_rate = Column(Float, comment="成交额占市场% 等(若有)")
    turnover = Column(Float, comment="市场总成交(万) 等(若有)")
    float_ratio = Column(Float, comment="流通市值比% 等(若有)")
    raw_data = Column(JSON().with_variant(JSONB, "postgresql"), default=dict)
    source = Column(String(20), nullable=False, default="tushare")
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_slb_code_date", "code", "trade_date"),
        UniqueConstraint("code", "trade_date", "reason", "side", name="uq_lhb_code_date_reason_side"),
    )


class InstitutionSurvey(Base):
    """机构调研 (上市公司接待调研活动)"""

    __tablename__ = "institution_survey"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    code = Column(String(10), nullable=False, comment="6 位股票代码")
    name = Column(String(100), default="", comment="公司简称")
    survey_date = Column(Date, nullable=False, comment="公告/调研活动日期(通常取公告日)")
    org_name = Column(String(200), default="", comment="机构名称")
    org_type = Column(String(100), default="", comment="机构类型/接待对象类型")
    content = Column(Text, comment="调研内容摘要(若有)")
    raw_data = Column(JSON().with_variant(JSONB, "postgresql"), default=dict)
    source = Column(String(20), nullable=False, default="tushare")
    created_at = Column(DateTime, default=datetime.now)

    __table_args__ = (
        Index("idx_isvy_code_date", "code", "survey_date"),
        UniqueConstraint("code", "survey_date", "org_name", name="uq_isvy_code_date_org"),
    )
