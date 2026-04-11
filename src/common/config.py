"""配置管理 — 所有参数通过 .env + 环境变量注入

优先级: 系统环境变量 > 项目根目录 .env > 代码默认值
"""
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).parent.parent.parent

_SHARED_CFG = SettingsConfigDict(
    populate_by_name=True,
    extra="ignore",
    env_file=str(PROJECT_ROOT / ".env"),
    env_file_encoding="utf-8",
)


# ================================================================
# 基础设施
# ================================================================

class DatabaseConfig(BaseSettings):
    model_config = _SHARED_CFG
    url: str = Field(
        default="postgresql://localhost:5432/qt_quant",
        alias="DATABASE_URL",
    )
    pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    pool_timeout: int = Field(default=30, alias="DB_POOL_TIMEOUT")
    pool_recycle: int = Field(default=1800, alias="DB_POOL_RECYCLE")


class QMTConfig(BaseSettings):
    model_config = _SHARED_CFG
    qmt_path: str = Field(default="", alias="QMT_PATH")
    account_id: str = Field(default="", alias="QMT_ACCOUNT_ID")
    account_type: str = Field(default="STOCK", alias="QMT_ACCOUNT_TYPE")


class DownloadConfig(BaseSettings):
    model_config = _SHARED_CFG
    batch_size: int = Field(default=500, alias="DL_BATCH_SIZE")
    batch_pause: float = Field(default=2.0, alias="DL_BATCH_PAUSE")
    retry_count: int = Field(default=3, alias="DL_RETRY_COUNT")
    retry_delay: float = Field(default=5.0, alias="DL_RETRY_DELAY")
    download_timeout: int = Field(default=600, alias="DL_TIMEOUT")
    default_start_1d: str = Field(default="20160101", alias="DL_START_1D")
    default_start_1w: str = Field(default="20160101", alias="DL_START_1W")
    default_start_5m: str = Field(default="20230101", alias="DL_START_5M")
    default_start_15m: str = Field(default="20230101", alias="DL_START_15M")
    default_start_30m: str = Field(default="20230101", alias="DL_START_30M")
    default_start_1h: str = Field(default="20230101", alias="DL_START_1H")
    default_start_1m: str = Field(default="20250101", alias="DL_START_1M")
    default_start_tick: str = Field(default="20260301", alias="DL_START_TICK")


class APIConfig(BaseSettings):
    model_config = _SHARED_CFG
    host: str = Field(default="0.0.0.0", alias="API_HOST")
    port: int = Field(default=8012, alias="API_PORT")


class WebhookConfig(BaseSettings):
    model_config = _SHARED_CFG
    openclaw_url: str = Field(default="", alias="OPENCLAW_WEBHOOK_URL")
    feishu_url: str = Field(default="", alias="FEISHU_WEBHOOK_URL")
    feishu_app_id: str = Field(default="", alias="FEISHU_APP_ID")
    feishu_app_secret: str = Field(default="", alias="FEISHU_APP_SECRET")


# ================================================================
# 机器学习
# ================================================================

class MLIterateConfig(BaseSettings):
    model_config = _SHARED_CFG
    max_iterations: int = Field(default=50, alias="ML_ITERATE_MAX_ITERATIONS")
    target_sharpe: float = Field(default=2.0, alias="ML_ITERATE_TARGET_SHARPE")
    convergence_patience: int = Field(default=10, alias="ML_ITERATE_CONVERGENCE_PATIENCE")
    initial_top_n: int = Field(default=30, alias="ML_ITERATE_INITIAL_TOP_N")
    min_factors: int = Field(default=5, alias="ML_ITERATE_MIN_FACTORS")


class MLConfig(BaseSettings):
    model_config = _SHARED_CFG
    model_dir: str = Field(default="./models", alias="ML_MODEL_DIR")
    label_period: int = Field(default=2, alias="ML_LABEL_PERIOD")
    train_window: int = Field(default=252, alias="ML_TRAIN_WINDOW")
    retrain_step: int = Field(default=21, alias="ML_RETRAIN_STEP")
    iterate: MLIterateConfig = MLIterateConfig()


# ================================================================
# 回测 & 交易 & 风控
# ================================================================

class BacktestConfig(BaseSettings):
    model_config = _SHARED_CFG
    initial_capital: float = Field(default=1_000_000.0, alias="BACKTEST_INITIAL_CAPITAL")
    max_position_pct: float = Field(default=0.20, alias="BACKTEST_MAX_POSITION_PCT")
    max_total_position_pct: float = Field(default=0.80, alias="BACKTEST_MAX_TOTAL_POSITION_PCT")
    max_holdings: int = Field(default=5, alias="BACKTEST_MAX_HOLDINGS")


class RiskConfig(BaseSettings):
    model_config = _SHARED_CFG
    stop_loss_pct: float = Field(default=-8.0, alias="RISK_STOP_LOSS_PCT")
    take_profit_pct: float = Field(default=20.0, alias="RISK_TAKE_PROFIT_PCT")
    max_single_position_pct: float = Field(default=30.0, alias="RISK_MAX_SINGLE_POSITION_PCT")
    max_total_position_pct: float = Field(default=80.0, alias="RISK_MAX_TOTAL_POSITION_PCT")
    max_daily_loss_pct: float = Field(default=-5.0, alias="RISK_MAX_DAILY_LOSS_PCT")


class TradingConfig(BaseSettings):
    model_config = _SHARED_CFG
    paper_trading: bool = Field(default=True, alias="TRADING_PAPER_MODE")
    risk: RiskConfig = RiskConfig()


# ================================================================
# 持仓监控 / 信号仲裁 / 仓位分配
# ================================================================

class PositionMonitorConfig(BaseSettings):
    model_config = _SHARED_CFG
    default_stop_loss_pct: float = Field(default=-8.0, alias="PM_STOP_LOSS_PCT")
    default_take_profit_pct: float = Field(default=15.0, alias="PM_TAKE_PROFIT_PCT")
    default_trailing_stop_pct: float = Field(default=5.0, alias="PM_TRAILING_STOP_PCT")
    default_max_hold_days: int = Field(default=10, alias="PM_MAX_HOLD_DAYS")
    enable_trailing_stop: bool = Field(default=True, alias="PM_ENABLE_TRAILING_STOP")
    force_sell_on_expiry: bool = Field(default=True, alias="PM_FORCE_SELL_EXPIRY")
    partial_take_profit: bool = Field(default=False, alias="PM_PARTIAL_TAKE_PROFIT")
    partial_take_profit_ratio: float = Field(default=0.5, alias="PM_PARTIAL_TP_RATIO")
    expiry_loss_threshold: float = Field(default=0.0, alias="PM_EXPIRY_LOSS_THRESHOLD")


class ArbiterConfig(BaseSettings):
    model_config = _SHARED_CFG
    max_holdings: int = Field(default=5, alias="ARB_MAX_HOLDINGS")
    max_buy_per_day: int = Field(default=2, alias="ARB_MAX_BUY_PER_DAY")
    max_sell_per_day: int = Field(default=5, alias="ARB_MAX_SELL_PER_DAY")
    min_amount_wan: float = Field(default=5000.0, alias="ARB_MIN_AMOUNT_WAN")
    multi_strategy_bonus: float = Field(default=0.2, alias="ARB_MULTI_BONUS")


class SizerConfig(BaseSettings):
    model_config = _SHARED_CFG
    mode: str = Field(default="equal", alias="SIZER_MODE")
    max_single_pct: float = Field(default=20.0, alias="SIZER_MAX_SINGLE_PCT")
    max_total_pct: float = Field(default=80.0, alias="SIZER_MAX_TOTAL_PCT")
    min_trade_amount: float = Field(default=5000.0, alias="SIZER_MIN_TRADE_AMOUNT")
    lot_size: int = Field(default=100, alias="SIZER_LOT_SIZE")
    atr_lookback: int = Field(default=14, alias="SIZER_ATR_LOOKBACK")


# ================================================================
# Signal 默认值
# ================================================================

class SignalDefaultsConfig(BaseSettings):
    model_config = _SHARED_CFG
    stop_loss_pct: float = Field(default=-8.0, alias="SIG_STOP_LOSS_PCT")
    take_profit_pct: float = Field(default=15.0, alias="SIG_TAKE_PROFIT_PCT")
    max_hold_days: int = Field(default=10, alias="SIG_MAX_HOLD_DAYS")
    trailing_stop_pct: float = Field(default=0.0, alias="SIG_TRAILING_STOP_PCT")
    min_amount: float = Field(default=5000.0, alias="SIG_MIN_AMOUNT")


# ================================================================
# Tier 1 规则策略参数
# ================================================================

class MomentumStratConfig(BaseSettings):
    model_config = _SHARED_CFG
    lookback_days: int = Field(default=20, alias="STRAT_MOM_LOOKBACK")
    top_n: int = Field(default=10, alias="STRAT_MOM_TOP_N")
    min_turnover: float = Field(default=0.5, alias="STRAT_MOM_MIN_TURNOVER")
    stop_loss_pct: float = Field(default=-8.0, alias="STRAT_MOM_STOP_LOSS")
    take_profit_pct: float = Field(default=15.0, alias="STRAT_MOM_TAKE_PROFIT")
    max_hold_days: int = Field(default=5, alias="STRAT_MOM_MAX_HOLD_DAYS")
    trailing_stop_pct: float = Field(default=5.0, alias="STRAT_MOM_TRAILING_STOP")


class ReversalStratConfig(BaseSettings):
    model_config = _SHARED_CFG
    lookback_days: int = Field(default=10, alias="STRAT_REV_LOOKBACK")
    top_n: int = Field(default=10, alias="STRAT_REV_TOP_N")
    max_drawdown: float = Field(default=-30.0, alias="STRAT_REV_MAX_DRAWDOWN")
    stop_loss_pct: float = Field(default=-5.0, alias="STRAT_REV_STOP_LOSS")
    take_profit_pct: float = Field(default=10.0, alias="STRAT_REV_TAKE_PROFIT")
    max_hold_days: int = Field(default=5, alias="STRAT_REV_MAX_HOLD_DAYS")
    trailing_stop_pct: float = Field(default=3.0, alias="STRAT_REV_TRAILING_STOP")
    bounce_target_pct: float = Field(default=5.0, alias="STRAT_REV_BOUNCE_TARGET")


class IndustryRotationStratConfig(BaseSettings):
    model_config = _SHARED_CFG
    lookback_days: int = Field(default=20, alias="STRAT_IND_LOOKBACK")
    top_industries: int = Field(default=3, alias="STRAT_IND_TOP_INDUSTRIES")
    stocks_per_industry: int = Field(default=3, alias="STRAT_IND_STOCKS_PER_IND")
    stop_loss_pct: float = Field(default=-8.0, alias="STRAT_IND_STOP_LOSS")
    take_profit_pct: float = Field(default=15.0, alias="STRAT_IND_TAKE_PROFIT")
    max_hold_days: int = Field(default=10, alias="STRAT_IND_MAX_HOLD_DAYS")
    trailing_stop_pct: float = Field(default=5.0, alias="STRAT_IND_TRAILING_STOP")


class MovingAverageStratConfig(BaseSettings):
    model_config = _SHARED_CFG
    short_ma: int = Field(default=5, alias="STRAT_MA_SHORT")
    long_ma: int = Field(default=20, alias="STRAT_MA_LONG")
    top_n: int = Field(default=15, alias="STRAT_MA_TOP_N")
    stop_loss_pct: float = Field(default=-6.0, alias="STRAT_MA_STOP_LOSS")
    take_profit_pct: float = Field(default=12.0, alias="STRAT_MA_TAKE_PROFIT")
    max_hold_days: int = Field(default=10, alias="STRAT_MA_MAX_HOLD_DAYS")
    trailing_stop_pct: float = Field(default=4.0, alias="STRAT_MA_TRAILING_STOP")


class GridTradingStratConfig(BaseSettings):
    model_config = _SHARED_CFG
    grid_pct: float = Field(default=10.0, alias="STRAT_GRID_PCT")
    lookback_days: int = Field(default=60, alias="STRAT_GRID_LOOKBACK")
    top_n: int = Field(default=10, alias="STRAT_GRID_TOP_N")
    stop_loss_pct: float = Field(default=-5.0, alias="STRAT_GRID_STOP_LOSS")
    take_profit_pct: float = Field(default=6.0, alias="STRAT_GRID_TAKE_PROFIT")
    max_hold_days: int = Field(default=5, alias="STRAT_GRID_MAX_HOLD_DAYS")


class CBDualLowStratConfig(BaseSettings):
    model_config = _SHARED_CFG
    price_weight: float = Field(default=1.0, alias="STRAT_CB_PRICE_WEIGHT")
    premium_weight: float = Field(default=1.0, alias="STRAT_CB_PREMIUM_WEIGHT")
    max_price: float = Field(default=130.0, alias="STRAT_CB_MAX_PRICE")
    max_premium: float = Field(default=50.0, alias="STRAT_CB_MAX_PREMIUM")
    min_rating: str = Field(default="AA-", alias="STRAT_CB_MIN_RATING")
    top_n: int = Field(default=20, alias="STRAT_CB_TOP_N")
    stop_loss_pct: float = Field(default=-3.0, alias="STRAT_CB_STOP_LOSS")
    take_profit_pct: float = Field(default=10.0, alias="STRAT_CB_TAKE_PROFIT")
    max_hold_days: int = Field(default=20, alias="STRAT_CB_MAX_HOLD_DAYS")
    min_amount: float = Field(default=1000.0, alias="STRAT_CB_MIN_AMOUNT")


class LowVolDividendStratConfig(BaseSettings):
    model_config = _SHARED_CFG
    lookback_days: int = Field(default=60, alias="STRAT_LV_LOOKBACK")
    vol_weight: float = Field(default=0.5, alias="STRAT_LV_VOL_WEIGHT")
    div_weight: float = Field(default=0.5, alias="STRAT_LV_DIV_WEIGHT")
    max_vol_pct: float = Field(default=40.0, alias="STRAT_LV_MAX_VOL_PCT")
    min_dividend_yield: float = Field(default=2.0, alias="STRAT_LV_MIN_DIV_YIELD")
    top_n: int = Field(default=15, alias="STRAT_LV_TOP_N")
    stop_loss_pct: float = Field(default=-5.0, alias="STRAT_LV_STOP_LOSS")
    take_profit_pct: float = Field(default=10.0, alias="STRAT_LV_TAKE_PROFIT")
    max_hold_days: int = Field(default=20, alias="STRAT_LV_MAX_HOLD_DAYS")
    trailing_stop_pct: float = Field(default=3.0, alias="STRAT_LV_TRAILING_STOP")


# ================================================================
# 数据采集 (datacollect)
# ================================================================

class DatacollectConfig(BaseSettings):
    model_config = _SHARED_CFG
    akshare_rate: float = Field(default=0.15, alias="DATACOLLECT_AKSHARE_RATE")
    akshare_burst: int = Field(default=3, alias="DATACOLLECT_AKSHARE_BURST")
    baostock_rate: float = Field(default=5.0, alias="DATACOLLECT_BAOSTOCK_RATE")
    baostock_burst: int = Field(default=10, alias="DATACOLLECT_BAOSTOCK_BURST")
    tushare_token: str = Field(default="", alias="TUSHARE_TOKEN")
    tushare_rate: float = Field(default=0.8, alias="DATACOLLECT_TUSHARE_RATE")
    tushare_burst: int = Field(default=5, alias="DATACOLLECT_TUSHARE_BURST")
    adata_rate: float = Field(default=0.5, alias="DATACOLLECT_ADATA_RATE")
    adata_burst: int = Field(default=5, alias="DATACOLLECT_ADATA_BURST")
    pytdx_rate: float = Field(default=1.0, alias="DATACOLLECT_PYTDX_RATE")
    pytdx_burst: int = Field(default=5, alias="DATACOLLECT_PYTDX_BURST")
    eastmoney_rate: float = Field(default=0.1, alias="DATACOLLECT_EASTMONEY_RATE")
    eastmoney_burst: int = Field(default=2, alias="DATACOLLECT_EASTMONEY_BURST")
    max_retries: int = Field(default=5, alias="DATACOLLECT_MAX_RETRIES")
    retry_backoff_base: float = Field(default=2.0, alias="DATACOLLECT_RETRY_BACKOFF")
    request_timeout: int = Field(default=30, alias="DATACOLLECT_REQUEST_TIMEOUT")
    proxy_url: str = Field(default="", alias="DATACOLLECT_PROXY_URL")
    archive_days: int = Field(default=90, alias="DATACOLLECT_ARCHIVE_DAYS")
    impersonate: str = Field(default="chrome", alias="DATACOLLECT_IMPERSONATE")

    # A28: per-source concurrency
    global_concurrency: int = Field(default=50, alias="DATACOLLECT_GLOBAL_CONCURRENCY")

    # A33: Write buffer
    write_buffer_size: int = Field(default=200, alias="DATACOLLECT_WRITE_BUFFER_SIZE")
    write_flush_interval: float = Field(default=1.0, alias="DATACOLLECT_WRITE_FLUSH_INTERVAL")
    write_batch_size: int = Field(default=5000, alias="DATACOLLECT_WRITE_BATCH_SIZE")

    # A37: Memory chunk threshold
    chunk_threshold: int = Field(default=100000, alias="DATACOLLECT_CHUNK_THRESHOLD")

    # A38: Proxy pool
    proxy_enabled: bool = Field(default=False, alias="DATACOLLECT_PROXY_ENABLED")
    proxy_urls: str = Field(default="", alias="DATACOLLECT_PROXY_URLS")
    proxy_rotate_strategy: str = Field(default="round_robin", alias="DATACOLLECT_PROXY_ROTATE_STRATEGY")
    proxy_health_check_interval: int = Field(default=300, alias="DATACOLLECT_PROXY_HEALTH_CHECK_INTERVAL")
    proxy_blacklist_cooldown: int = Field(default=600, alias="DATACOLLECT_PROXY_BLACKLIST_COOLDOWN")

    # Tier 2: Global market intelligence sources
    yfinance_rate: float = Field(default=0.5, alias="DATACOLLECT_YFINANCE_RATE")
    yfinance_burst: int = Field(default=10, alias="DATACOLLECT_YFINANCE_BURST")
    sina_rate: float = Field(default=0.2, alias="DATACOLLECT_SINA_RATE")
    sina_burst: int = Field(default=3, alias="DATACOLLECT_SINA_BURST")
    rss_rate: float = Field(default=1.0, alias="DATACOLLECT_RSS_RATE")
    rss_burst: int = Field(default=5, alias="DATACOLLECT_RSS_BURST")


# ================================================================
# 情绪引擎
# ================================================================

class SentimentConfig(BaseSettings):
    model_config = _SHARED_CFG
    enabled: bool = Field(default=True, alias="SENTIMENT_ENABLED")
    auto_apply: bool = Field(default=False, alias="SENTIMENT_AUTO_APPLY")
    collect_schedule: str = Field(
        default="09:00,12:00,15:30,20:00", alias="SENTIMENT_COLLECT_SCHEDULE",
    )
    w_earning: float = Field(default=0.25, alias="SENTIMENT_W_EARNING")
    w_capital: float = Field(default=0.25, alias="SENTIMENT_W_CAPITAL")
    w_volatility: float = Field(default=0.15, alias="SENTIMENT_W_VOLATILITY")
    w_sector: float = Field(default=0.10, alias="SENTIMENT_W_SECTOR")
    w_news: float = Field(default=0.15, alias="SENTIMENT_W_NEWS")
    w_global: float = Field(default=0.10, alias="SENTIMENT_W_GLOBAL")


# ================================================================
# Tier 2 打分策略参数
# ================================================================

class ScoringStratConfig(BaseSettings):
    model_config = _SHARED_CFG
    ic_window: int = Field(default=20, alias="STRAT_SCORE_IC_WINDOW")
    top_n: int = Field(default=20, alias="STRAT_SCORE_TOP_N")
    neutralize_industry: bool = Field(default=False, alias="STRAT_SCORE_NEUTRALIZE")
    stop_loss_pct: float = Field(default=-8.0, alias="STRAT_SCORE_STOP_LOSS")
    take_profit_pct: float = Field(default=15.0, alias="STRAT_SCORE_TAKE_PROFIT")
    max_hold_days: int = Field(default=10, alias="STRAT_SCORE_MAX_HOLD_DAYS")
    trailing_stop_pct: float = Field(default=5.0, alias="STRAT_SCORE_TRAILING_STOP")


# ================================================================
# Tier 3 ML 策略参数
# ================================================================

class MLStratConfig(BaseSettings):
    model_config = _SHARED_CFG
    top_n: int = Field(default=10, alias="STRAT_ML_TOP_N")
    long_threshold: float = Field(default=0.0, alias="STRAT_ML_LONG_THRESHOLD")
    stop_loss_pct: float = Field(default=-8.0, alias="STRAT_ML_STOP_LOSS")
    take_profit_pct: float = Field(default=15.0, alias="STRAT_ML_TAKE_PROFIT")
    max_hold_days: int = Field(default=8, alias="STRAT_ML_MAX_HOLD_DAYS")
    trailing_stop_pct: float = Field(default=5.0, alias="STRAT_ML_TRAILING_STOP")


# ================================================================
# 汇总
# ================================================================

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        populate_by_name=True,
        extra="ignore",
        env_file=str(PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    database: DatabaseConfig = DatabaseConfig()
    qmt: QMTConfig = QMTConfig()
    download: DownloadConfig = DownloadConfig()
    datacollect: DatacollectConfig = DatacollectConfig()
    api: APIConfig = APIConfig()
    webhook: WebhookConfig = WebhookConfig()

    ml: MLConfig = MLConfig()
    backtest: BacktestConfig = BacktestConfig()
    trading: TradingConfig = TradingConfig()

    position_monitor: PositionMonitorConfig = PositionMonitorConfig()
    arbiter: ArbiterConfig = ArbiterConfig()
    sizer: SizerConfig = SizerConfig()
    signal_defaults: SignalDefaultsConfig = SignalDefaultsConfig()

    strat_momentum: MomentumStratConfig = MomentumStratConfig()
    strat_reversal: ReversalStratConfig = ReversalStratConfig()
    strat_industry_rotation: IndustryRotationStratConfig = IndustryRotationStratConfig()
    strat_moving_average: MovingAverageStratConfig = MovingAverageStratConfig()
    strat_grid_trading: GridTradingStratConfig = GridTradingStratConfig()
    strat_cb_dual_low: CBDualLowStratConfig = CBDualLowStratConfig()
    strat_low_vol_dividend: LowVolDividendStratConfig = LowVolDividendStratConfig()
    sentiment: SentimentConfig = SentimentConfig()
    strat_scoring: ScoringStratConfig = ScoringStratConfig()
    strat_ml: MLStratConfig = MLStratConfig()


settings = Settings()
