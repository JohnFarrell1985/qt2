# QA 测试工程师 — 补充参考

> 精简版 (自动加载): `.cursor/agents/qa-engineer.md`
> 本文档是补充参考, 包含精简版中没有的详细信息, Agent 按需 `Read` 查阅

---

## 一、现有测试文件清单 (35 个)

```
tests/
├── test_api/
│   └── test_main.py                  # FastAPI TestClient, mock lifespan
├── test_backtest/
│   ├── test_fees.py                  # 手续费计算
│   └── test_performance.py           # 绩效指标 (Sharpe, MaxDD, WinRate)
├── test_common/
│   ├── test_config.py                # pydantic-settings 加载
│   ├── test_db.py                    # get_session, init_database
│   └── test_logger.py               # 日志配置
├── test_data/
│   ├── test_download_engine.py       # 批量下载引擎
│   └── test_qmt_client.py           # xtquant mock
├── test_factor/
│   ├── test_factor_analysis.py       # IC/ICIR
│   ├── test_factor_calc.py           # 因子计算
│   └── test_factor_preprocess.py     # MAD/中性化/Z-score
├── test_ml/
│   ├── test_auto_iterate.py          # 自动迭代
│   ├── test_dataset.py               # FactorDataset
│   ├── test_feature_selection.py     # 特征选择
│   ├── test_lgb_model.py            # LightGBM 训练/预测
│   ├── test_model_evaluation.py      # 模型评估
│   └── test_strategy_builder.py      # ML→策略
├── test_strategy/
│   ├── test_base_registry.py         # BaseStrategy + 注册
│   ├── test_instrument_pool.py       # 标的池
│   ├── test_macro_env.py            # 宏观环境
│   ├── test_orchestrator.py          # 主调度
│   ├── test_position_monitor.py      # 持仓监控 (止损/止盈)
│   ├── test_position_sizer.py        # 仓位管理
│   ├── test_rule_strategies.py       # 7 个规则策略
│   ├── test_scoring.py              # 打分策略
│   ├── test_signal_arbiter.py        # 信号仲裁
│   └── test_strategy_pool.py        # 策略池
├── test_trading/
│   ├── test_live_trading.py          # 实盘交易
│   ├── test_order_manager.py         # 订单管理
│   ├── test_paper_trading.py         # 模拟盘
│   ├── test_position_manager.py      # 持仓管理
│   ├── test_qmt_trader.py           # QMT mock
│   ├── test_risk_control.py          # 风控
│   └── test_trade_log.py            # 交易日志
└── e2e/
    └── TODO-E2E.md                   # E2E 测试设计文档 (25 TC)
```

---

## 二、E2E 测试设计概要

详见 `tests/e2e/TODO-E2E.md`

| 套件 | 文件 | 用例数 | 被测路径 |
|------|------|--------|---------|
| E2E-01 | `test_strategy_pipeline.py` | 6 | POST /strategy/execute 全链路 |
| E2E-02 | `test_backtest_pipeline.py` | 5 | POST /api/backtest/run 全链路 |
| E2E-03 | `test_ml_pipeline.py` | 5 | POST /api/ml/train → predict 链 |
| E2E-04 | `test_data_query.py` | 4 | GET /api/data/* 查询链 |
| E2E-05 | `test_system_health.py` | 5 | 健康检查 + 容错 + 并发 |

**数据库隔离**: PostgreSQL `e2e_test` schema, SAVEPOINT/ROLLBACK 每测试隔离

---

## 三、测试规范 (详细)

### 3.1 目录与命名
```
tests/
├── test_模块名/                       # 与 src/ 模块一一对应
│   ├── conftest.py                    # 模块级 fixtures
│   ├── test_文件名.py                  # 与 src/模块名/文件名.py 对应
│   └── ...
└── e2e/
    ├── conftest.py                    # E2E 共享 fixtures (DB, Client, Seed)
    ├── fixtures/
    │   ├── seed_market_data.py        # 行情数据工厂
    │   └── seed_factor_data.py        # 因子数据工厂
    └── test_套件名.py
```

### 3.2 测试用例结构
```python
class TestClassName:
    """被测类/模块名 单元测试"""

    def test_功能_正常输入_预期结果(self):
        """一句话描述测试意图"""
        # Arrange → Act → Assert

    def test_功能_空输入(self): ...
    def test_功能_极端值(self): ...

    def test_功能_无效输入_抛出异常(self):
        with pytest.raises(ValueError, match="预期错误消息"):
            target_function(invalid_input)

    def test_功能_T加1约束(self):
        """当日买入的持仓不可当日卖出"""
        ...
```

### 3.3 Mock 规范
```python
# 正确: 只 mock 外部依赖
@patch("src.data.qmt_client.xtdata")
def test_download(self, mock_xt):
    mock_xt.get_market_data.return_value = pd.DataFrame(...)

# 正确: mock 数据库 session
@patch("src.common.db.get_session")
def test_data_query(self, mock_session):
    mock_session.return_value.__enter__.return_value = mock_db

# 错误: mock 核心业务逻辑
@patch("src.strategy.orchestrator.StrategyOrchestrator.execute")
def test_execute(self, mock_exec):  # ← 不要这样做
    mock_exec.return_value = {"actions": []}
```

### 3.4 合成数据规范

E2E 测试使用确定性合成数据:

```python
import numpy as np
RANDOM_SEED = 42

def create_synthetic_prices(stock_code: str, days: int, trend: str) -> list[dict]:
    """生成确定性价格序列
    Args:
        trend: "up" (+0.3%/日) | "down" (-0.2%/日) | "oscillate" (±2%) | "volatile" | "stable"
    """
    np.random.seed(RANDOM_SEED + hash(stock_code) % 10000)
    ...
```

**数据分组** (50 只测试股票):

| 代码范围 | 行为 | 测试用途 |
|---------|------|---------|
| 000001-000010 | 稳定上涨 (+0.3%/日) | 动量策略应选中 |
| 000011-000020 | 稳定下跌 (-0.2%/日) | 止损应触发 |
| 000021-000030 | 均值回归 (振荡 ±2%) | 反转策略目标 |
| 000031-000040 | 高波动 (vol=3%) | 低波策略应排除 |
| 000041-000050 | 低波稳定 (+0.05%/日) | 红利策略目标 |

### 3.5 E2E 数据库隔离

```python
E2E_SCHEMA = "e2e_test"

@pytest.fixture(scope="session")
def db_engine():
    """Session 级: 创建隔离 schema, 建表, 完成后 DROP"""
    engine = create_engine(settings.database.url)
    with engine.connect() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {E2E_SCHEMA} CASCADE"))
        conn.execute(text(f"CREATE SCHEMA {E2E_SCHEMA}"))
        conn.commit()
    for table in Base.metadata.tables.values():
        table.schema = E2E_SCHEMA
    Base.metadata.create_all(bind=engine)
    yield engine
    with engine.connect() as conn:
        conn.execute(text(f"DROP SCHEMA IF EXISTS {E2E_SCHEMA} CASCADE"))
        conn.commit()
    for table in Base.metadata.tables.values():
        table.schema = None

@pytest.fixture(autouse=True)
def db_session(db_engine):
    """Function 级: SAVEPOINT/ROLLBACK 保证每个测试隔离"""
    connection = db_engine.connect()
    connection.execute(text(f"SET search_path TO {E2E_SCHEMA}, public"))
    transaction = connection.begin()
    session = Session(bind=connection)
    yield session
    session.close()
    transaction.rollback()
    connection.close()
```

---

## 四、A 股专项测试清单

### 4.1 交易规则
- [ ] T+1: 当日买入的股票 `can_sell=False`, 第二日才可卖出
- [ ] 涨停板: 涨幅 >= 9.8% (主板) / 19.8% (创业板/科创板) 时不可买入
- [ ] 跌停板: 跌幅 >= 9.8% / 19.8% 时不可卖出 (已持有的除外)
- [ ] 停牌: 停牌股票既不可买也不可卖
- [ ] 100 股整手: 买入数量必须是 100 的整数倍 (可转债除外, 10 张)
- [ ] ST / *ST: 涨跌幅限制 5%
- [ ] 北交所: 涨跌幅限制 30%

### 4.2 资金计算
- [ ] 手续费: 佣金 (万 2.5, 最低 5 元) + 印花税 (千 1, 仅卖出) + 过户费
- [ ] 可用资金: 买入后 T+1 才可用
- [ ] 整手限制: `target_quantity = (amount / price) // 100 * 100`
- [ ] 浮点精度: 金额计算使用 `round(x, 2)`, 比例计算使用 `round(x, 6)`

### 4.3 因子与 ML
- [ ] 因子计算: 不使用 trade_date 之后的数据 (前视偏差)
- [ ] 训练集/测试集: 时间序列不可随机拆分 (必须按时间先后)
- [ ] 预处理: MAD 去极值后, 值域应在 [-3σ, +3σ] 内
- [ ] IC 值: 范围应在 [-1, 1], 典型有效因子 IC 绝对值 > 0.02

### 4.4 回测特殊场景
- [ ] 首日建仓: 首个交易日 holdings 为空, 应正常产出 buy 信号
- [ ] 全部停牌: stock_pool 全部停牌时, 应返回空操作而非崩溃
- [ ] 数据缺失: 某日无行情数据时的降级处理
- [ ] 跨年回测: 跨年度时交易日历的连续性

---

## 五、监督清单

### 审查 Developer Agent 提交的单元测试
- [ ] 是否覆盖正常路径、边界条件、异常输入三类场景
- [ ] 是否有 A 股特殊规则测试 (T+1, 涨跌停, 整手)
- [ ] 断言是否具体 (不仅 `assert result is not None`, 而是检查具体值)
- [ ] Mock 范围是否合理 (只 mock 外部依赖, 不 mock 被测逻辑)
- [ ] 测试是否可独立运行 (不依赖执行顺序)
- [ ] 是否有 docstring 说明测试意图
- [ ] 测试数据是否确定性 (固定种子, 无随机)

### 审查 Architect Agent 的设计是否可测试
- [ ] 模块接口是否有明确的输入/输出定义 (方便构造测试数据)
- [ ] 是否存在全局状态污染 (单例、类变量) 影响测试隔离
- [ ] 外部依赖是否通过依赖注入 (方便 mock)
- [ ] 配置是否可在测试中覆盖 (不硬编码)
- [ ] 是否有异步/定时任务需要特殊测试策略

---

## 六、协作协议 (详细)

### 向 Developer Agent (02)
- **Bug 报告**: 附失败测试用例、预期行为、实际行为、严重度
- **测试用例审查请求**: 复杂业务逻辑的测试是否准确反映需求
- **Mock 数据格式确认**: 确认 mock 返回值与真实接口一致

### 向 Architect Agent (01)
- **可测试性报告**: 模块耦合导致难以测试, 建议改进设计
- **文档不一致**: 设计文档描述的行为与代码实际行为不符
- **测试覆盖报告**: 各模块的覆盖率和风险评估
- **质量门禁建议**: 建议新增或调整质量标准

### 接收来自 Developer Agent (02)
- **代码变更通知**: 影响范围, 需要新增/修改的测试
- **测试用例建议**: 开发者视角的边界条件和陷阱
- **Mock 指导**: 外部依赖的 mock 方式和数据格式

### 接收来自 Architect Agent (01)
- **测试范围要求**: 新功能的关键路径和必测场景
- **验收标准**: 功能验收的量化指标
- **优先级调整**: 测试任务的优先级变更

---

## 七、CI/CD 质量门禁设计

### GitHub Actions 管线 (P0-25)

```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install ruff
      - run: ruff check src/ tests/
      - run: ruff format --check src/ tests/

  unit-test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -e ".[dev]"
      - run: pytest tests/ --ignore=tests/e2e -v --cov=src --cov-report=xml
      - name: Coverage gate
        run: |
          coverage report --fail-under=80

  e2e-test:
    runs-on: ubuntu-latest
    needs: unit-test
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -e ".[dev]"
      - run: pytest tests/e2e/ -v --tb=short
    env:
      DATABASE_URL: ${{ secrets.E2E_DATABASE_URL }}
```

### 质量门禁标准

| 指标 | 阈值 | 说明 |
|------|------|------|
| 单元测试通过率 | 100% | 任何失败立即阻断 |
| 代码覆盖率 | >= 80% | 核心模块 (strategy/ml/backtest) 要求 >= 90% |
| ruff lint | 0 errors | 格式和 lint 零容忍 |
| E2E 测试通过率 | 100% | 全部 25 TC 通过 |
| 测试执行时间 | < 5 分钟 (单元) / < 1 分钟 (E2E) | 超时需要优化 |

---

## 八、参考资源

### 项目核心测试文件
| 文件 | 阅读优先级 | 用途 |
|------|-----------|------|
| `tests/e2e/TODO-E2E.md` | ★★★★★ | E2E 测试设计文档 (25 TC 详细定义) |
| `tests/test_api/test_main.py` | ★★★★★ | TestClient + mock lifespan 模式参考 |
| `tests/test_strategy/test_orchestrator.py` | ★★★★ | 复杂业务逻辑测试参考 |
| `tests/test_strategy/test_signal_arbiter.py` | ★★★★ | A 股规则测试参考 (T+1, 涨跌停) |
| `tests/test_ml/test_lgb_model.py` | ★★★★ | ML 管线测试参考 |
| `tests/test_factor/test_factor_preprocess.py` | ★★★ | 因子预处理测试参考 |
| `tests/test_trading/test_risk_control.py` | ★★★ | 风控规则测试参考 |
| `src/common/config.py` | ★★★ | 了解配置结构, 测试中如何覆盖 |
| `src/common/db.py` | ★★★ | 了解 DB session 模式, 如何 mock |
| `src/strategy/base.py` | ★★★ | 核心数据模型定义 |

### 设计文档 (测试依据)
| 文档 | 用途 |
|------|------|
| `doc/TODO-P0.md` | 待修复 Bug 详细描述 → 回归测试依据 |
| `doc/04-策略管理.md` | 10 策略行为定义 → 策略测试依据 |
| `doc/05-回测引擎.md` | 回测方法论 → 回测测试依据 |
| `doc/06-交易模块.md` | 交易流程 + 风控规则 → 交易测试依据 |
| `doc/07-API接口文档.md` | API 接口规范 → E2E 测试依据 |
