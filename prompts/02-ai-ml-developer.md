# AI/ML 量化开发工程师 — 补充参考

> 精简版 (自动加载): `.cursor/agents/ai-ml-developer.md`
> 本文档是补充参考, 包含精简版中没有的详细信息, Agent 按需 `Read` 查阅

---

## 一、完整代码结构 (77 个 Python 源文件)

```
src/
├── __init__.py
├── api/                              # FastAPI 应用
│   ├── main.py                       # app 入口, lifespan, router 注册
│   ├── scheduler.py                  # APScheduler 定时任务
│   └── routers/
│       ├── backtest_router.py        # POST /api/backtest/run
│       ├── data_router.py            # GET /api/data/stocks, /stock/{code}/daily 等
│       ├── factor_router.py          # GET /api/factors
│       ├── iterate_router.py         # POST /api/iterate/run
│       ├── ml_router.py              # POST /api/ml/train, /api/ml/predict
│       ├── strategy_router.py        # POST /strategy/execute, /strategy/signals
│       ├── trading_router.py         # 交易相关
│       └── webhook_router.py         # OpenClaw/飞书 webhook
├── backtest/
│   ├── engine.py                     # 日线回测引擎
│   ├── engine_minute.py              # 分钟线回测引擎
│   ├── strategy_runner.py            # 策略回测 Runner (run_strategy, run_continuous)
│   ├── data_loader.py                # 回测数据加载
│   ├── performance.py                # 绩效计算 (Sharpe, MaxDD, WinRate)
│   ├── fees.py                       # 手续费模型
│   ├── stock_picker.py               # 选股器
│   ├── cli.py / strategy_cli.py      # CLI 入口
│   └── prompts/prompt1.txt           # LLM 提示词模板
├── common/
│   ├── config.py                     # pydantic-settings Settings (单例 settings)
│   ├── db.py                         # SQLAlchemy engine + get_session() + init_database()
│   └── logger.py                     # 日志配置
├── data/
│   ├── models.py                     # ORM: Stock, StockDaily, StockMinute, MarketIndex 等
│   ├── qmt_client.py                 # xtquant/xtdata 封装
│   ├── download_engine.py            # 批量下载引擎 (断点续传, 流控)
│   ├── sync.py                       # 数据同步调度
│   ├── market_data.py                # 行情数据查询
│   ├── factor_data.py                # 因子数据查询
│   ├── financial_data.py             # 财务数据
│   └── cb_data.py                    # 可转债数据
├── factor/
│   ├── factor_calc.py                # 因子计算 (11 个量价因子)
│   ├── factor_preprocess.py          # MAD 去极值 + 行业/市值中性化 + Z-score
│   ├── factor_analysis.py            # IC/ICIR 分析 + 因子衰减检测
│   └── factor_pool.py                # 因子池管理
├── ml/
│   ├── lgb_model.py                  # LightGBM 封装 (train, predict, feature_importance)
│   ├── dataset.py                    # FactorDataset (特征矩阵构建)
│   ├── auto_iterate.py               # 自动因子-模型迭代 (Thompson Sampling Bandit)
│   ├── feature_selection.py          # 特征选择 (IC 筛选 + 相关性去重)
│   ├── model_evaluation.py           # 模型评估指标
│   └── strategy_builder.py           # 从 ML 模型生成策略信号
├── strategy/
│   ├── base.py                       # Signal, HoldingPosition, ActionItem, BaseStrategy
│   ├── orchestrator.py               # StrategyOrchestrator (主调度)
│   ├── position_monitor.py           # 持仓监控 (止损/止盈/追踪)
│   ├── signal_arbiter.py             # 信号仲裁 (去重/T+1/涨跌停/投票)
│   ├── position_sizer.py             # 仓位管理 (等权/ATR/Kelly)
│   ├── scoring.py                    # 多因子打分策略 (Tier 2)
│   ├── ml_strategy.py                # ML 策略包装 (Tier 3)
│   ├── instrument_pool.py            # 标的池管理
│   ├── macro_env.py                  # 宏观环境状态
│   ├── registry.py                   # 策略注册表
│   ├── strategy_pool.py              # 策略池
│   └── rules/                        # Tier 1 规则策略
│       ├── momentum.py               # 动量突破
│       ├── reversal.py               # 均值反转
│       ├── industry_rotation.py      # 行业轮动
│       ├── moving_average.py         # 均线突破
│       ├── grid_trading.py           # T+1 宽网格
│       ├── low_vol_dividend.py       # 低波红利
│       └── cb_dual_low.py            # 可转债双低
└── trading/
    ├── qmt_trader.py                 # QMT 下单接口
    ├── live_trading.py               # 实盘交易逻辑
    ├── paper_trading.py              # 模拟盘
    ├── order_manager.py              # 订单管理
    ├── position_manager.py           # 持仓管理
    ├── risk_control.py               # 多层风控
    └── trade_log.py                  # 交易日志
```

**测试结构** (35 个测试文件):
```
tests/
├── test_api/test_main.py
├── test_backtest/test_fees.py, test_performance.py
├── test_common/test_config.py, test_db.py, test_logger.py
├── test_data/test_download_engine.py, test_qmt_client.py
├── test_factor/test_factor_analysis.py, test_factor_calc.py, test_factor_preprocess.py
├── test_ml/test_auto_iterate.py, test_dataset.py, test_feature_selection.py,
│   test_lgb_model.py, test_model_evaluation.py, test_strategy_builder.py
├── test_strategy/test_base_registry.py, test_instrument_pool.py, test_macro_env.py,
│   test_orchestrator.py, test_position_monitor.py, test_position_sizer.py,
│   test_rule_strategies.py, test_scoring.py, test_signal_arbiter.py, test_strategy_pool.py
├── test_trading/test_live_trading.py, test_order_manager.py, test_paper_trading.py,
│   test_position_manager.py, test_qmt_trader.py, test_risk_control.py, test_trade_log.py
└── e2e/TODO-E2E.md
```

---

## 二、配置体系

`src/common/config.py` 使用 pydantic-settings, 从 `.env` 加载:

| 配置类 | 前缀 | 用途 |
|--------|------|------|
| DatabaseConfig | `DB_` | PostgreSQL 连接 |
| QMTConfig | `QMT_` | 迅投 SDK |
| DownloadConfig | `DL_` | 批量下载参数 |
| APIConfig | `API_` | FastAPI 服务 |
| WebhookConfig | `WEBHOOK_` | 飞书 webhook |
| MLConfig (含 MLIterateConfig) | `ML_` | LightGBM 超参 |
| BacktestConfig | `BT_` | 回测参数 |
| TradingConfig (含 RiskConfig) | `TRADE_` | 交易+风控 |
| PositionMonitorConfig | `PM_` | 止损/止盈 |
| ArbiterConfig | `ARB_` | 信号仲裁 |
| SizerConfig | `SIZER_` | 仓位管理 |
| SignalDefaultsConfig | `SIG_` | 信号默认值 |
| StratMomentumConfig 等 | `STRAT_*_` | 各策略独立配置 |

**完整技术栈**: Python 3.11+ | LightGBM >=4.6 | XGBoost >=3.0 | CatBoost >=1.2.10 | scikit-learn >=1.7 | FastAPI >=0.115 | SQLAlchemy >=2.0 | PostgreSQL 16 | pandas >=2.2 | numpy >=2.0 | torch >=2.8 | transformers >=5.0 | ONNX Runtime >=1.21 | peft >=0.18 | trl >=1.0 | skfolio >=0.15 | cvxpy >=1.5 | structlog >=25.1 | pandera >=0.23 | tenacity >=9.0 | APScheduler >=3.11 | Alembic >=1.15

---

## 三、代码规范 (详细)

### 3.1 通用规范
- `ruff` 格式化和检查 (配置在 `pyproject.toml`)
- 类型注解: 所有公开函数必须有参数和返回值类型注解
- Docstring: 公开类和函数使用 Google 风格 docstring
- 不写赘余注释, 注释仅用于解释非显而易见的设计意图

### 3.2 数据库操作
```python
# 正确: 使用 context manager
from src.common.db import get_session
with get_session() as session:
    stocks = session.query(Stock).filter(...).all()

# 错误: 手动管理 session
session = Session()
try: ...
finally: session.close()
```

### 3.3 配置读取
```python
# 正确: 通过 settings 单例
from src.common.config import settings
batch_size = settings.download.batch_size

# 错误: 硬编码
batch_size = 500
```

### 3.4 API 路由
```python
from fastapi import APIRouter, HTTPException
router = APIRouter(prefix="/api/模块名", tags=["模块中文名"])

@router.post("/动作", summary="简要说明")
def action_name(req: RequestModel):
    ...
    return {"status": "ok", "data": result}
```

### 3.5 策略实现
```python
from src.strategy.base import BaseStrategy, Signal
class NewStrategy(BaseStrategy):
    name = "strategy_name"
    def pick(self, trade_date, stock_pool, **kwargs) -> list[Signal]:
        ...
```

### 3.6 测试规范
```python
import pytest
from unittest.mock import patch, MagicMock

class TestModuleName:
    """模块名 单元测试"""
    def test_正常路径(self): ...
    def test_边界条件(self): ...
    def test_异常输入(self): ...

    @patch("src.data.qmt_client.xtdata")
    def test_外部依赖_mock(self, mock_xt):
        mock_xt.get_market_data.return_value = {...}
        ...
```

### 3.7 新增模块检查清单
- [ ] `__init__.py` 声明公开接口
- [ ] ORM 模型继承 `Base`, 有 `to_dict()` 方法
- [ ] 配置类继承 `BaseSettings`, 在 `Settings` 中聚合
- [ ] `.env` 新增参数有注释说明
- [ ] API router 在 `src/api/main.py` 中注册
- [ ] 对应 `tests/test_模块名/` 目录存在
- [ ] `pyproject.toml` 新增依赖 (如需要)

---

## 四、协作协议 (详细)

### 向 Architect Agent (01)
- **技术可行性反馈**: 设计方案在工程上不可行时, 给出具体原因和替代方案
- **性能瓶颈报告**: 实际运行中发现的瓶颈, 附 profiling 数据
- **依赖冲突报告**: 新依赖与现有技术栈的版本冲突
- **文档不一致报告**: 设计文档与实际代码行为不符

### 向 QA Agent (03)
- **代码变更通知**: 每次改动附带影响范围, 方便 QA 制定测试策略
- **测试用例建议**: 对复杂业务逻辑, 建议特定的测试场景和边界条件
- **Mock 指导**: 告知哪些外部依赖需要 mock, 提供 mock 数据格式

### 接收来自 Architect Agent (01)
- **设计方案**: 模块接口定义、数据模型、状态机
- **架构审查反馈**: 违反架构原则的代码需要修改
- **优先级调整**: TODO 任务优先级变更

### 接收来自 QA Agent (03)
- **Bug 报告**: 测试中发现的代码缺陷, 附复现步骤和测试用例
- **测试用例审查请求**: 复杂业务逻辑的测试是否合理
- **覆盖率报告**: 需要补充测试的模块

---

## 五、监督清单

### 审查 QA Agent 测试用例时
- [ ] 测试是否真正验证了业务逻辑, 而非仅测试 "代码能运行"
- [ ] Mock 对象的行为是否与真实对象一致 (特别是 QMT/数据库)
- [ ] 断言是否充分: 不仅检查返回码, 还检查具体数据内容
- [ ] 测试数据是否覆盖 A 股特殊场景: 涨跌停 (10%/20%)、ST、停牌、退市
- [ ] E2E 测试的合成数据是否与真实行情分布相近

### 审查 Architect Agent 设计时
- [ ] 接口定义在 Python 中是否可自然表达 (避免过度抽象)
- [ ] 数据模型是否匹配 PostgreSQL JSONB 的查询模式
- [ ] 配置参数数量是否合理 (避免过度参数化)
- [ ] 工作量估算是否现实 (结合代码复杂度)
- [ ] 外部依赖是否有纯 Python 替代 (减少 C 扩展编译风险)

---

## 六、参考资源

### 项目核心文件
| 文件 | 阅读优先级 | 用途 |
|------|-----------|------|
| `src/common/config.py` | ★★★★★ | 全局配置结构, 新增功能必读 |
| `src/common/db.py` | ★★★★★ | 数据库操作模式 |
| `src/strategy/base.py` | ★★★★★ | Signal/HoldingPosition/ActionItem/BaseStrategy |
| `src/strategy/orchestrator.py` | ★★★★ | 主调度逻辑, 理解完整执行链路 |
| `src/data/models.py` | ★★★★ | 所有 ORM 模型定义 |
| `src/ml/lgb_model.py` | ★★★★ | ML 训练核心 |
| `src/api/main.py` | ★★★ | 应用入口, router 注册, lifespan |
| `.env` | ★★★ | 所有配置参数和注释 |
| `pyproject.toml` | ★★★ | 依赖声明 + 工具配置 |
| `tests/test_api/test_main.py` | ★★★ | 测试模式参考 (TestClient + mock) |

### 设计文档 (实现时参考)
| 文档 | 对应模块 |
|------|---------|
| ~~`doc/TODO-P0.md`~~ | P0 已全部完成 |
| `doc/TODO-P1.md` | P1 重要任务细节 (ETF/因子/监控) |
| `doc/TODO-P2.md` | P2 增强功能 (蒸馏/RD-Agent) |
| `doc/12-数据采集模块.md` | `src/datacollect/` |
| `doc/13-数据清洗与LLM.md` | `src/dataclean/` |
| `doc/11-市场情绪引擎.md` | `src/sentiment/` |
| `doc/14-ETF资产配置轮动.md` | `src/strategy/etf_rotation/` |

### 代码模式速查
| 模式 | 参考文件 |
|------|---------|
| FastAPI router | `src/api/routers/strategy_router.py` |
| ORM 模型 | `src/data/models.py` |
| 策略实现 | `src/strategy/rules/momentum.py` |
| 单元测试 | `tests/test_strategy/test_orchestrator.py` |
| 配置类 | `src/common/config.py` (任意 *Config 类) |
| 数据查询 | `src/data/market_data.py` |
