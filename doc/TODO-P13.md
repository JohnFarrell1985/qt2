# P1.3: 工程化 (再次之 — 架构与可维护性)

> 最后更新: 2026-04-14
>
> 11 + 17 项 (含代码审查发现) | 预估工作量 ~9 + ~8 天
>
> 优先级说明: 模块完善/事件总线/自动注册/版本管理 — 提升代码质量和可维护性, 为后续扩展打基础
>
> 返回总览: [TODO.md](TODO.md) | 同级: ~~P1.1 系统风险~~ (✅ 已完成) | ~~P1.2 赚钱效应~~ (✅ 已完成)

---

## 代码审查发现 (2026-04-14)

> 三视角审查 (高级系统架构师 / 高级量化交易员 / 高级软件工程师) 发现以下问题。
> 按严重程度排序, CRITICAL 必须在实盘前修复。

### CRITICAL: 回测手续费计算参数错位

| 属性 | 内容 |
|------|------|
| **文件** | `src/backtest/orchestrator_backtester.py` L192, L249, L257 |
| **工作量** | 0.5 天 |

`calc_sell_fees` / `calc_buy_fees` 的调用参数与 `fees.py` 函数签名不匹配。`fees.py` 签名为 `(price, quantity, code, config)`, 但回测器传入 `(amount, config)`, 导致费用计算错误, **回测盈亏不可信**。需对齐为 `calc_sell_fees(sell_price, qty, code, self.fee_config)`, 与 `strategy_runner.py` / `engine.py` 的调用方式一致。

---

### CRITICAL: API 无认证/鉴权中间件

| 属性 | 内容 |
|------|------|
| **文件** | `src/api/main.py`, `src/api/deps.py` |
| **工作量** | 1 天 |

交易下单、策略执行、数据同步等敏感接口**无认证保护** (无 API Key / JWT / OAuth)。若 API 暴露至公网, 任何人可触发交易操作。建议至少实现 API Key 认证中间件。

---

### CRITICAL: 因子中性化使用当前行业/市值 (look-ahead bias)

| 属性 | 内容 |
|------|------|
| **文件** | `src/ml/dataset.py` L58-67, L169-186 |
| **工作量** | 1 天 |

`_load_industry_data` 从 `Stock` 表取**当前时点**行业归属和市值, 而非历史 Point-in-Time 数据。多年回测/训练中用了未来信息做中性化, 构成前视偏差。需改为按 `trade_date` 取历史行业/市值快照。

---

### HIGH: CORS 配置过于宽松

| 属性 | 内容 |
|------|------|
| **文件** | `src/api/main.py` L71-76 |
| **工作量** | 0.5 天 |

`allow_origins=["*"]` 且 `allow_credentials=True` 同时启用。生产环境应收紧为具体域名。

---

### HIGH: 迭代任务全局状态并发安全

| 属性 | 内容 |
|------|------|
| **文件** | `src/api/routers/iterate_router.py` L17-80 |
| **工作量** | 0.5 天 |

`_running_engine`, `_last_error`, `_is_running` 等全局可变状态在并发请求时存在竞态条件。虽有 `_running_lock` 但异常路径的读写未必全在锁内。

---

### HIGH: CI/CD 工作流缺失

| 属性 | 内容 |
|------|------|
| **文件** | `.github/` (缺失) |
| **工作量** | 1 天 |

仓库内无 `.github/workflows` 目录, 但 `README.md` 声称有 CI/CD。需补齐 GitHub Actions (pytest + ruff + coverage)。

---

### HIGH: 无依赖锁文件

| 属性 | 内容 |
|------|------|
| **文件** | `pyproject.toml` L12-60 |
| **工作量** | 0.5 天 |

生产依赖全部 `>=` 浮动版本, 无 `uv.lock`。构建不可复现, 存在供应链风险。需生成并提交锁文件。

---

### MEDIUM: data→strategy 分层违反

| 属性 | 内容 |
|------|------|
| **文件** | `src/data/universe_provider.py` L13-91 |
| **工作量** | 0.5 天 |

`universe_provider.py` 依赖 `strategy.trading_rules`, 违反分层 (data 不应依赖 strategy)。应将交易规则接口抽象到 common 层或通过依赖注入解耦。

---

### MEDIUM: get_session 只读路径无条件 commit

| 属性 | 内容 |
|------|------|
| **文件** | `src/common/db.py` L57-87 |
| **工作量** | 0.5 天 |

`get_session()` 在成功路径一律 `commit()`, 只读 API 也会触发无意义提交。建议区分读写 session, 或在只读路径使用 `flush` 而非 `commit`。

---

### MEDIUM: JSON 字符串配置类型安全弱

| 属性 | 内容 |
|------|------|
| **文件** | `src/common/config.py` L471-521 |
| **工作量** | 0.5 天 |

`EtfRotationConfig.risk_pool` 等为 JSON 字符串默认值, 运行时解析可能失败。`FactorPipelineConfig.xt_categories` 为逗号分隔字符串, 类型安全弱于 `list[str]` 字段。建议使用 Pydantic `validator` 或直接声明为 `list` 类型。

---

### MEDIUM: 密钥字段无启动时校验

| 属性 | 内容 |
|------|------|
| **文件** | `src/common/config.py` L339, L418-427 |
| **工作量** | 0.5 天 |

`TUSHARE_TOKEN`、`DEEPSEEK_API_KEY` 等默认为空字符串, 无启动时校验。失败延迟到首次 API 调用。建议在需要时提前 fail-fast。

---

### MEDIUM: TradeOrder 缺少复合索引

| 属性 | 内容 |
|------|------|
| **文件** | `src/data/models.py` L420-437 |
| **工作量** | 0.5 天 (Alembic 迁移) |

高频按 `(code, status, created_at)` 查询, 缺少复合索引可能导致全表扫描。

---

### MEDIUM: asyncio.get_event_loop() 弃用 API

| 属性 | 内容 |
|------|------|
| **文件** | `src/data/kline_bulk_sync.py` L474 |
| **工作量** | 0.5 天 |

Python 3.10+ 中 `asyncio.get_event_loop()` 已弃用, 应改用 `asyncio.get_running_loop()` 或 `asyncio.run()`。

---

### MEDIUM: bulk_writer 动态表名 SQL 拼接

| 属性 | 内容 |
|------|------|
| **文件** | `src/data/bulk_writer.py` L87-92 |
| **工作量** | 0.5 天 |

`table_name` 用于 `text(f"...{table_name}...")`, 虽当前来自 `model.__tablename__` 可控, 但缺乏显式校验。建议添加白名单或 `sql.identifier` 引用。

---

### MEDIUM: sentiment_bridge 跨模块边界

| 属性 | 内容 |
|------|------|
| **文件** | `src/datacollect/sentiment_bridge.py` L17-19 |
| **工作量** | 0.5 天 |

同时依赖 `data.models` 和 `sentiment.models`, 是跨 data + sentiment 的粘合层。严格分层应移至 `sentiment` 包或独立 `integration` 包。

---

### MEDIUM: Coverage fail_under = 99 门槛极高

| 属性 | 内容 |
|------|------|
| **文件** | `pyproject.toml` L99-101 |
| **工作量** | 0.5 天 |

99% 覆盖率要求极严, 易导致 CI 频繁失败。建议降至 85-90% 或按模块设定差异化目标。

---

### LOW: pyproject.toml dev 依赖重复声明

| 属性 | 内容 |
|------|------|
| **文件** | `pyproject.toml` L62-71 vs L103-107 |

`[project.optional-dependencies] dev` 与 `[dependency-groups] dev` 都声明了 pytest/ruff, 版本区间不一致 (pytest `>=8` vs `>=9`), 可能导致工具解析混淆。保留其一即可。

---

### P1-08 ~ P1-11: datacollect 完善

| # | 描述 | 文件 | 工作量 |
|---|------|------|--------|
| P1-08 | `CollectRouter` 自适应路由 | `src/datacollect/router.py` | 1.5 天 |
| P1-09 | `OpenClawReceiver` POST 推送 | `src/datacollect/collectors/openclaw_receiver.py` | 1 天 |
| P1-10 | `XtdataCollector` QMT 本地缓存 | `src/datacollect/collectors/xtdata_collector.py` | 1 天 |
| P1-11 | APScheduler 定时调度 | `src/datacollect/scheduler.py` | 1.5 天 |

**P1-08 为什么要做:**
不同数据源的可靠性不同，需要自适应降级链: akshare (免费优先) → HTTP 爬虫 → Playwright 浏览器 → Tavily API (付费兜底)。

**P1-11 技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| **APScheduler** | >=3.11 (stable) / 4.0α (实验) | ✅ 2026最新稳定3.11.2 (4.0仍为alpha,不建议生产用) | 轻量级进程内调度，支持 cron/interval/date 三种触发器 |

**为什么不用 Celery:** Celery 需要 Redis/RabbitMQ 消息中间件，架构过重。APScheduler 单进程内运行，适合日级低频采集 (4 个时段/天)。

**参考文档:**
- APScheduler 官方: [apscheduler.readthedocs.io](https://apscheduler.readthedocs.io/)
- [APScheduler vs Celery (2026)](https://leapcell.io/blog/scheduling-tasks-in-python-apscheduler-vs-celery-beat)

---

### P1-12 ~ P1-15: dataclean 完善

| # | 描述 | 文件 | 工作量 |
|---|------|------|--------|
| P1-12 | `StockEventExtraction` Schema + Cleaner | `src/dataclean/schemas/` + `cleaners/` | 1 天 |
| P1-13 | `RiskAlertExtraction` Schema | `src/dataclean/schemas/risk_alert.py` | 0.5 天 |
| P1-14 | Schema + Prompt 注册表 | `src/dataclean/registry.py` | 1 天 |
| P1-15 | 清洗日志 ORM (LLM token 追踪) | `src/dataclean/models.py` | 0.5 天 |

**为什么要做:** 情绪只是数据清洗的一种输出。个股事件 (利好/利空/重组/增减持)、风险预警 (监管处罚/质押爆仓) 等也需要结构化抽取。注册表机制使新增 Schema 只需 "注册" 而非改代码。

---

### P1-23: 轻量级事件总线 (从 P3-03 提升)

| 属性 | 内容 |
|------|------|
| **模块** | common |
| **文件** | 新增 `src/common/event_bus.py` |
| **工作量** | 3 天 |
| **原优先级** | P3-03, 因审查发现其为多模块协作的基础设施, 提升至 P1 |

**为什么提升到 P1:**
当前模块间通过函数调用串联 (采集→清洗→情绪→策略→交易)。P0 阶段将新增 4 个数据采集器、P1 阶段新增多个监控/优化模块, 如果不引入事件总线, 每次新增模块都要修改调用方代码, 违反开闭原则。事件总线是后续"数据采集完成后同时触发清洗+个股雷达+风险预警"等多播场景的前提。

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| **blinker** | >=1.9 | ✅ | Flask 内部使用的信号库, 轻量 |
| **PyPubSub** | >=4.0.7 | ✅ 2025.12 | 话题式发布订阅 |
| asyncio 自研 | Python 内置 | ✅ | 支持异步处理器 |

**落地方案:**
```python
from blinker import Namespace

events = Namespace()

# 定义事件
data_collected = events.signal("data_collected")
data_cleaned = events.signal("data_cleaned")
factor_computed = events.signal("factor_computed")
model_predicted = events.signal("model_predicted")
signal_generated = events.signal("signal_generated")

# 订阅 (解耦: 采集模块不知道谁在监听)
@data_collected.connect
def on_data_collected(sender, **kwargs):
    # 触发清洗
    cleaner.process(kwargs["data"])
    # 触发情绪更新
    sentiment_engine.update(kwargs["data"])
```

**参考文档:**
- Blinker: [blinker GitHub](https://github.com/pallets-eco/blinker)
- [Event Bus with asyncio in Python (2026)](https://oneuptime.com/blog/post/2026-01-25-event-bus-asyncio-python/view)

---

### P1-29: 策略自动发现与注册

| 属性 | 内容 |
|------|------|
| **模块** | strategy |
| **文件** | `src/strategy/__init__.py` (修改), `src/strategy/orchestrator.py` (修改) |
| **工作量** | 0.5 天 |
| **优先级** | **中 — 架构审查新增** |

**为什么要做:**

当前 `orchestrator.py` 中通过硬编码 import 注册所有策略:

```python
from src.strategy.rules.momentum import MomentumBreakout
from src.strategy.rules.mean_reversion import MeanReversion
# ... 逐个 import
```

每新增一个策略都要修改 `orchestrator.py`, 违反开闭原则 (OCP)。RD-Agent 和 Qlib 都使用注册表模式自动发现策略。

**落地方案:**

```python
# src/strategy/__init__.py
import importlib
import pkgutil

_STRATEGY_REGISTRY: dict[str, type] = {}

def register_strategy(name: str):
    """装饰器: 自动注册策略"""
    def decorator(cls):
        _STRATEGY_REGISTRY[name] = cls
        return cls
    return decorator

def discover_strategies():
    """自动扫描 src/strategy/rules/ 下所有 BaseStrategy 子类"""
    import src.strategy.rules as rules_pkg
    for _, module_name, _ in pkgutil.walk_packages(
        rules_pkg.__path__, prefix=rules_pkg.__name__ + "."
    ):
        importlib.import_module(module_name)
    return _STRATEGY_REGISTRY

# 策略侧使用:
@register_strategy("momentum_breakout")
class MomentumBreakout(BaseStrategy):
    ...
```

---

### P1-31: FactorPool 版本追溯

| 属性 | 内容 |
|------|------|
| **模块** | factor |
| **文件** | `src/factor/factor_pool.py`, Alembic 迁移 |
| **工作量** | 0.5 天 |
| **优先级** | **低 — 架构审查新增, 可在 P1-21/P1-30 之后** |

**为什么要做:**

因子的有效性会随时间变化。记录因子版本可以:
- 追溯 "某次回测用了哪个版本的因子计算逻辑"
- 对比不同版本因子的 IC/ICIR 衰减曲线
- 在因子迭代时保留历史基准

**落地方案:**

```python
# factor_pool.py 表扩展
class FactorMeta(Base):
    __tablename__ = "factor_meta"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    factor_name = Column(String(100), nullable=False)
    version = Column(String(20), nullable=False, default="1.0.0")
    category = Column(String(50))
    data_source = Column(String(50))
    description = Column(Text)
    ic_mean = Column(Float)
    icir = Column(Float)
    created_at = Column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("factor_name", "version"),)
```

---

### ~~P1-26: 可观测性 (结构化日志 + 告警)~~ → **已合并至 P4**

> **状态: 已合并**
>
> 原 P1-26 的 structlog 结构化日志和飞书告警已扩展为完整的全栈可观测性设计,
> 编号 P4-01~P4-07，涵盖 OpenTelemetry 链路追踪、Prometheus 指标、Loki 日志管线、
> Grafana 看板、Alertmanager 告警等。
>
> 详见: [TODO-P4.md](TODO-P4.md)

---
