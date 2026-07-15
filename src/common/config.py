"""配置管理 — env/*.env.* + config/app.json + config/strategies/*.json + 环境变量

分文件 (env/ 目录):
  .env.db, .env.qmt, .env.datacollect, .env.trading
全局: config/app.json
选股策略 preset: config/strategies/{bull_launch,bear_rebound}.json
优先级: CLI --strategy / SELECTION_STRATEGY > app.json active_strategy > bull_launch
"""
import json
import os
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).parent.parent.parent

_ENV_DIR = PROJECT_ROOT / "env"
_dc_path = _ENV_DIR / ".env.datacollect"
_raw_env = [p for p in sorted(_ENV_DIR.glob(".env.*")) if p.name != ".env.example"]
if _dc_path in _raw_env:
    _raw_env = [p for p in _raw_env if p != _dc_path] + [_dc_path]
_ENV_FILES: tuple[str, ...] = tuple(str(p) for p in _raw_env)

_SHARED_CFG = SettingsConfigDict(
    populate_by_name=True,
    extra="ignore",
    env_file=_ENV_FILES,
    env_file_encoding="utf-8",
)


class DatabaseConfig(BaseSettings):
    model_config = _SHARED_CFG
    url: str = Field(default="postgresql://localhost:5432/qt_quant", alias="DATABASE_URL")
    pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    pool_timeout: int = Field(default=30, alias="DB_POOL_TIMEOUT")
    pool_recycle: int = Field(default=1800, alias="DB_POOL_RECYCLE")
    init_max_retries: int = Field(default=5, alias="DB_INIT_MAX_RETRIES")
    init_backoff_base: int = Field(default=2, alias="DB_INIT_BACKOFF_BASE_SEC")


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
    default_start_tick: str = Field(default="", alias="DL_START_TICK")


class SchedulerConfig(BaseSettings):
    model_config = _SHARED_CFG
    daily_sync_time: str = Field(default="17:00", alias="SCHEDULER_DAILY_SYNC_TIME")
    sync_days_back: int = Field(default=5, alias="SCHEDULER_DAILY_SYNC_DAYS_BACK")
    poll_interval_sec: int = Field(default=30, alias="SCHEDULER_POLL_INTERVAL_SEC")


class DataQualityConfig(BaseSettings):
    model_config = _SHARED_CFG
    enabled: bool = Field(default=True, alias="DATA_QUALITY_ENABLED")
    z_threshold: float = Field(default=10.0, alias="DATA_QUALITY_Z_THRESHOLD")
    max_pct_change: float = Field(default=22.0, alias="DATA_QUALITY_MAX_PCT_CHANGE")


class ResilienceConfig(BaseSettings):
    model_config = _SHARED_CFG
    circuit_breaker_threshold: int = Field(default=5, alias="RESILIENCE_CB_THRESHOLD")
    recovery_timeout_sec: float = Field(default=60.0, alias="RESILIENCE_RECOVERY_TIMEOUT")
    degradation_enabled: bool = Field(default=True, alias="RESILIENCE_DEGRADATION_ENABLED")


class BacktestConfig(BaseSettings):
    model_config = _SHARED_CFG
    initial_capital: float = Field(default=1_000_000.0, alias="BACKTEST_INITIAL_CAPITAL")
    max_position_pct: float = Field(default=0.20, alias="BACKTEST_MAX_POSITION_PCT")
    max_total_position_pct: float = Field(default=0.80, alias="BACKTEST_MAX_TOTAL_POSITION_PCT")
    max_holdings: int = Field(default=5, alias="BACKTEST_MAX_HOLDINGS")
    commission_rate: float = Field(default=0.000115, alias="FEE_COMMISSION_RATE")
    commission_min: float = Field(default=5.0, alias="FEE_COMMISSION_MIN")
    stamp_tax_rate: float = Field(default=0.0005, alias="FEE_STAMP_TAX_RATE")
    transfer_fee_rate: float = Field(default=0.00002, alias="FEE_TRANSFER_FEE_RATE")
    slippage_enabled: bool = Field(default=False, alias="SLIPPAGE_ENABLED")
    slippage_fixed_bps: float = Field(default=5.0, alias="SLIPPAGE_FIXED_BPS")


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


class TradingRulesConfig(BaseSettings):
    model_config = _SHARED_CFG
    cross_border_etf_prefixes: list[str] = Field(
        default_factory=list,
        alias="TRADING_RULES_CROSS_BORDER_ETF_PREFIXES",
    )


class DatacollectConfig(BaseSettings):
    model_config = _SHARED_CFG
    akshare_rate: float = Field(default=0.15, alias="DATACOLLECT_AKSHARE_RATE")
    akshare_burst: float = Field(default=3.0, alias="DATACOLLECT_AKSHARE_BURST")
    baostock_rate: float = Field(default=5.0, alias="DATACOLLECT_BAOSTOCK_RATE")
    baostock_burst: float = Field(default=10.0, alias="DATACOLLECT_BAOSTOCK_BURST")
    eastmoney_rate: float = Field(default=0.1, alias="DATACOLLECT_EASTMONEY_RATE")
    eastmoney_burst: float = Field(default=2.0, alias="DATACOLLECT_EASTMONEY_BURST")
    adata_rate: float = Field(default=0.5, alias="DATACOLLECT_ADATA_RATE")
    adata_burst: float = Field(default=5.0, alias="DATACOLLECT_ADATA_BURST")
    tushare_rate: float = Field(default=0.8, alias="DATACOLLECT_TUSHARE_RATE")
    tushare_burst: float = Field(default=5.0, alias="DATACOLLECT_TUSHARE_BURST")
    rsshub_base_url: str = Field(default="https://rsshub.app", alias="DATACOLLECT_RSSHUB_BASE_URL")
    exchange_info_skip_if_no_list_date_gap: bool = Field(
        default=True,
        alias="DATACOLLECT_EXCHANGE_INFO_SKIP_IF_NO_GAP",
    )
    tushare_enabled: bool = Field(default=False, alias="TUSHARE_ENABLED")
    tushare_token: str = Field(default="", alias="TUSHARE_TOKEN")
    max_retries: int = Field(default=3, alias="DATACOLLECT_MAX_RETRIES")
    retry_backoff_base: float = Field(default=10.0, alias="DATACOLLECT_BACKOFF_BASE")
    request_timeout: int = Field(default=30, alias="DATACOLLECT_REQUEST_TIMEOUT")
    impersonate: str = Field(default="chrome124", alias="DATACOLLECT_TLS_IMPERSONATE")
    proxy_url: str = Field(default="", alias="DATACOLLECT_PROXY_URL")
    global_concurrency: int = Field(default=50, alias="DATACOLLECT_GLOBAL_CONCURRENCY")
    write_buffer_size: int = Field(default=200, alias="DATACOLLECT_WRITE_BUFFER_SIZE")
    write_batch_size: int = Field(default=5000, alias="DATACOLLECT_WRITE_BATCH_SIZE")
    kline_non_etf_default_days_back: int = Field(default=365, alias="DATACOLLECT_KLINE_STOCK_DAYS_BACK")
    etf_daily_start_date: str = Field(default="20160101", alias="DATACOLLECT_ETF_DAILY_START_DATE")
    etf_daily_kline_source: str = Field(default="auto", alias="DATACOLLECT_ETF_DAILY_KLINE_SOURCE")
    etf_daily_stall_sec: float = Field(default=120.0, alias="DATACOLLECT_ETF_DAILY_STALL_SEC")
    etf_daily_resume: bool = Field(default=True, alias="DATACOLLECT_ETF_DAILY_RESUME")
    etf_daily_sina_only: bool = Field(default=False, alias="DATACOLLECT_ETF_DAILY_SINA_ONLY")
    etf_daily_use_progress: bool = Field(default=True, alias="DATACOLLECT_ETF_DAILY_USE_PROGRESS")
    etf_download_max_retries: int = Field(default=5, alias="DATACOLLECT_ETF_DOWNLOAD_MAX_RETRIES")


class MaFilterConfig(BaseSettings):
    model_config = _SHARED_CFG
    compute_periods: list[int] = Field(
        default=[5, 10, 15, 20, 30, 40, 50, 60],
        alias="SELECTION_MA_COMPUTE_PERIODS",
    )
    filter_periods: list[int] = Field(default=[5, 10, 20, 50], alias="SELECTION_MA_FILTER_PERIODS")
    require_bullish_order: bool = Field(default=True, alias="SELECTION_MA_BULLISH_ORDER")
    require_rising: bool = Field(default=True, alias="SELECTION_MA_RISING")
    require_spreading: bool = Field(default=True, alias="SELECTION_MA_SPREADING")
    prior_surge_lookback_days: int = Field(
        default=5,
        alias="SELECTION_PRIOR_SURGE_LOOKBACK_DAYS",
        description="向前回溯 N 个交易日检查是否出现过大涨 (非自然日)",
    )
    prior_surge_min_pct: float = Field(
        default=5.0,
        alias="SELECTION_PRIOR_SURGE_MIN_PCT",
        description="单日涨幅超过该值(%)视为大涨",
    )
    universe: str = Field(default="all_a", alias="SELECTION_UNIVERSE")
    universe_file: str = Field(default="", alias="SELECTION_UNIVERSE_FILE")
    exclude_st: bool = Field(default=True, alias="SELECTION_EXCLUDE_ST")
    min_avg_turnover_20d: float = Field(
        default=0.0,
        alias="SELECTION_MIN_AVG_TURNOVER_20D",
        description="20 日均换手率(%)硬筛下限; 0 表示不启用",
    )
    min_avg_amount_20d: float = Field(default=0.0, alias="SELECTION_MIN_AVG_AMOUNT_20D")
    exclude_limit_up: bool = Field(
        default=False,
        alias="SELECTION_EXCLUDE_LIMIT_UP",
        description="硬筛是否排除筛选日涨停收盘 (初筛默认保留供人工复核)",
    )
    prior_surge_use_board_threshold: bool = Field(
        default=True,
        alias="SELECTION_PRIOR_SURGE_USE_BOARD",
        description="prior_surge 阈值按板块涨跌幅动态调整",
    )
    max_candidates: int = Field(default=200, alias="SELECTION_MAX_CANDIDATES")
    anchor_ma_period: int = Field(default=5, alias="SELECTION_ANCHOR_MA_PERIOD")
    ma5_proximity_pct: float = Field(
        default=3.0,
        alias="SELECTION_MA5_PROXIMITY_PCT",
        description="收盘价相对锚点均线(默认5日)允许偏离上限(%)，上下对称",
    )
    require_volume_pullback: bool = Field(default=True, alias="SELECTION_REQUIRE_VOLUME_PULLBACK")
    require_ma5_proximity: bool = Field(
        default=True,
        alias="SELECTION_REQUIRE_MA5_PROXIMITY",
        description="硬性要求: 收盘价不得偏离锚点均线超过 ma5_proximity_pct (%)",
    )
    require_low_above_ma5: bool = Field(
        default=False,
        alias="SELECTION_REQUIRE_LOW_ABOVE_MA5",
        description="可选: 最低价不得跌破锚点均线 (与上下对称偏离二选一常用)",
    )
    max_gain_lookback_days: int = Field(
        default=10,
        alias="SELECTION_MAX_GAIN_LOOKBACK_DAYS",
        description="近 N 个交易日总涨幅统计窗口 (交易日)",
    )
    max_gain_total_pct: float = Field(
        default=30.0,
        alias="SELECTION_MAX_GAIN_TOTAL_PCT",
        description="近 N 个交易日累计涨幅上限 (%)",
    )
    max_gain_1m_lookback_days: int = Field(
        default=22,
        alias="SELECTION_MAX_GAIN_1M_LOOKBACK_DAYS",
        description="近一月(交易日)涨幅统计窗口",
    )
    max_gain_1m_pct: float = Field(
        default=30.0,
        alias="SELECTION_MAX_GAIN_1M_PCT",
        description="近一月(交易日)累计涨幅上限 (%)",
    )
    require_close_above_ma5: bool = Field(
        default=False,
        alias="SELECTION_REQUIRE_CLOSE_ABOVE_MA5",
        description="收盘价须在锚点均线(默认5日)上方",
    )
    volume_shrink_ratio: float = Field(
        default=1.0,
        alias="SELECTION_VOLUME_SHRINK_RATIO",
        description="筛选日成交量 / 上一交易日成交量须低于该比例 (1.0 即严格缩量)",
    )
    require_ma5_ma10_cross: bool = Field(
        default=False,
        alias="SELECTION_REQUIRE_MA5_MA10_CROSS",
        description="要求 MA5 上穿 MA10 或即将上穿",
    )
    ma5_ma10_imminent_pct: float = Field(
        default=1.5,
        alias="SELECTION_MA5_MA10_IMMINENT_PCT",
        description="即将上穿: MA5 低于 MA10 但差距不超过该比例(%)",
    )
    ma5_ma10_fresh_cross_days: int = Field(
        default=1,
        alias="SELECTION_MA5_MA10_FRESH_CROSS_DAYS",
        description="金叉以来 MA5 在 MA10 上方最多 N 个交易日(含金叉当日)",
    )
    ma5_ma10_allow_imminent: bool = Field(
        default=True,
        alias="SELECTION_MA5_MA10_ALLOW_IMMINENT",
        description="允许 MA5 在 MA10 下方收敛上行、即将金叉",
    )
    ma5_ma10_imminent_lookback: int = Field(
        default=5,
        alias="SELECTION_MA5_MA10_IMMINENT_LOOKBACK",
        description="即将金叉: 近 N 日不得曾 MA5 在 MA10 上方(排除死叉回落)",
    )
    ma5_ma10_imminent_only: bool = Field(
        default=False,
        alias="SELECTION_MA5_MA10_IMMINENT_ONLY",
        description="仅选尚未金叉、斜率预测即将上穿的标的",
    )
    ma5_ma10_max_days_to_cross: float = Field(
        default=1.0,
        alias="SELECTION_MA5_MA10_MAX_DAYS_TO_CROSS",
        description="斜率预测金叉须在 N 个交易日内",
    )
    ma5_ma10_slope_lookback: int = Field(
        default=1,
        alias="SELECTION_MA5_MA10_SLOPE_LOOKBACK",
        description="计算均线斜率的回溯交易日数",
    )
    ma5_ma10_require_next_day: bool = Field(
        default=True,
        alias="SELECTION_MA5_MA10_REQUIRE_NEXT_DAY",
        description="要求斜率预测下一交易日即金叉",
    )
    ma5_ma10_touch_pct: float = Field(
        default=0.3,
        alias="SELECTION_MA5_MA10_TOUCH_PCT",
        description="MA5 与 MA10 正好相交: 差距不超过该比例(%)",
    )
    require_ma5_ma10_above_long: bool = Field(
        default=False,
        alias="SELECTION_REQUIRE_MA5_MA10_ABOVE_LONG",
        description="MA5 与 MA10 均须在指定长均线上方 (见 ma5_ma10_above_groups)",
    )
    ma5_ma10_above_groups: list[list[int]] = Field(
        default_factory=list,
        alias="SELECTION_MA5_MA10_ABOVE_GROUPS",
        description="长均线条件: 组内 AND (MA5/10 均在各均线之上), 组间 OR。例 [[20,30],[40,50]]",
    )
    require_ma5_below_long: bool = Field(
        default=False,
        alias="SELECTION_REQUIRE_MA5_BELOW_LONG",
        description="MA5 须在指定长均线组下方 (见 ma5_below_groups)",
    )
    ma5_below_groups: list[list[int]] = Field(
        default_factory=list,
        alias="SELECTION_MA5_BELOW_GROUPS",
        description="长均线条件: 组内 AND (MA5 在各均线之下), 组间 OR。例 [[30]] 或 [[20,30],[40,50]]",
    )
    require_close_below_ma5: bool = Field(
        default=False,
        alias="SELECTION_REQUIRE_CLOSE_BELOW_MA5",
        description="收盘价须在锚点均线(默认5日)下方",
    )
    ma5_below_pct: float = Field(
        default=5.0,
        alias="SELECTION_MA5_BELOW_PCT",
        description="收盘价相对锚点均线向下至少偏离 (%)",
    )

    @field_validator("ma5_ma10_above_groups", "ma5_below_groups", mode="before")
    @classmethod
    def _parse_ma_groups(cls, v):
        if v is None or v == "":
            return []
        if isinstance(v, str):
            groups: list[list[int]] = []
            for part in v.split("|"):
                part = part.strip()
                if not part:
                    continue
                groups.append([int(x.strip()) for x in part.split(",") if x.strip()])
            return groups
        if isinstance(v, list):
            if not v:
                return []
            if isinstance(v[0], list):
                return v
            if isinstance(v[0], int):
                return [v]
        return v

    @field_validator("compute_periods", "filter_periods", mode="before")
    @classmethod
    def _parse_int_list(cls, v):
        if isinstance(v, str):
            return [int(x.strip()) for x in v.split(",") if x.strip()]
        return v


class RankConfig(BaseSettings):
    """启动突破初筛: 综合打分与分层 (硬筛通过后排序)."""

    model_config = _SHARED_CFG
    enabled: bool = Field(default=True, alias="SELECTION_RANK_ENABLED")
    tier_a_min: int = Field(default=70, alias="SELECTION_TIER_A_MIN")
    tier_b_min: int = Field(default=55, alias="SELECTION_TIER_B_MIN")
    export_top_n: int = Field(default=20, alias="SELECTION_EXPORT_TOP_N")
    weight_ma5_dist: float = Field(default=0.30, alias="SELECTION_WEIGHT_MA5_DIST")
    weight_vol_shrink: float = Field(default=0.25, alias="SELECTION_WEIGHT_VOL_SHRINK")
    weight_gain_10d: float = Field(default=0.20, alias="SELECTION_WEIGHT_GAIN_10D")
    weight_surge_recency: float = Field(default=0.15, alias="SELECTION_WEIGHT_SURGE_RECENCY")
    weight_liquidity: float = Field(default=0.10, alias="SELECTION_WEIGHT_LIQUIDITY")
    weight_ma5_ma10_cross: float = Field(
        default=0.0,
        alias="SELECTION_WEIGHT_MA5_MA10_CROSS",
        description="MA5/MA10 金叉新鲜度或即将上穿紧密度权重",
    )


class SelectionConfig(BaseSettings):
    model_config = _SHARED_CFG
    active_strategy: str = Field(default="bull_launch", alias="SELECTION_STRATEGY")
    ma_filter: MaFilterConfig = MaFilterConfig()
    rank: RankConfig = RankConfig()
    output_dir: str = Field(default="reports", alias="SELECTION_OUTPUT_DIR")


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
    scheduler: SchedulerConfig = SchedulerConfig()
    data_quality: DataQualityConfig = DataQualityConfig()
    resilience: ResilienceConfig = ResilienceConfig()
    backtest: BacktestConfig = BacktestConfig()
    trading: TradingConfig = TradingConfig()
    trading_rules: TradingRulesConfig = TradingRulesConfig()
    selection: SelectionConfig = SelectionConfig()


settings = Settings()

APP_JSON_PATH = PROJECT_ROOT / "config" / "app.json"
STRATEGIES_DIR = PROJECT_ROOT / "config" / "strategies"

_active_strategy_meta: dict[str, str] = {}


def load_json_config(json_path: str | Path) -> dict:
    """Load a JSON config file; missing file returns {}."""
    path = Path(json_path)
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def list_strategies() -> list[str]:
    if not STRATEGIES_DIR.is_dir():
        return []
    return sorted(p.stem for p in STRATEGIES_DIR.glob("*.json"))


def load_strategy(strategy_id: str) -> dict:
    path = STRATEGIES_DIR / f"{strategy_id}.json"
    data = load_json_config(path)
    if not data:
        available = ", ".join(list_strategies()) or "(none)"
        raise FileNotFoundError(f"Strategy not found: {strategy_id} (available: {available})")
    return data


def get_strategy_meta() -> dict[str, str]:
    return dict(_active_strategy_meta)


def _apply_section(obj, section: dict) -> None:
    for key, val in section.items():
        if hasattr(obj, key):
            setattr(obj, key, val)


def apply_app_config() -> None:
    """Apply config/app.json values to settings (non-secret defaults)."""
    app = load_json_config(APP_JSON_PATH)
    if not app:
        return

    data = app.get("data", {})
    if "akshare_rate" in data:
        settings.datacollect.akshare_rate = data["akshare_rate"]

    bt = app.get("backtest", {})
    if bt:
        slip = bt.get("slippage")
        for key, val in bt.items():
            if key == "slippage" or not hasattr(settings.backtest, key):
                continue
            setattr(settings.backtest, key, val)
        if slip:
            if "enabled" in slip:
                settings.backtest.slippage_enabled = slip["enabled"]
            if "fixed_bps" in slip:
                settings.backtest.slippage_fixed_bps = slip["fixed_bps"]

    sched = app.get("scheduler", {})
    if sched:
        _apply_section(settings.scheduler, sched)

    risk = app.get("risk", {})
    if risk:
        _apply_section(settings.trading.risk, risk)

    sel = app.get("selection", {})
    if sel:
        if "output_dir" in sel:
            settings.selection.output_dir = sel["output_dir"]
        if "active_strategy" in sel and not os.environ.get("SELECTION_STRATEGY"):
            settings.selection.active_strategy = sel["active_strategy"]


def _resolve_strategy_id(explicit: str | None = None) -> str:
    if explicit:
        return explicit
    env = os.environ.get("SELECTION_STRATEGY", "").strip()
    if env:
        return env
    if settings.selection.active_strategy:
        return settings.selection.active_strategy
    app = load_json_config(APP_JSON_PATH)
    return app.get("selection", {}).get("active_strategy", "bull_launch")


def apply_strategy(strategy_id: str | None = None) -> str:
    """Load strategy preset JSON into selection.ma_filter / selection.rank."""
    global _active_strategy_meta
    sid = _resolve_strategy_id(strategy_id)
    data = load_strategy(sid)
    settings.selection.active_strategy = sid

    ma = data.get("ma_filter", {})
    if ma:
        _apply_section(settings.selection.ma_filter, ma)
    rank = data.get("rank", {})
    if rank:
        _apply_section(settings.selection.rank, rank)

    _active_strategy_meta = {
        "id": data.get("id", sid),
        "label": data.get("label", sid),
        "description": data.get("description", ""),
    }
    return sid


apply_app_config()
apply_strategy()


def validate_required_keys(*required_configs: tuple[str, str]) -> list[str]:
    missing: list[str] = []
    for attr_path, label in required_configs:
        obj = settings
        for part in attr_path.split("."):
            obj = getattr(obj, part, "")
        if not obj:
            missing.append(label)
    return missing
