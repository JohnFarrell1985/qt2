# E2E 端到端测试设计文档

> 最后更新: 2026-04-12
>
> 3 个子目录 | 31 个文件 | ~75 个测试用例
>
> 目标: 验证 A 股量化因子迭代平台各模块的跨层数据流正确性

---

## 一、背景与目标

### 1.1 现状

- 已有 **35 个单元测试文件**, 覆盖各模块的独立逻辑
- 单元测试通过 mock 隔离所有外部依赖 (DB、QMT、Scheduler)
- **零 E2E 测试** — 无法验证模块间的数据流是否正确串联

### 1.2 E2E 测试目标

| 目标 | 说明 |
|------|------|
| **跨模块数据流** | 验证 API → 策略引擎 → 回测 → ML → 交易 的完整链路 |
| **数据一致性** | DB 写入的数据能被下游模块正确消费 |
| **业务逻辑正确性** | T+1 约束、止损止盈、涨跌停过滤等 A 股规则在端到端场景下正确生效 |
| **错误处理** | 异常输入返回结构化错误, 不产生 500 |
| **回归保护** | 后续代码修改不会破坏已有的跨模块行为 |

### 1.3 不在 E2E 范围

- 性能/压力测试 (单独设计)
- UI/前端测试 (无前端)

> **注**: QMT 和真实数据源的 E2E 测试已在 `qmt/` 和 `datacollect/` 子目录实现。
> QMT 需要终端已登录，用 `-m qmt` 标记；数据源测试使用真实 API 但限制为轻量级调用。

---

## 二、架构设计

### 2.1 目录结构

```
tests/e2e/
├── __init__.py
├── TODO-E2E.md                       ← 本文档
├── conftest.py                       ← 共享 fixtures: DB 隔离 (e2e_test schema)、TestClient、数据种子
├── fixtures/
│   ├── __init__.py
│   ├── seed_market_data.py           ← 合成行情数据工厂 (Stock, StockDaily, TradingDate)
│   └── seed_factor_data.py           ← 合成因子数据工厂 (FactorMeta, FactorValue)
│
├── api/                              ← API E2E (合成数据, 无外部依赖)
│   ├── __init__.py
│   ├── test_strategy_pipeline.py     ← E2E-01: 策略执行全链路
│   ├── test_backtest_pipeline.py     ← E2E-02: 回测全链路
│   ├── test_ml_pipeline.py           ← E2E-03: ML 训练→预测全链路
│   ├── test_data_query.py            ← E2E-04: 数据查询链路
│   ├── test_data_extended.py         ← 数据扩展测试
│   ├── test_strategy_extended.py     ← 策略扩展测试
│   ├── test_sentiment.py             ← 情绪引擎测试
│   └── test_system_health.py         ← E2E-05: 系统健康与容错
│
├── datacollect/                      ← 数据采集 E2E (真实数据源, 120s硬超时)
│   ├── __init__.py
│   ├── conftest.py                   ← datacollect_e2e schema 隔离 + session fixtures
│   ├── test_source_health.py         ← 数据源连通性检测 (baostock/akshare/tushare/adata)
│   ├── test_stock_list.py            ← 股票列表采集落盘
│   ├── test_daily_kline.py           ← 日线 K 线采集落盘
│   ├── test_index_data.py            ← 指数数据采集落盘
│   ├── test_financial.py             ← 财务报表/指标采集落盘
│   ├── test_etf_sector.py            ← ETF + 板块数据采集落盘
│   └── test_dispatcher.py            ← FallbackDispatcher 降级链逻辑
│
└── qmt/                              ← QMT 终端 E2E (需 QMT 已登录)
    ├── __init__.py
    ├── test_qmt_connection.py        ← QMT 连接测试
    ├── test_qmt_market.py            ← QMT 行情数据
    ├── test_qmt_sector.py            ← QMT 板块数据
    ├── test_qmt_financial.py         ← QMT 财务数据
    ├── test_qmt_sync.py              ← QMT 数据同步
    ├── test_qmt_special.py           ← QMT 特殊场景
    └── test_qmt_trader.py            ← QMT 交易模块
```

### 2.2 数据流总览

```
                    ┌─────────────────────────────────────────────┐
                    │              FastAPI TestClient              │
                    └───────────────────┬─────────────────────────┘
                                        │ HTTP
         ┌──────────┬──────────┬────────┼────────┬──────────┐
         │          │          │        │        │          │
    E2E-01     E2E-02     E2E-03   E2E-04   E2E-05    (parallel)
   Strategy   Backtest     ML      Data     Health
   Pipeline   Pipeline   Pipeline  Query    Check
         │          │          │        │        │
         └──────────┴──────────┴────────┼────────┘
                                        │
                    ┌───────────────────▼─────────────────────────┐
                    │     PostgreSQL (e2e_test schema 隔离)        │
                    │     合成数据: 50 stocks × 252 trading days   │
                    └─────────────────────────────────────────────┘
```

---

## 三、数据库隔离策略

### 3.1 方案: PostgreSQL Schema 隔离

使用现有 PostgreSQL 实例 (`qt_quant` 数据库), 通过独立 schema 实现完全隔离:

```
qt_quant (数据库)
├── public          ← 生产数据 (不动)
└── e2e_test        ← E2E 测试专用 (每次运行前重建)
```

### 3.2 生命周期

| 阶段 | 操作 | scope |
|------|------|-------|
| **Session 启动** | `DROP SCHEMA IF EXISTS e2e_test CASCADE` → `CREATE SCHEMA e2e_test` → `Base.metadata.create_all()` | `scope="session"` |
| **种子数据** | 插入 50 stocks × 252 days + 5 factors | `scope="session"` |
| **每个测试** | `BEGIN` → `SAVEPOINT` → 测试执行 → `ROLLBACK TO SAVEPOINT` | `scope="function"` |
| **Session 结束** | `DROP SCHEMA e2e_test CASCADE` | `scope="session"` |

### 3.3 关键实现 (`conftest.py` 核心代码)

```python
import pytest
from contextlib import contextmanager
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from unittest.mock import patch

from src.common.config import settings
from src.common.db import Base

E2E_SCHEMA = "e2e_test"


@pytest.fixture(scope="session")
def db_engine():
    """连接现有 PostgreSQL, 创建隔离的 e2e_test schema"""
    engine = create_engine(
        settings.database.url,
        pool_size=3,
        max_overflow=5,
        pool_pre_ping=True,
    )
    # 清理 + 重建 schema
    with engine.connect() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {E2E_SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {E2E_SCHEMA}"))
        conn.commit()

    # 将所有 ORM 表建在 e2e_test schema 下
    original_schemas = {}
    for table_name, table in Base.metadata.tables.items():
        original_schemas[table_name] = table.schema
        table.schema = E2E_SCHEMA
    Base.metadata.create_all(bind=engine)

    yield engine

    # Teardown: 清理 schema, 恢复原始设置
    with engine.connect() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {E2E_SCHEMA} CASCADE"))
        conn.commit()
    for table_name, table in Base.metadata.tables.items():
        table.schema = original_schemas.get(table_name)
    engine.dispose()


@pytest.fixture(autouse=True)
def db_session(db_engine):
    """每个测试使用独立事务, ROLLBACK 保证隔离"""
    connection = db_engine.connect()
    connection.execute(text(f"SET search_path TO {E2E_SCHEMA}, public"))
    transaction = connection.begin()
    session = Session(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db_session):
    """FastAPI TestClient, 注入测试 DB session, mock scheduler/QMT"""
    @contextmanager
    def _override_session():
        yield db_session

    with patch("src.common.db.get_session", _override_session), \
         patch("src.api.main.init_database"), \
         patch("src.api.main.start_scheduler"), \
         patch("src.api.main.stop_scheduler"):
        from fastapi.testclient import TestClient
        from src.api.main import app
        with TestClient(app) as c:
            yield c
```

---

## 四、合成数据设计

### 4.1 股票池 (50 只)

| 代码范围 | 行为特征 | 测试用途 |
|----------|---------|---------|
| `000001.SZ` ~ `000010.SZ` | 稳定上涨 (+0.3%/日) | 动量策略应选中这些股票 |
| `000011.SZ` ~ `000020.SZ` | 稳定下跌 (-0.2%/日) | 止损逻辑应触发卖出 |
| `000021.SZ` ~ `000030.SZ` | 均值回归 (振荡 ±2%) | 反转策略目标 |
| `000031.SZ` ~ `000040.SZ` | 高波动 (随机游走, vol=3%) | 低波红利策略应排除 |
| `000041.SZ` ~ `000050.SZ` | 低波稳定 (+0.05%/日, vol=0.5%) | 红利策略目标 |

### 4.2 交易日历

- 252 个交易日: `2024-01-02` 至 `2024-12-31`
- 排除周末和 A 股法定节假日 (简化为排除周末即可)

### 4.3 行情数据 (`StockDaily`)

每只股票每天生成:
- `open`, `high`, `low`, `close`: 根据分组行为特征生成确定性价格序列
- `volume`: 100 万 ~ 500 万 (随机但确定性种子)
- `turnover`: 基于 volume × close 计算
- `pct_change`: (close - prev_close) / prev_close

关键设计:
- 使用固定随机种子 (`np.random.seed(42)`) 保证可复现
- `000001.SZ` 的 close 在 2024-12-31 应约为 `10 × (1.003)^252 ≈ 21.3` (初始价 10 元)

### 4.4 因子数据 (`FactorMeta` + `FactorValue`)

5 个因子:

| 因子名 | 计算方式 | 说明 |
|--------|---------|------|
| `mom_20` | 20 日收益率 | 动量因子 |
| `vol_20` | 20 日收益率标准差 | 波动率因子 |
| `rsi_14` | 14 日 RSI | 超买超卖 |
| `turnover_avg_20` | 20 日平均换手率 | 流动性因子 |
| `amplitude_20` | 20 日平均振幅 | 波动幅度 |

从合成价格数据直接计算, 保证因子与行情的一致性。

### 4.5 策略数据 (`Strategy` + `InstrumentPool`)

- 默认策略池包含 `momentum`, `reversal`, `low_vol_dividend` 三个 Tier 1 策略
- 默认标的池 `all_50` 包含全部 50 只股票

---

## 五、测试套件详细设计

### E2E-01: 策略执行全链路

**被测路径**: `POST /strategy/execute` → StrategyOrchestrator → PositionMonitor → SignalArbiter → PositionSizer → ActionItems

**前置条件**: 合成行情数据已入库, 策略已注册

| 用例编号 | 用例名称 | 输入 | 预期结果 | 验证点 |
|---------|---------|------|---------|--------|
| TC-01-01 | 空仓买入 | `holdings=[]`, `total_capital=1000000` | 返回 buy 信号 | `actions` 非空, 所有 `direction=="buy"`, `target_quantity` 是 100 的整数倍 |
| TC-01-02 | 止损触发 | 持仓 `000011.SZ` (下跌股), `profit_pct=-9.0` | 返回 sell 信号 | `actions` 包含 `000011.SZ` 的 sell, `reasons` 包含 "止损" |
| TC-01-03 | T+1 约束 | 持仓 `000001.SZ`, `buy_date=today`, `can_sell=False` | 不产生该股卖出 | `actions` 中无 `000001.SZ` 的 sell |
| TC-01-04 | 满仓限制 | 已持有 5 只 (max_holdings=5) | 无新买入 | `actions` 中无 `direction=="buy"` 的新股 |
| TC-01-05 | 多策略投票 | 同一股票被 2 个策略选中 | score 叠加 | 该股的 `score > 单策略 score` |
| TC-01-06 | 策略 CRUD | 先 POST 创建策略 → GET 列表 → POST 执行 | 全链路通过 | 创建返回 id, 列表包含新策略, 执行不报错 |

**关键断言**:
- 卖出信号优先于买入信号 (先卖后买)
- `target_quantity` 是 100 的整数倍 (A 股 100 股整手)
- T+1 当日买入不可当日卖出
- 响应结构: `{"summary": {...}, "actions": [...]}`

---

### E2E-02: 回测全链路

**被测路径**: `POST /api/backtest/run` → strategy_runner → data_loader → performance report

**前置条件**: 合成行情数据已入库 (供 `data_loader` 读取), 或 mock `data_loader`

| 用例编号 | 用例名称 | 输入 | 预期结果 | 验证点 |
|---------|---------|------|---------|--------|
| TC-02-01 | 简单回测 | `schedule_file` (JSON, 固定选股), `continuous=false` | 返回 equity_curve + trades | `equity_curve` 长度 > 0, 每笔 trade 有 buy/sell 价格 |
| TC-02-02 | 连续持仓回测 | `stock_pool="000001.SZ,000002.SZ"`, `continuous=true` | 持仓滚动 | trades 中有持仓天数 > 1 的记录 |
| TC-02-03 | 绩效指标合理 | 使用上涨股池 | Sharpe > 0, total_return > 0 | `performance.sharpe_ratio > 0`, `performance.total_return > 0` |
| TC-02-04 | 缺少参数 | 不传 `schedule_file` 也不传 `stock_pool` | HTTP 400 | `response.status_code == 400`, `detail` 包含错误说明 |
| TC-02-05 | 涨停跳过 | 构造涨幅 > 9.8% 的数据 | 该笔交易 skipped | trades 中有 `skipped=True, skip_reason` 包含 "涨停" |

**关键断言**:
- 回测结果包含 `equity_curve`, `trades`, `performance` 三个部分
- 绩效报告包含 `sharpe_ratio`, `max_drawdown`, `total_return`, `win_rate`
- 上涨股池回测的 `total_return > 0` (合成数据的基本正确性)

---

### E2E-03: ML 训练→预测全链路

**被测路径**: `POST /api/ml/train` → FactorDataset → LGBFactorModel → save; `POST /api/ml/predict` → load → signals

**前置条件**: 合成因子数据 + 行情数据已入库

| 用例编号 | 用例名称 | 输入 | 预期结果 | 验证点 |
|---------|---------|------|---------|--------|
| TC-03-01 | 模型训练 | 5 个因子, 50 只股票, 2024 全年 | 返回 metrics + model_path | `status=="success"`, `metrics` 包含 train/val 指标 |
| TC-03-02 | 模型预测 | 使用 TC-03-01 保存的 model_path | 返回 signals 列表 | `signals` 非空, 每个 signal 有 `code`, `score` |
| TC-03-03 | 训练→预测链 | 同一测试内先 train 再 predict | 全链路通过 | predict 使用 train 的输出 model_path |
| TC-03-04 | 空数据集 | 不存在的 stock_pool | HTTP 400 | `response.status_code == 400`, `detail` 包含 "数据集为空" |
| TC-03-05 | 模型路径不存在 | `model_path="nonexistent.pkl"` | HTTP 500 | `response.status_code == 500` |

**关键断言**:
- 训练返回 `feature_importance` (因子重要性排序)
- 预测的 `signals` 按 score 降序排列
- `top_n` 参数正确限制返回数量

---

### E2E-04: 数据查询链路

**被测路径**: `GET /api/data/*` 和 `GET /api/factors/*` 系列端点

**前置条件**: 合成数据已入库

| 用例编号 | 用例名称 | 输入 | 预期结果 | 验证点 |
|---------|---------|------|---------|--------|
| TC-04-01 | 股票列表 | `GET /api/data/stocks?limit=100` | 返回 50 只股票 | `total == 50`, 每项有 `code`, `name` |
| TC-04-02 | 日线行情 | `GET /api/data/stock/000001.SZ/daily?start=2024-01-02&end=2024-01-31` | 返回约 20 条 | 每条有 OHLCV 字段, `close > 0` |
| TC-04-03 | 因子列表 | `GET /api/factors` | 返回 5 个因子 | 包含 `mom_20`, `vol_20` 等 |
| TC-04-04 | 数据一致性 | 查询行情 → 用相同数据执行策略 | 策略使用的数据与查询一致 | 策略 execute 返回的股票代码在 stocks 列表中 |

**关键断言**:
- 分页参数 `limit`, `offset` 正确生效
- 查询结果的字段类型正确 (日期为字符串, 价格为浮点数)
- 交叉验证: 数据查询 API 返回的数据与策略执行消费的数据一致

---

### E2E-05: 系统健康与容错

**被测路径**: `GET /health`, 各端点错误处理, 并发安全

| 用例编号 | 用例名称 | 输入 | 预期结果 | 验证点 |
|---------|---------|------|---------|--------|
| TC-05-01 | 健康检查 (正常) | `GET /health` (DB 正常) | `{"status": "ok"}` | `database == "connected"` |
| TC-05-02 | 健康检查 (DB 异常) | mock `check_db_connection` 返回 False | `{"status": "degraded"}` | 不返回 500 |
| TC-05-03 | 无效 JSON | `POST /strategy/execute` body 为 `{invalid}` | HTTP 422 | 包含 `detail` 字段的验证错误 |
| TC-05-04 | 结构化错误 | 各主要 POST 端点传入无效类型 | 不返回 500 | 返回 400 或 422, body 含 `detail` |
| TC-05-05 | 并发安全 | 10 个并发 `POST /strategy/execute` | 全部成功 | 无死锁, 无 500 错误 |

**关键断言**:
- 健康检查端点永远返回 200 (即使 DB 异常也返回 degraded, 不 crash)
- FastAPI 的 Pydantic 验证在 422 响应中提供字段级错误信息
- 并发测试使用 `concurrent.futures.ThreadPoolExecutor`

---

## 六、测试数据工厂

### 6.1 `seed_market_data.py`

```python
def create_stocks(session, count=50) -> list[Stock]:
    """创建 50 只测试股票"""
    ...

def create_trading_dates(session, year=2024) -> list[TradingDate]:
    """创建 2024 年 252 个交易日"""
    ...

def create_stock_daily(session, stocks, trading_dates) -> list[StockDaily]:
    """根据分组行为特征生成确定性价格序列
    - 使用 np.random.seed(42) 保证可复现
    - 上涨组/下跌组/振荡组/高波动组/低波动组
    """
    ...
```

### 6.2 `seed_factor_data.py`

```python
def create_factor_meta(session) -> list[FactorMeta]:
    """创建 5 个标准因子定义"""
    ...

def create_factor_values(session, stocks, trading_dates, daily_data) -> list[FactorValue]:
    """从合成价格数据计算因子值并入库
    - mom_20: 20 日收益率
    - vol_20: 20 日波动率
    - rsi_14: 14 日 RSI
    - turnover_avg_20: 20 日平均换手率
    - amplitude_20: 20 日平均振幅
    """
    ...
```

### 6.3 `conftest.py` 中的 `seeded_db` fixture

```python
@pytest.fixture(scope="session")
def seeded_db(db_engine):
    """在 e2e_test schema 中插入全部合成数据 (session 级别, 只执行一次)"""
    SessionLocal = sessionmaker(bind=db_engine)
    session = SessionLocal()
    session.execute(text(f"SET search_path TO {E2E_SCHEMA}, public"))
    try:
        stocks = create_stocks(session)
        dates = create_trading_dates(session)
        daily = create_stock_daily(session, stocks, dates)
        factor_meta = create_factor_meta(session)
        factor_values = create_factor_values(session, stocks, dates, daily)
        session.commit()
        yield {
            "stocks": stocks,
            "dates": dates,
            "daily": daily,
            "factor_meta": factor_meta,
            "factor_values": factor_values,
        }
    finally:
        session.close()
```

---

## 七、Mock 策略

### 7.1 需要 Mock 的组件

| 组件 | 原因 | Mock 方式 |
|------|------|----------|
| `init_database` | 避免重复建表 / 操作 public schema | `patch("src.api.main.init_database")` |
| `start_scheduler` / `stop_scheduler` | CI 中不需要定时任务 | `patch("src.api.main.start_scheduler")` |
| `xtquant` / `xtdata` | QMT SDK 在 CI 不可用 | `patch` 所有 `src.data.qmt_client` 调用 |
| `data_loader` (部分) | 回测 E2E-02 中 mock 行情读取 | `patch("src.backtest.data_loader.get_open_price_exact")` |

### 7.2 不 Mock 的组件 (真实执行)

| 组件 | 原因 |
|------|------|
| PostgreSQL | 使用真实数据库, e2e_test schema 隔离 |
| 策略引擎 | 测试真实策略逻辑 |
| SignalArbiter | 测试真实信号仲裁 |
| PositionMonitor | 测试真实持仓监控 |
| PositionSizer | 测试真实仓位分配 |
| LightGBM 训练/预测 | 测试真实 ML 管线 |
| PerformanceAnalyzer | 测试真实绩效计算 |

---

## 八、运行方式

### 8.1 本地运行

```bash
# ── 按模块运行 (推荐) ──
uv run pytest tests/e2e/api/ -v --tb=short             # API E2E (合成数据)
uv run pytest tests/e2e/datacollect/ -v --timeout=120   # 数据采集 E2E (真实数据源)
uv run pytest tests/e2e/qmt/ -v -m qmt                  # QMT E2E (需 QMT 终端)

# ── 全量运行 ──
uv run pytest tests/e2e/ -v -m "not qmt" --tb=short    # 全部 (排除 QMT)
uv run pytest tests/e2e/ -v --tb=short                  # 全部 (含 QMT)

# ── 运行单个套件 ──
uv run pytest tests/e2e/api/test_strategy_pipeline.py -v
uv run pytest tests/e2e/datacollect/test_daily_kline.py -v

# ── 运行单个用例 ──
uv run pytest tests/e2e/api/test_strategy_pipeline.py::TestStrategyExecution::test_empty_holdings_buy -v
```

### 8.2 前提条件

| 测试类型 | 前提条件 |
|---------|---------|
| API E2E (`tests/e2e/api/`) | PostgreSQL 可达, Python 依赖已安装 (`uv sync`) |
| 数据采集 E2E (`tests/e2e/datacollect/`) | PostgreSQL 可达 + 外网可达 (baostock/akshare) |
| QMT E2E (`tests/e2e/qmt/`) | PostgreSQL + QMT 终端已启动登录 |

**数据库隔离说明:**

| 子目录 | Schema | 说明 |
|--------|--------|------|
| `api/` | `e2e_test` | 合成数据, session 级创建/清理 |
| `datacollect/` | `datacollect_e2e` | 真实数据, 独立 conftest.py 管理 |
| `qmt/` | `qmt_e2e_test` | QMT 数据, 独立 schema |

**数据采集 E2E 设计原则:**

- **2 分钟硬超时**: 所有测试 `@pytest.mark.timeout(120)`, 数据源超时即判定不可用
- **轻量下载**: 每个测试仅取 1-2 只股票 / 5 个交易日数据, 不触发反爬限流
- **网络容错**: `requests.exceptions.ProxyError`/`ConnectionError`/`Timeout` 自动 skip
- **独立 schema**: 使用 `datacollect_e2e`, 测试后 ROLLBACK + DROP

### 8.3 CI 集成 (GitHub Actions)

```yaml
# .github/workflows/ci.yml 中新增 E2E job
e2e-test:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with: { python-version: '3.11' }
    - run: pip install -e ".[dev]"
    - run: pytest tests/e2e/api/ -v --tb=short         # API E2E
    - run: pytest tests/e2e/datacollect/ -v --timeout=120  # 数据采集 E2E
    # QMT E2E 不在 CI 运行 (需要 QMT 终端)
  env:
    DATABASE_URL: postgresql://game_agents:****@123.60.11.74:5432/qt_quant
```

### 8.4 预期耗时

| 子目录 | 测试数 | 预期耗时 |
|--------|--------|---------|
| `api/` — Schema 创建 + 建表 | — | ~2s |
| `api/` — 合成数据插入 (50×252 行) | — | ~5s |
| `api/` — E2E-01~05 全部用例 | 25 TC | ~40s |
| `datacollect/` — Schema 创建 | — | ~1s |
| `datacollect/` — 数据源连通性 | 4 TC | ~30s |
| `datacollect/` — 采集落盘 | 10 TC | ~60s |
| `datacollect/` — Dispatcher 逻辑 | 4 TC | ~10s |
| Schema 清理 | — | ~1s |
| **API + datacollect 总计** | **~43 TC** | **< 3 min** |
| `qmt/` (需终端) | 7 文件 | ~2 min |

---

## 九、落地计划

### Phase 1: 基础设施 (1 天) ✅ DONE

| 步骤 | 文件 | 内容 |
|------|------|------|
| 1.1 | `tests/e2e/__init__.py` | 空文件 (包标记) |
| 1.2 | `tests/e2e/conftest.py` | DB engine + e2e_test schema 隔离 + SAVEPOINT rollback + TestClient + seeded_db |
| 1.3 | `tests/e2e/fixtures/__init__.py` | 空文件 (包标记) |
| 1.4 | `tests/e2e/fixtures/seed_market_data.py` | 50 stocks + 252 dates + StockDaily 合成数据 |
| 1.5 | `tests/e2e/fixtures/seed_factor_data.py` | 5 FactorMeta + FactorValue 合成数据 |

### Phase 2: API 核心测试套件 (1 天) ✅ DONE

| 步骤 | 文件 | TC 数量 |
|------|------|--------|
| 2.1 | `api/test_strategy_pipeline.py` | 6 |
| 2.2 | `api/test_backtest_pipeline.py` | 5 |
| 2.3 | `api/test_ml_pipeline.py` | 5 |

### Phase 3: API 辅助测试套件 (0.5 天) ✅ DONE

| 步骤 | 文件 | TC 数量 |
|------|------|--------|
| 3.1 | `api/test_data_query.py` | 4 |
| 3.2 | `api/test_system_health.py` | 5 |

### Phase 4: 数据采集 E2E (1 天) ✅ DONE

| 步骤 | 文件 | TC 数量 | 说明 |
|------|------|--------|------|
| 4.1 | `datacollect/conftest.py` | — | datacollect_e2e schema 隔离 |
| 4.2 | `datacollect/test_source_health.py` | 4 | baostock/akshare/tushare/adata 连通性 |
| 4.3 | `datacollect/test_stock_list.py` | 2 | 股票列表采集落盘 |
| 4.4 | `datacollect/test_daily_kline.py` | 2 | 日线 K 线采集落盘 |
| 4.5 | `datacollect/test_index_data.py` | 2 | 指数数据采集落盘 |
| 4.6 | `datacollect/test_financial.py` | 2 | 财务报表/指标采集落盘 |
| 4.7 | `datacollect/test_etf_sector.py` | 3 | ETF + 板块数据落盘 |
| 4.8 | `datacollect/test_dispatcher.py` | 5 | FallbackDispatcher 降级链 (含 mock) |

### Phase 5: QMT 终端 E2E ✅ DONE

| 步骤 | 文件 | 说明 |
|------|------|------|
| 5.1 | `qmt/test_qmt_connection.py` | QMT 连接测试 |
| 5.2 | `qmt/test_qmt_market.py` | 行情数据 |
| 5.3 | `qmt/test_qmt_sector.py` | 板块数据 |
| 5.4 | `qmt/test_qmt_financial.py` | 财务数据 |
| 5.5 | `qmt/test_qmt_sync.py` | 数据同步 |
| 5.6 | `qmt/test_qmt_special.py` | 特殊场景 |
| 5.7 | `qmt/test_qmt_trader.py` | 交易模块 |

### Phase 6: 文档与 CI (0.5 天) ✅ DONE

| 步骤 | 内容 |
|------|------|
| 6.1 | 更新 `README.md` 测试章节 |
| 6.2 | 更新 `doc/08-用户手册.md` 测试章节 |
| 6.3 | 更新 `doc/12-数据采集模块.md` 测试章节 |
| 6.4 | 更新 `.github/workflows/ci.yml` 新增 E2E job |

---

## 十、文件清单与代码量

### 基础设施

| 文件 | 行数 | 用途 |
|------|------|------|
| `tests/e2e/__init__.py` | 0 | 包标记 |
| `tests/e2e/conftest.py` | ~180 | PostgreSQL e2e_test schema 隔离, SAVEPOINT, TestClient |
| `tests/e2e/fixtures/__init__.py` | 0 | 包标记 |
| `tests/e2e/fixtures/seed_market_data.py` | ~150 | Stock, TradingDate, StockDaily 合成工厂 |
| `tests/e2e/fixtures/seed_factor_data.py` | ~100 | FactorMeta, FactorValue 合成工厂 |

### api/ — API 端到端测试

| 文件 | 行数 | 用途 |
|------|------|------|
| `api/__init__.py` | 0 | 包标记 |
| `api/test_strategy_pipeline.py` | ~220 | E2E-01: 策略执行全链路 (6 TC) |
| `api/test_backtest_pipeline.py` | ~200 | E2E-02: 回测全链路 (5 TC) |
| `api/test_ml_pipeline.py` | ~180 | E2E-03: ML 训练→预测 (5 TC) |
| `api/test_data_query.py` | ~120 | E2E-04: 数据查询 (4 TC) |
| `api/test_data_extended.py` | ~100 | 数据扩展测试 |
| `api/test_strategy_extended.py` | ~100 | 策略扩展测试 |
| `api/test_sentiment.py` | ~80 | 情绪引擎测试 |
| `api/test_system_health.py` | ~120 | E2E-05: 系统健康与容错 (5 TC) |

### datacollect/ — 数据采集端到端测试

| 文件 | 行数 | 用途 |
|------|------|------|
| `datacollect/__init__.py` | 0 | 包标记 |
| `datacollect/conftest.py` | ~70 | datacollect_e2e schema 隔离 + session fixtures |
| `datacollect/test_source_health.py` | ~80 | 数据源连通性 (baostock/akshare/tushare/adata) |
| `datacollect/test_stock_list.py` | ~100 | 股票列表采集落盘 |
| `datacollect/test_daily_kline.py` | ~120 | 日线 K 线采集落盘 |
| `datacollect/test_index_data.py` | ~100 | 指数数据采集落盘 |
| `datacollect/test_financial.py` | ~100 | 财务报表/指标采集落盘 |
| `datacollect/test_etf_sector.py` | ~120 | ETF + 板块数据落盘 |
| `datacollect/test_dispatcher.py` | ~150 | FallbackDispatcher 降级链 (含 mock) |

### qmt/ — QMT 终端端到端测试

| 文件 | 行数 | 用途 |
|------|------|------|
| `qmt/__init__.py` | 0 | 包标记 |
| `qmt/test_qmt_connection.py` | ~80 | QMT 连接测试 |
| `qmt/test_qmt_market.py` | ~100 | 行情数据 |
| `qmt/test_qmt_sector.py` | ~80 | 板块数据 |
| `qmt/test_qmt_financial.py` | ~80 | 财务数据 |
| `qmt/test_qmt_sync.py` | ~100 | 数据同步 |
| `qmt/test_qmt_special.py` | ~80 | 特殊场景 |
| `qmt/test_qmt_trader.py` | ~100 | 交易模块 |

### 汇总

| 子目录 | 文件数 | 测试用例 | 代码量 |
|--------|--------|---------|--------|
| 基础设施 | 5 | — | ~430 行 |
| api/ | 9 | ~25 TC | ~1120 行 |
| datacollect/ | 9 | ~20 TC | ~840 行 |
| qmt/ | 8 | ~30 TC | ~620 行 |
| **合计** | **31** | **~75 TC** | **~3010 行** |
