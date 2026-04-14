"""配置管理 — 所有参数通过 env/*.env.* 分模块文件 + 环境变量注入

优先级: 系统环境变量 > env/*.env.* > 代码默认值
文件按模块拆分在 env/ 目录下, 便于维护:
  env/.env.db, env/.env.qmt, env/.env.datacollect, env/.env.api,
  env/.env.ml, env/.env.trading, env/.env.strategy, env/.env.webhook
"""
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).parent.parent.parent

_ENV_DIR = PROJECT_ROOT / "env"
_ENV_FILES: tuple[str, ...] = tuple(
    str(p) for p in sorted(_ENV_DIR.glob(".env.*"))
    if p.name != ".env.example"
)

_SHARED_CFG = SettingsConfigDict(
    populate_by_name=True,
    extra="ignore",
    env_file=_ENV_FILES,
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
# 数据质量
# ================================================================

class DataQualityConfig(BaseSettings):
    model_config = _SHARED_CFG
    enabled: bool = Field(default=True, alias="DATA_QUALITY_ENABLED")
    z_threshold: float = Field(default=10.0, alias="DATA_QUALITY_Z_THRESHOLD")
    max_pct_change: float = Field(default=22.0, alias="DATA_QUALITY_MAX_PCT_CHANGE")


# ================================================================
# 系统容错
# ================================================================

class ResilienceConfig(BaseSettings):
    model_config = _SHARED_CFG
    circuit_breaker_threshold: int = Field(default=5, alias="RESILIENCE_CB_THRESHOLD")
    recovery_timeout_sec: float = Field(default=60.0, alias="RESILIENCE_RECOVERY_TIMEOUT")
    degradation_enabled: bool = Field(default=True, alias="RESILIENCE_DEGRADATION_ENABLED")


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
    cv_n_splits: int = Field(default=5, alias="ML_CV_N_SPLITS")
    cv_purge_days: int = Field(default=3, alias="ML_CV_PURGE_DAYS")
    cv_embargo_pct: float = Field(default=0.05, alias="ML_CV_EMBARGO_PCT")


# ================================================================
# 回测 & 交易 & 风控
# ================================================================

class BacktestConfig(BaseSettings):
    model_config = _SHARED_CFG
    initial_capital: float = Field(default=1_000_000.0, alias="BACKTEST_INITIAL_CAPITAL")
    max_position_pct: float = Field(default=0.20, alias="BACKTEST_MAX_POSITION_PCT")
    max_total_position_pct: float = Field(default=0.80, alias="BACKTEST_MAX_TOTAL_POSITION_PCT")
    max_holdings: int = Field(default=5, alias="BACKTEST_MAX_HOLDINGS")

    # A 股交易费率
    commission_rate: float = Field(default=0.000115, alias="FEE_COMMISSION_RATE")
    commission_min: float = Field(default=5.0, alias="FEE_COMMISSION_MIN")
    stamp_tax_rate: float = Field(default=0.0005, alias="FEE_STAMP_TAX_RATE")
    transfer_fee_rate: float = Field(default=0.00002, alias="FEE_TRANSFER_FEE_RATE")

    # 港股通交易费率
    hk_commission_rate: float = Field(default=0.0003, alias="FEE_HK_COMMISSION_RATE")
    hk_commission_min: float = Field(default=5.0, alias="FEE_HK_COMMISSION_MIN")
    hk_stamp_tax_rate: float = Field(default=0.001, alias="FEE_HK_STAMP_TAX_RATE")
    hk_trading_fee_rate: float = Field(default=0.0000565, alias="FEE_HK_TRADING_FEE_RATE")
    hk_transaction_levy_rate: float = Field(default=0.000027, alias="FEE_HK_TRANSACTION_LEVY_RATE")
    hk_frc_levy_rate: float = Field(default=0.0000015, alias="FEE_HK_FRC_LEVY_RATE")
    hk_settlement_fee_rate: float = Field(default=0.000042, alias="FEE_HK_SETTLEMENT_FEE_RATE")
    hk_settlement_fee_min: float = Field(default=2.0, alias="FEE_HK_SETTLEMENT_FEE_MIN")


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
    max_daily_turnover_pct: float = Field(default=0.20, alias="ARB_MAX_DAILY_TURNOVER_PCT")


class SizerConfig(BaseSettings):
    model_config = _SHARED_CFG
    mode: str = Field(default="equal", alias="SIZER_MODE")
    max_single_pct: float = Field(default=20.0, alias="SIZER_MAX_SINGLE_PCT")
    max_total_pct: float = Field(default=80.0, alias="SIZER_MAX_TOTAL_PCT")
    min_trade_amount: float = Field(default=5000.0, alias="SIZER_MIN_TRADE_AMOUNT")
    lot_size: int = Field(default=100, alias="SIZER_LOT_SIZE")
    atr_lookback: int = Field(default=14, alias="SIZER_ATR_LOOKBACK")
    kelly_fraction: float = Field(default=0.25, alias="SIZER_KELLY_FRACTION")
    drawdown_guard_enabled: bool = Field(default=True, alias="SIZER_DRAWDOWN_GUARD_ENABLED")


class RegimeGateConfig(BaseSettings):
    model_config = _SHARED_CFG
    enabled: bool = Field(default=False, alias="REGIME_GATE_ENABLED")
    drift_window: int = Field(default=63, alias="REGIME_GATE_DRIFT_WINDOW")
    drift_threshold: float = Field(default=0.60, alias="REGIME_GATE_DRIFT_THRESHOLD")
    vol_percentile_window: int = Field(default=252, alias="REGIME_GATE_VOL_WINDOW")
    vol_high_pct: float = Field(default=0.80, alias="REGIME_GATE_VOL_HIGH_PCT")


# ================================================================
# Signal 默认值
# ================================================================

class TradingRulesConfig(BaseSettings):
    model_config = _SHARED_CFG
    cross_border_etf_prefixes: list[str] = Field(
        default_factory=list,
        alias="TRADING_RULES_CROSS_BORDER_ETF_PREFIXES",
    )


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

    # Circuit breaker
    cb_failure_threshold: int = Field(default=5, alias="DATACOLLECT_CB_FAILURE_THRESHOLD")
    cb_cooldown_sec: float = Field(default=300.0, alias="DATACOLLECT_CB_COOLDOWN_SEC")
    cb_success_threshold: int = Field(default=2, alias="DATACOLLECT_CB_SUCCESS_THRESHOLD")

    # Dead letter queue
    dead_letter_backoff_base: float = Field(default=60.0, alias="DATACOLLECT_DL_BACKOFF_BASE")
    dead_letter_max_retries: int = Field(default=3, alias="DATACOLLECT_DL_MAX_RETRIES")
    dead_letter_pending_limit: int = Field(default=100, alias="DATACOLLECT_DL_PENDING_LIMIT")

    # Anti-crawl sentinel
    sentinel_latency_spike_sec: float = Field(default=10.0, alias="DATACOLLECT_SENTINEL_LATENCY_SPIKE_SEC")
    sentinel_latency_warn_sec: float = Field(default=5.0, alias="DATACOLLECT_SENTINEL_LATENCY_WARN_SEC")
    sentinel_soft_block_min_bytes: int = Field(default=50, alias="DATACOLLECT_SENTINEL_SOFT_BLOCK_MIN_BYTES")
    sentinel_consecutive_timeout_limit: int = Field(default=2, alias="DATACOLLECT_SENTINEL_CONSECUTIVE_TIMEOUT")
    sentinel_history_size: int = Field(default=50, alias="DATACOLLECT_SENTINEL_HISTORY_SIZE")

    # Data validator
    validator_pct_change_limit: float = Field(default=22.0, alias="DATACOLLECT_VALIDATOR_PCT_CHANGE_LIMIT")
    validator_zscore_limit: float = Field(default=10.0, alias="DATACOLLECT_VALIDATOR_ZSCORE_LIMIT")

    # Idempotency
    idempotency_ttl_hours: int = Field(default=24, alias="DATACOLLECT_IDEMPOTENCY_TTL_HOURS")

    # RSS feeds
    rsshub_base_url: str = Field(default="https://rsshub.app", alias="DATACOLLECT_RSSHUB_BASE_URL")
    rss_max_entries: int = Field(default=50, alias="DATACOLLECT_RSS_MAX_ENTRIES")
    rss_summary_max_chars: int = Field(default=500, alias="DATACOLLECT_RSS_SUMMARY_MAX_CHARS")


# ================================================================
# 数据清洗 LLM (dataclean)
# ================================================================

class DatacleanConfig(BaseSettings):
    model_config = _SHARED_CFG
    llm_provider: str = Field(default="deepseek", alias="LLM_PROVIDER")
    deepseek_api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field(default="https://api.deepseek.com", alias="DEEPSEEK_BASE_URL")
    deepseek_model: str = Field(default="deepseek-chat", alias="DEEPSEEK_MODEL")
    deepseek_reasoner_model: str = Field(default="deepseek-reasoner", alias="DEEPSEEK_REASONER_MODEL")
    qwen_api_key: str = Field(default="", alias="QWEN_API_KEY")
    qwen_base_url: str = Field(
        default="https://dashscope.aliyuncs.com/compatible-mode/v1",
        alias="QWEN_BASE_URL",
    )
    qwen_model: str = Field(default="qwen3-max", alias="QWEN_MODEL")
    llm_temperature: float = Field(default=0.1, alias="LLM_TEMPERATURE")
    llm_max_retries: int = Field(default=2, alias="LLM_MAX_RETRIES")
    llm_timeout: int = Field(default=30, alias="LLM_TIMEOUT")


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
    w_northbound: float = Field(default=0.0, alias="SENTIMENT_W_NORTHBOUND")


# ================================================================
# ETF 轮动策略 (P1-20)
# ================================================================

class EtfRotationConfig(BaseSettings):
    model_config = _SHARED_CFG
    enabled: bool = Field(default=True, alias="ETF_ROTATION_ENABLED")
    momentum_method: str = Field(default="13612w", alias="ETF_ROTATION_MOMENTUM_METHOD")
    lookback_days: int = Field(default=25, alias="ETF_ROTATION_LOOKBACK_DAYS")
    top_k: int = Field(default=2, alias="ETF_ROTATION_TOP_K")
    rebalance_interval: int = Field(default=20, alias="ETF_ROTATION_REBALANCE_INTERVAL")
    min_hold_days: int = Field(default=9, alias="ETF_ROTATION_MIN_HOLD_DAYS")
    rank_threshold: float = Field(default=0.10, alias="ETF_ROTATION_RANK_THRESHOLD")
    score_min: float = Field(default=0.0, alias="ETF_ROTATION_SCORE_MIN")
    score_max: float = Field(default=5.0, alias="ETF_ROTATION_SCORE_MAX")
    stop_loss_daily: float = Field(default=0.05, alias="ETF_ROTATION_STOP_LOSS_DAILY")
    stop_loss_3d: float = Field(default=0.08, alias="ETF_ROTATION_STOP_LOSS_3D")
    use_caa_weights: bool = Field(default=False, alias="ETF_ROTATION_USE_CAA_WEIGHTS")
    caa_target_vol: float = Field(default=0.10, alias="ETF_ROTATION_CAA_TARGET_VOL")
    volatility_gate: bool = Field(default=True, alias="ETF_ROTATION_VOLATILITY_GATE")
    risk_pool: str = Field(
        default='["510300.SH","159915.SZ","510500.SH","510880.SH","513180.SH","513100.SH","513500.SH","513880.SH","513030.SH","518880.SH","159985.SZ"]',
        alias="ETF_ROTATION_RISK_POOL",
    )
    defensive_pool: str = Field(
        default='["511260.SH","511010.SH"]',
        alias="ETF_ROTATION_DEFENSIVE_POOL",
    )
    canary_pool: str = Field(
        default='["513100.SH","511260.SH"]',
        alias="ETF_ROTATION_CANARY_POOL",
    )


# ================================================================
# 多源因子管线 (P1-21)
# ================================================================

class FactorPipelineConfig(BaseSettings):
    model_config = _SHARED_CFG
    alpha158_enabled: bool = Field(default=True, alias="FACTOR_ALPHA158_ENABLED")
    alpha158_windows: str = Field(default="5,10,20,30,60", alias="FACTOR_ALPHA158_WINDOWS")
    xt_enabled: bool = Field(default=False, alias="FACTOR_XT_ENABLED")
    xt_categories: str = Field(
        default="factor_growth,factor_base_derivative,factor_metrics,factor_quality,factor_momentum,factor_risk",
        alias="FACTOR_XT_CATEGORIES",
    )
    screen_ic_threshold: float = Field(default=0.03, alias="FACTOR_SCREEN_IC_THRESHOLD")
    screen_icir_threshold: float = Field(default=0.3, alias="FACTOR_SCREEN_ICIR_THRESHOLD")
    screen_ic_positive_ratio: float = Field(default=0.55, alias="FACTOR_SCREEN_IC_POSITIVE_RATIO")
    screen_corr_threshold: float = Field(default=0.7, alias="FACTOR_SCREEN_CORR_THRESHOLD")
    screen_decay_halflife_min: int = Field(default=20, alias="FACTOR_SCREEN_DECAY_HALFLIFE_MIN")


# ================================================================
# 组合优化 (P1-05)
# ================================================================

class PortfolioConfig(BaseSettings):
    model_config = _SHARED_CFG
    optimizer_method: str = Field(default="caa", alias="PORTFOLIO_OPTIMIZER_METHOD")
    caa_target_vol: float = Field(default=0.10, alias="PORTFOLIO_CAA_TARGET_VOL")
    caa_cap: float = Field(default=0.25, alias="PORTFOLIO_CAA_CAP")
    caa_cash_assets: str = Field(
        default='["511010.SH","511260.SH"]',
        alias="PORTFOLIO_CAA_CASH_ASSETS",
    )
    max_industry_pct: float = Field(default=0.15, alias="PORTFOLIO_MAX_INDUSTRY_PCT")
    max_single_pct: float = Field(default=0.05, alias="PORTFOLIO_MAX_SINGLE_PCT")


# ================================================================
# 监控 (monitoring)
# ================================================================

class FactorMonitorConfig(BaseSettings):
    model_config = _SHARED_CFG
    ic_warning_threshold: float = Field(default=0.02, alias="FACTOR_MON_IC_WARNING")
    icir_threshold: float = Field(default=0.5, alias="FACTOR_MON_ICIR_WARNING")
    psi_warning: float = Field(default=0.2, alias="FACTOR_MON_PSI_WARNING")
    psi_critical: float = Field(default=0.4, alias="FACTOR_MON_PSI_CRITICAL")
    ic_window: int = Field(default=20, alias="FACTOR_MON_IC_WINDOW")


class ModelMonitorConfig(BaseSettings):
    model_config = _SHARED_CFG
    corr_warning: float = Field(default=0.1, alias="MODEL_MON_CORR_WARNING")
    psi_feature_warning: float = Field(default=0.2, alias="MODEL_MON_PSI_WARNING")
    check_window: int = Field(default=20, alias="MODEL_MON_CHECK_WINDOW")


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
        env_file=_ENV_FILES,
        env_file_encoding="utf-8",
    )
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    database: DatabaseConfig = DatabaseConfig()
    qmt: QMTConfig = QMTConfig()
    download: DownloadConfig = DownloadConfig()
    datacollect: DatacollectConfig = DatacollectConfig()
    dataclean: DatacleanConfig = DatacleanConfig()
    api: APIConfig = APIConfig()
    webhook: WebhookConfig = WebhookConfig()

    data_quality: DataQualityConfig = DataQualityConfig()
    resilience: ResilienceConfig = ResilienceConfig()

    ml: MLConfig = MLConfig()
    backtest: BacktestConfig = BacktestConfig()
    trading: TradingConfig = TradingConfig()

    position_monitor: PositionMonitorConfig = PositionMonitorConfig()
    arbiter: ArbiterConfig = ArbiterConfig()
    sizer: SizerConfig = SizerConfig()
    trading_rules: TradingRulesConfig = TradingRulesConfig()
    signal_defaults: SignalDefaultsConfig = SignalDefaultsConfig()
    regime_gate: RegimeGateConfig = RegimeGateConfig()

    strat_momentum: MomentumStratConfig = MomentumStratConfig()
    strat_reversal: ReversalStratConfig = ReversalStratConfig()
    strat_industry_rotation: IndustryRotationStratConfig = IndustryRotationStratConfig()
    strat_moving_average: MovingAverageStratConfig = MovingAverageStratConfig()
    strat_grid_trading: GridTradingStratConfig = GridTradingStratConfig()
    strat_cb_dual_low: CBDualLowStratConfig = CBDualLowStratConfig()
    strat_low_vol_dividend: LowVolDividendStratConfig = LowVolDividendStratConfig()
    sentiment: SentimentConfig = SentimentConfig()
    factor_monitor: FactorMonitorConfig = FactorMonitorConfig()
    model_monitor: ModelMonitorConfig = ModelMonitorConfig()
    strat_scoring: ScoringStratConfig = ScoringStratConfig()
    strat_ml: MLStratConfig = MLStratConfig()

    etf_rotation: EtfRotationConfig = EtfRotationConfig()
    factor_pipeline: FactorPipelineConfig = FactorPipelineConfig()
    portfolio: PortfolioConfig = PortfolioConfig()


settings = Settings()
