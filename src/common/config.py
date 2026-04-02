"""配置管理 — 所有参数通过 .env + 环境变量注入

优先级: 系统环境变量 > 项目根目录 .env > 代码默认值
"""
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).parent.parent.parent

_SHARED_CFG = SettingsConfigDict(populate_by_name=True, extra="ignore")


class DatabaseConfig(BaseSettings):
    model_config = _SHARED_CFG
    url: str = Field(
        default="postgresql://game_agents:1234+asdf@123.60.11.74:5432/qt_quant",
        alias="DATABASE_URL",
    )
    pool_size: int = Field(default=5, alias="DB_POOL_SIZE")
    max_overflow: int = Field(default=10, alias="DB_MAX_OVERFLOW")
    pool_timeout: int = Field(default=30, alias="DB_POOL_TIMEOUT")
    pool_recycle: int = Field(default=1800, alias="DB_POOL_RECYCLE")


class QMTConfig(BaseSettings):
    model_config = _SHARED_CFG
    mini_qmt_path: str = Field(default="", alias="QMT_MINI_PATH")
    account_id: str = Field(default="", alias="QMT_ACCOUNT_ID")
    account_type: str = Field(default="STOCK", alias="QMT_ACCOUNT_TYPE")


class DownloadConfig(BaseSettings):
    """数据下载引擎参数

    社区实测: 每批 500 只, 批间暂停 2~3s 可避免 MiniQMT 过载和限流。
    """
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
    label_period: int = Field(default=5, alias="ML_LABEL_PERIOD")
    train_window: int = Field(default=252, alias="ML_TRAIN_WINDOW")
    retrain_step: int = Field(default=21, alias="ML_RETRAIN_STEP")
    iterate: MLIterateConfig = MLIterateConfig()


class BacktestConfig(BaseSettings):
    model_config = _SHARED_CFG
    initial_capital: float = Field(default=1_000_000.0, alias="BACKTEST_INITIAL_CAPITAL")
    max_position_pct: float = Field(default=0.30, alias="BACKTEST_MAX_POSITION_PCT")
    max_total_position_pct: float = Field(default=0.80, alias="BACKTEST_MAX_TOTAL_POSITION_PCT")
    max_holdings: int = Field(default=3, alias="BACKTEST_MAX_HOLDINGS")


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
    ml: MLConfig = MLConfig()
    backtest: BacktestConfig = BacktestConfig()
    trading: TradingConfig = TradingConfig()
    api: APIConfig = APIConfig()
    webhook: WebhookConfig = WebhookConfig()


settings = Settings()
