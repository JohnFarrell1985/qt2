"""
Fin-R1 API Middleware Configuration
实时中间层配置
"""
from pydantic_settings import BaseSettings
from pydantic import Field, validator
from typing import Optional


class Settings(BaseSettings):
    """应用配置 - 带字段验证"""

    # 服务配置
    HOST: str = Field(default="0.0.0.0")
    PORT: int = Field(default=8012, ge=1, le=65535, description="服务端口号，范围1-65535")
    WORKERS: int = Field(default=1, ge=1, le=8, description="工作进程数，范围1-8")

    # vLLM后端
    VLLM_BASE_URL: str = Field(default="http://172.17.0.1:8010")
    VLLM_MODEL: str = Field(default="/models/Fin-R1")
    VLLM_TIMEOUT: int = Field(default=120, ge=10, le=300, description="vLLM超时时间(秒)，范围10-300")

    # 数据源配置
    ENABLE_REALTIME_API: bool = Field(default=True)
    ENABLE_DB_HISTORY: bool = Field(default=True)
    DATA_CACHE_TTL: int = Field(default=60, ge=10, le=300, description="数据缓存时间(秒)")
    MAX_DATA_STOCKS: int = Field(default=20, ge=1, le=50, description="最大处理股票数量")

    # 数据库连接（使用现有的 PostgreSQL 服务器）
    DATABASE_URL: str = Field(
        default="postgresql://game_agents:1234+asdf@123.60.11.74:5432/finr1_data"
    )

    # 日志
    LOG_LEVEL: str = Field(default="INFO", pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$")

    # 安全配置（可选）
    API_KEY: Optional[str] = Field(default=None, description="API访问密钥，留空则不验证")
    CORS_ORIGINS: str = Field(default="*", description="允许的CORS源，逗号分隔或*表示全部")

    @validator('CORS_ORIGINS')
    def parse_cors_origins(cls, v):
        """解析CORS源为列表"""
        if v == "*":
            return ["*"]
        return [origin.strip() for origin in v.split(',')]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
