"""FastAPI 主服务

启动后访问 /docs 查看 Swagger UI 交互式文档,
/redoc 查看 ReDoc 格式文档。
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.common.config import settings
from src.common.db import init_database, check_db_connection
from src.common.logger import get_logger
from src.api.routers import (
    data_router, factor_router, ml_router, backtest_router,
    trading_router, strategy_router, iterate_router, webhook_router,
)
from src.api.scheduler import start_scheduler, stop_scheduler

logger = get_logger(__name__)

TAG_METADATA = [
    {"name": "数据查询", "description": "股票列表、历史行情、基本面数据查询"},
    {"name": "因子分析", "description": "因子库管理、因子列表、分类查询"},
    {"name": "机器学习", "description": "LightGBM 模型训练、预测、因子重要性"},
    {"name": "回测", "description": "历史回测引擎 (日线/分钟线)、绩效报告"},
    {"name": "交易管理", "description": "QMT 模拟盘/实盘交易、持仓查询、委托管理"},
    {"name": "策略管理", "description": "策略池 CRUD、标的池管理、宏观环境状态、策略编排"},
    {"name": "自动迭代", "description": "ML 因子组合自动搜索优化、收敛分析、最佳因子权重"},
    {"name": "Webhook推送", "description": "OpenClaw/飞书事件推送: 风控告警、迭代完成、同步异常"},
    {"name": "系统", "description": "系统信息、健康检查"},
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("A股量化因子迭代平台启动中...")
    init_database()
    start_scheduler()
    logger.info("服务就绪 — 访问 /docs 查看 API 文档")
    yield
    stop_scheduler()
    logger.info("服务关闭")


app = FastAPI(
    title="A股量化因子迭代平台",
    description=(
        "## 系统概述\n\n"
        "基于 **LightGBM** 因子挖掘 + **迅投 QMT** 数据/交易的 A 股量化投资平台。\n\n"
        "### 核心功能\n\n"
        "- **数据层**: 对接迅投 QMT 行情/财务数据, 400+ 因子落库\n"
        "- **因子工程**: 因子预处理 (去极值/标准化/中性化)、IC/IR 分析\n"
        "- **机器学习**: LightGBM 因子选股模型, 自动迭代优化因子组合\n"
        "- **策略池**: 多策略管理, 标的池化, 宏观环境→策略映射\n"
        "- **回测引擎**: 日线/分钟线回测, 夏普/最大回撤/Calmar 等指标\n"
        "- **交易执行**: QMT 模拟盘 & 实盘, 风控 (止损/止盈/仓位限制)\n\n"
        "### 技术栈\n\n"
        "Python 3.10+ | FastAPI | PostgreSQL | LightGBM | xtquant SDK\n"
    ),
    version="3.0.0",
    lifespan=lifespan,
    openapi_tags=TAG_METADATA,
    docs_url="/docs",
    redoc_url="/redoc",
    license_info={"name": "MIT", "url": "https://opensource.org/licenses/MIT"},
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(data_router.router)
app.include_router(factor_router.router)
app.include_router(ml_router.router)
app.include_router(backtest_router.router)
app.include_router(trading_router.router)
app.include_router(strategy_router.router)
app.include_router(iterate_router.router)
app.include_router(webhook_router.router)


@app.get("/", tags=["系统"])
def root():
    """系统信息 — 返回平台名称、版本、可用模块列表"""
    return {
        "name": "A股量化因子迭代平台",
        "version": "3.0.0",
        "docs": "/docs",
        "modules": [
            "data", "factor", "ml", "backtest", "trading",
            "strategy", "instrument_pool", "macro_env", "auto_iterate",
        ],
    }


@app.get("/health", tags=["系统"])
def health():
    """健康检查 — 探测 DB 连接, 用于容器探针和监控"""
    db_ok = check_db_connection()
    status = "ok" if db_ok else "degraded"
    return {"status": status, "database": "connected" if db_ok else "unreachable"}
