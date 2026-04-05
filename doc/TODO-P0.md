# P0: 紧急 / 基础 (Bug 修复 + 核心量化 + 基础设施)

> 最后更新: 2026-04-05
>
> 12 项 | 预估工作量 ~16.5 天
>
> **注意**: datacollect (P0-05~P0-11) 和 dataclean (P0-12~P0-19) 共 15 项已移至 [TODO-P01.md](TODO-P01.md), 爬虫攻防耗时较长, 优先修复现有代码 Bug。
>
> 返回总览: [TODO.md](TODO.md)

---

## 当前代码现状

**已实现** (`src/` 中已存在代码):

| 模块 | 路径 | 状态 |
|------|------|------|
| 策略引擎 | `src/strategy/` | 10 策略 + orchestrator + monitor + arbiter + sizer |
| 数据下载 | `src/data/` | QMT 数据下载引擎 + models |
| 因子工程 | `src/factor/` | 因子计算 / 预处理 / IC 分析 |
| 机器学习 | `src/ml/` | LGB + 自动迭代 + 评估 |
| 回测引擎 | `src/backtest/` | 日线 / 分钟线回测 + 绩效 |
| 交易模块 | `src/trading/` | QMT 交易 + 风控 + 模拟盘 |
| API 服务 | `src/api/` | FastAPI 路由 |
| 公共基础 | `src/common/` | 配置 / 数据库 / 日志 |

**仅有文档设计、代码未创建** (待办):

| 模块 | 路径 | 设计文档 |
|------|------|---------|
| 数据采集 | `src/datacollect/` | [doc/12-数据采集模块.md](12-数据采集模块.md) — **暂缓, 见 [P01](TODO-P01.md)** |
| 数据清洗 | `src/dataclean/` | [doc/13-数据清洗与LLM.md](13-数据清洗与LLM.md) — **暂缓, 见 [P01](TODO-P01.md)** |
| 情绪引擎 | `src/sentiment/` | [doc/11-市场情绪引擎.md](11-市场情绪引擎.md) |
| 个股雷达 | `src/stockradar/` | doc/13 引擎扩展章节 |
| 资金流向 | `src/fundflow/` | doc/13 引擎扩展章节 |
| 风险预警 | `src/riskmonitor/` | doc/13 引擎扩展章节 |
| 行业轮动 | `src/sectorwatch/` | doc/13 引擎扩展章节 |
| 宏观经济 | `src/macrotrack/` | doc/13 引擎扩展章节 |
| **ETF 轮动** | `src/strategy/etf_rotation/` | [TODO-P1.md P1-20](TODO-P1.md#p1-20-etf-全球资产轮动策略-tactical-asset-allocation) |

---

### P0-01: ATR PositionSizer 未接入

| 属性 | 内容 |
|------|------|
| **模块** | strategy |
| **文件** | `src/strategy/orchestrator.py`, `src/strategy/position_sizer.py` |
| **工作量** | 0.5 天 |

**为什么要做:**
当前 `PositionSizer` 支持 ATR-inverse 模式 (波动率倒数加权)，但 `StrategyOrchestrator` 调用 `allocate()` 时没有传入 `atr_map` 参数，导致 ATR 模式静默降级为等权分配。这是一个纯代码 Bug — 功能已实现但未接通。ATR-inverse 仓位管理是散户风控的核心手段: 波动率高的股票分配更少资金，降低单只爆仓风险。

**业界最佳实践:**
- **Van Tharp 的 ATR 仓位管理**: 经典公式 `position_size = risk_budget / (N × ATR)`，其中 N 通常取 2-3，确保每只股票的 "价格噪声" 对组合的冲击相等
- **Turtle Trading System**: 原始海龟交易法则使用 ATR (称为 "N") 来标准化仓位，确保不同波动率品种的 dollar risk 一致
- **Qlib** 框架内的 `TopkDropoutStrategy` 也支持波动率加权仓位

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| pandas | >=2.2 (兼容 3.0) | ✅ 2026最新3.0.2 (3.0需Python≥3.11) | ATR 计算 (rolling window) |
| numpy | >=2.0 | ✅ 2026最新2.4.4 | 向量化运算 |

**参考文档:**
- Van Tharp, *Trade Your Way to Financial Freedom*, Ch.12 Position Sizing
- Curtis Faith, *Way of the Turtle*, Ch.4 (ATR-based position sizing 原始规则)
- Investopedia: [Average True Range (ATR)](https://www.investopedia.com/terms/a/atr.asp)

**落地方案:**
1. 在 `orchestrator.py` 的 `_run_strategies()` 完成后，从 `stock_daily` 表拉取所有买入信号标的的近 20 日 OHLC 数据
2. 计算 ATR: `atr = talib.ATR(high, low, close, timeperiod=14)` 或 pandas 实现
3. 组装 `atr_map: dict[str, float]` 传入 `PositionSizer.allocate(atr_map=atr_map)`
4. 在 `.env` 中已有 `SIZER_ATR_LOOKBACK=14` 参数，直接使用

---

### P0-02: 行业中性化未启用

| 属性 | 内容 |
|------|------|
| **模块** | factor |
| **文件** | `src/ml/dataset.py`, `src/strategy/scoring.py`, `src/factor/factor_preprocess.py` |
| **工作量** | 1 天 |

**为什么要做:**
`factor_preprocess.py` 已经实现了 `neutralize()` 函数 (OLS 行业 + 市值中性化)，但 `FactorDataset.build()` 和 `MultiFactorScoringStrategy` 均未调用它。行业中性化是 A 股量化最重要的风控手段之一 — A 股行业轮动极为频繁 (煤飞色舞、新能源、AI 等板块月度级别切换)，如果不做行业中性化:
- 模型可能学到 "某行业上涨" 而非 "某因子选股有效"
- 回测业绩可能来自行业暴露 (beta) 而非选股能力 (alpha)
- 实盘中行业风格切换时策略会突然失效

**业界最佳实践:**
- **Barra CNE5/CNE6 模型**: 中信建投、国泰君安等券商量化团队的标配，10 大风格因子 + 行业因子做截面回归，残差即为纯 alpha
- **Qlib FactorAnalyzer**: 默认启用行业中性化，使用申万一级/二级行业分类
- **de Prado**: *Advances in Financial Machine Learning* Ch.8 强调特征预处理必须包含行业中性化

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| statsmodels | >=0.14 | ✅ 2026最新0.14.6 | OLS 回归做中性化 |
| pandas | >=2.2 (兼容 3.0) | ✅ 2026最新3.0.2 | 行业哑变量 + 截面操作 |
| 申万行业分类 | **2024版** | ✅ (2024版为最新) | 31 个一级行业, 二/三级大幅调整 (新增元宇宙/氢能/数字经济/合成生物学等) |

**参考文档:**
- Barra CNE5 Model: [xinyue6688/Barra-CNE5](https://github.com/xinyue6688/Barra-CNE5)
- Barra CNE6 + LightGBM: [finexsf/Barra-CNE6-LightGBM](https://github.com/finexsf/Barra-CNE6-LightGBM)
- 国君金工: [基于Barra CNE6的A股风险模型实践](https://finance.sina.com.cn/stock/stockzmt/2024-06-04/doc-inaxpkzq3963139.shtml)
- DolphinDB: [Barra 多因子风险模型实践](https://docs.dolphindb.com/zh/tutorials/barra_multi_factor_risk_model_0.html)

**落地方案:**
1. 在 `FactorDataset.build()` 中，调用 `preprocess_cross_section(df, neutralize_industry=True)`
2. 在 `MultiFactorScoringStrategy` 的因子打分前，按日期截面调用 `neutralize()`
3. 使用**申万 2024 版**一级行业代码 (31 个行业)，从 QMT 数据或 akshare `stock_board_industry_name_em()` 获取
4. 中性化公式: `alpha_pure = alpha_raw - β_industry × Industry_dummy - β_size × ln(MarketCap)`

---

### P0-03: FactorDataset 预处理断路

| 属性 | 内容 |
|------|------|
| **模块** | ml |
| **文件** | `src/ml/dataset.py` |
| **工作量** | 0.5 天 |

**为什么要做:**
`FactorDataset.build()` 代码中导入了 `preprocess_cross_section` 但从未调用。原始因子数据直接进入 LightGBM 训练，存在:
- **极端值污染**: 单只股票的异常因子值 (如 ST 股的 PE 为 -500) 会严重扭曲模型
- **尺度不一**: 市值因子范围 10^8~10^12，PE 范围 5~200，LGB 虽非距离度量模型，但极端值仍影响分裂点选择
- **IC 检验失真**: 未标准化的因子 IC 不可跨因子比较

**业界最佳实践:**
- **MAD 去极值 (Median Absolute Deviation)**: 比 3σ 法更稳健，不受极端值影响。公式: `clip to [median - 5×MAD, median + 5×MAD]`
- **Z-score 标准化**: 截面标准化使因子可比。Qlib 的 `CSZScoreNorm` 处理器是标配
- **de Prado**: 强调在 ML 前必须做因子预处理，否则 "garbage in, garbage out"

**技术选型:**

| 技术 | 版本 | 说明 |
|------|------|------|
| scipy.stats | >=1.15 | ✅ 2026最新1.17.1 | `median_abs_deviation()` |
| pandas | >=2.2 (兼容 3.0) | ✅ 2026最新3.0.2 | `groupby(date).transform()` 截面操作 |

**参考文档:**
- Marcos López de Prado, *Advances in Financial Machine Learning*, Ch.8
- Qlib 文档: [Data Processing](https://qlib.readthedocs.io/en/latest/component/data.html)
- 石川《因子投资：方法与实践》第3章

**落地方案:**
1. 在 `build()` 方法中，`pd.merge` 之后、`train_test_split` 之前插入:
   ```python
   df = preprocess_cross_section(df, method='mad', neutralize_industry=True)
   ```
2. 确认 `preprocess_cross_section` 对每个日期截面独立处理 (避免前视偏差)
3. **新增: IC 去重门控** (借鉴 RD-Agent): 新因子入库前，计算其与现有 SOTA 因子池的截面 Pearson 相关性，**max IC ≥ 0.99 的新因子丢弃** — 防止因子池膨胀/冗余:
   ```python
   def deduplicate_factors(sota_factors: pd.DataFrame, new_factors: pd.DataFrame,
                           threshold: float = 0.99) -> pd.DataFrame:
       """RD-Agent 式因子去重: 按日期截面计算新旧因子 IC, 丢弃高冗余因子"""
       ic_matrix = {}
       for date, group in pd.concat([sota_factors, new_factors], axis=1).groupby(level=0):
           corr = group[sota_factors.columns].corrwith(group[new_factors.columns])
           ic_matrix[date] = corr
       mean_ic = pd.DataFrame(ic_matrix).T.mean()  # 跨日期平均
       max_ic_per_new = mean_ic.unstack().max(axis=0)  # 每个新因子的最大相关性
       keep = max_ic_per_new[max_ic_per_new < threshold].index
       return new_factors[keep]
   ```

> **来源:** 微软 RD-Agent 0.8.0 (`rdagent/scenarios/qlib/developer/factor_runner.py`) 的 `deduplicate_new_factors` 方法

---

### P0-04: 回测与实盘管道不一致

| 属性 | 内容 |
|------|------|
| **模块** | backtest |
| **文件** | `src/backtest/` 新增 `orchestrator_backtester.py` |
| **工作量** | 5-7 天 (含涨跌停/停牌模拟) |

**为什么要做:**
这是系统中**最严重的结构性缺陷**。当前 `src/backtest/strategy_runner.py` 使用 `StockPicker` 抽象，而实盘使用 `StrategyOrchestrator` (包含 Monitor → Arbiter → Sizer 完整管道)。两套逻辑完全不同:
- 回测验证的不是实际会执行的策略
- PositionMonitor (止损/止盈/追踪止损) 从未被回测检验
- SignalArbiter (信号去重/冲突解决/T+1 约束) 逻辑不在回测中
- PositionSizer (仓位分配) 逻辑不在回测中
- **结果**: 回测收益率与实盘表现可能天差地别

**业界最佳实践:**
- **Microsoft Qlib**: 使用统一的 `Strategy → Executor → Simulator` 管道，回测和实盘共享同一套信号生成和执行逻辑。Qlib v0.9.7 (2025.08) 的 `backtest` 模块内置了 `NestedExecutor` 支持多级决策回测
- **Zipline/Backtrader**: 回测框架的核心设计原则就是 "write once, run in backtest and live"
- **QuantConnect LEAN**: C# 框架同样强调 `Algorithm` 类在回测和实盘中行为完全一致

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| 自研 OrchestratorBacktester | - | - | 复用现有 Orchestrator 管道 |
| pandas | >=2.0 | ✅ | 日历循环 + 持仓追踪 |
| sqlalchemy | >=2.0 | ✅ | 从 DB 读历史行情 |

**参考文档:**
- Microsoft Qlib 回测架构: [github.com/microsoft/qlib](https://github.com/microsoft/qlib) (39.8k⭐)
- Qlib Workflow 文档: [docs/component/workflow.rst](https://github.com/microsoft/qlib/blob/main/docs/component/workflow.rst)
- Zipline 设计理念: [github.com/quantopian/zipline](https://github.com/quantopian/zipline)

**落地方案:**
1. 新建 `src/backtest/orchestrator_backtester.py`
2. 核心类 `OrchestratorBacktester`:
   ```python
   class OrchestratorBacktester:
       def run(self, start_date, end_date, initial_capital):
           for trade_date in trading_calendar:
               # 1. PositionMonitor.scan(holdings) → sell_signals
               # 2. strategies[].generate(market_data, holdings) → buy_signals
               # 3. SignalArbiter.arbitrate(sell+buy, holdings) → actions
               # 4. PositionSizer.allocate(buy_actions) → sized_actions
               # 5. simulate_execution(actions, ohlc) → updated_holdings
               # 6. record_portfolio_value()
   ```
3. 使用 `stock_daily` 表的历史数据，按日历逐日模拟
4. 内置 T+1 约束: 当日买入的股票 `can_trade_date = T+1`
5. **涨跌停模拟** (A 股回测核心约束):
   - 涨停板 (`close == high` 且涨幅 ≥ 涨停阈值): 当日不可买入 (除非开板, 即 `high > low`)
   - 跌停板 (`close == low` 且跌幅 ≥ 跌停阈值): 当日不可卖出
   - 一字板 (`open == close == high == low`): 完全不可交易
   - 涨停阈值: 主板 10%, 科创板/创业板 20%, ST 5%
6. **停牌处理**: 停牌日 (`volume == 0`) 不可交易, 持仓市值按停牌前收盘价冻结
7. 保留 `strategy_runner.py` 作为快速单策略验证工具
8. 输出复用现有 `PerformanceAnalyzer`

> **A 股实盘教训**: 涨停买不进、跌停卖不出是回测-实盘差距最大来源之一。不处理此约束, "追涨"策略收益会被严重高估。

---

### P0-05 ~ P0-19: → 已移至 [TODO-P01.md](TODO-P01.md)

> **datacollect** (P0-05~P0-11, 7 项, ~5.5 天): SmartHttpClient / 令牌桶限流 / BaseCollector / AkshareCollector / 注册表 / 采集日志 / 模块初始化
>
> **dataclean** (P0-12~P0-19, 8 项, ~4 天): LLMClient / BaseCleaner / Schema / SentimentCleaner / RuleCleaner / Prompt 模板 / 模块初始化
>
> 爬虫攻防耗时较长, 优先修复现有代码 Bug 和搭建基础设施。

---

### P0-20 ~ P0-23: sentiment 情绪引擎核心

| # | 描述 | 文件 | 工作量 |
|---|------|------|--------|
| P0-20 | `SentimentDaily` + `SentimentIngestLog` ORM (JSONB) | `src/sentiment/models.py` | 1 天 |
| P0-21 | `price_volume.py` Layer 1 量价情绪 | `src/sentiment/price_volume.py` | 1.5 天 |
| P0-22 | `strategy_profiles.py` + JSON | `src/sentiment/strategy_profiles.py` | 1 天 |
| P0-23 | 情绪 API 端点 | `src/api/routers/sentiment_router.py` | 1 天 |

**为什么要做:**
情绪引擎是连接 "数据采集/清洗" 与 "策略执行" 的桥梁。它将多源情绪数据合成为宏观状态，驱动策略参数动态切换。Layer 1 量价情绪完全从已有行情数据计算，零成本且最稳定:
- 涨跌比 (A/D Ratio): 市场赚钱效应核心指标
- 波动率 (5/10/20 日): 恐慌/麻木判断
- 创 60 日新高/新低数: 趋势强度
- 北向资金净流入 (从 akshare): 聪明钱方向

**参考文档:** 详见 [doc/11-市场情绪引擎.md](11-市场情绪引擎.md)

**PostgreSQL JSONB 设计要点:**
- `SentimentDaily.indicators` 字段使用 JSONB 存储灵活的指标集
- 使用 `jsonb_path_ops` GIN 索引 (比默认 GIN 小 30-40%)
- 对高频查询字段创建 Expression Index: `CREATE INDEX ON sentiment_daily ((indicators->'ad_ratio'))`
- 参考: [PostgreSQL JSONB Indexing (2025)](https://www.rickychilcott.com/2025/09/22/postgresql-indexing-strategies-for-jsonb-columns/)

---

### P0-24: 幸存者偏差 / Point-in-Time 数据管理 (从 P2-04 提升)

| 属性 | 内容 |
|------|------|
| **模块** | data |
| **文件** | 新增 `src/data/universe_manager.py` |
| **工作量** | 3 天 |
| **原优先级** | P2-04, 因审查发现其为基础性依赖, 提升至 P0 |

**为什么提升到 P0:**
幸存者偏差直接影响**所有策略**的回测准确性。不处理就做后续 ML/策略优化, 等于在错误数据上调优, 所有结论不可信:
- **年化收益虚高 1.5-4.5%** (累积 35-45%)
- **Sharpe 虚高 20-30%**
- **最大回撤低估 15-25%**
- P0-04 (回测管道) 依赖此模块提供正确的"历史可交易股票列表"

原因: 只用当前存活股票回测, 遗漏了退市 (往往暴跌 80%+) 和被剔除指数成分的股票。

**业界最佳实践:**
- **SCD Type 2 (缓慢变化维度)**: 记录每只股票的生命周期 (`start_date`, `end_date`, `status_at_end`)
- **Point-in-Time 查询**: "T 日哪些股票是可交易的？" 而非 "今天的股票列表回溯到过去"
- **财务数据用 `announce_date`**: 而非 `report_date`, 避免使用尚未公布的财报数据

**落地方案:**
```python
class UniverseManager:
    def get_tradable(self, date: str) -> list[str]:
        """PIT 查询: 返回指定日期可交易的股票代码列表"""
        # SELECT code FROM stock_universe
        # WHERE start_date <= date AND (end_date IS NULL OR end_date >= date)
        # AND status NOT IN ('delisted', 'suspended')
    
    def sync_universe(self):
        """同步历史退市/停牌/上市数据 (来源: akshare/xtquant)"""
        # INSERT ON CONFLICT: SCD Type 2 更新
```

**参考文档:**
- [量化回测中的幸存者偏差 (长牛笔记)](https://stay-bullish.com/p/survivor-bias-in-quantitative-backtesting)
- [破除量化回测中的幸存者偏差 (gs-quant)](https://blog.csdn.net/gitblog_00036/article/details/151534400)
- [量化回测的致命陷阱：深入解析生存偏差](https://technologynova.org/%E9%87%8F%E5%8C%96%E5%9B%9E%E6%B5%8B%E7%9A%84%E8%87%B4%E5%91%BD%E9%99%B7%E9%98%B1)

---

### P0-25: CI/CD 自动化测试管线

| 属性 | 内容 |
|------|------|
| **模块** | infra |
| **文件** | 新增 `.github/workflows/ci.yml`, `tests/conftest.py` |
| **工作量** | 2 天 |

**为什么要做:**
当前系统已有 23+ 模块、多个策略和数据管道, 没有自动化测试门禁, 每次修改都可能引入回归 Bug。系统复杂度已超过手工验证能力。

**业界最佳实践:**
- **GitHub Actions**: 免费 CI (公开仓库无限, 私有仓库 2000 min/月)
- **pytest + coverage**: 行业标准 Python 测试框架
- **分层测试**: Unit (快速, 无 IO) → Integration (DB/API) → Backtest Smoke (端到端回测能跑通)
- **pre-commit hooks**: 提交前自动 lint + type check
- **Microsoft Qlib**: CI 包含 `pytest --cov` + MyPy + flake8

**落地方案:**
```yaml
# .github/workflows/ci.yml
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:16
        env:
          POSTGRES_DB: qt_test
          POSTGRES_PASSWORD: test
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: pip install -e ".[dev]"
      - run: pytest tests/ --cov=src --cov-report=xml -x
      - run: mypy src/ --ignore-missing-imports
```

**参考文档:**
- [GitHub Actions for Python](https://docs.github.com/en/actions/automating-builds-and-tests/building-and-testing-python)
- [pytest-cov](https://pytest-cov.readthedocs.io/)
- [pre-commit](https://pre-commit.com/)

---

### P0-26: Alembic 数据库迁移管理

| 属性 | 内容 |
|------|------|
| **模块** | infra |
| **文件** | 新增 `alembic/`, `alembic.ini` |
| **工作量** | 1 天 |

**为什么要做:**
当前使用 `Base.metadata.create_all()` 创建表, 无法追踪 schema 变更历史。一旦修改 ORM 模型 (如加字段), 线上数据库无法自动迁移, 只能手动 ALTER TABLE, 极易出错。随着 P0 阶段不断新增表 (universe, sentiment 等), 此问题会迅速恶化。

**业界最佳实践:**
- **Alembic**: SQLAlchemy 官方迁移工具, 行业标准
- **版本化迁移**: 每次 schema 变更生成一个带时间戳的迁移脚本
- **auto-generate**: Alembic 自动对比 ORM 模型与数据库差异, 生成迁移脚本
- **Django**: 内置 `makemigrations / migrate`, Alembic 是 SQLAlchemy 生态的对等方案

**落地方案:**
```bash
pip install alembic
alembic init alembic
# 修改 alembic/env.py 使用项目的 Base.metadata 和 DATABASE_URL
alembic revision --autogenerate -m "initial schema"
alembic upgrade head
```

**参考文档:**
- [Alembic Tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html)
- [Auto Generating Migrations](https://alembic.sqlalchemy.org/en/latest/autogenerate.html)

---

### P0-27: 涨跌停/停牌数据采集

| 属性 | 内容 |
|------|------|
| **模块** | data |
| **文件** | `src/data/limit_status.py` |
| **工作量** | 1 天 |
| **依赖** | P0-04 (回测管道), P0-06 (akshare 采集) |

**为什么要做:**
P0-04 回测管道新增了涨跌停/停牌模拟, 但需要历史涨跌停数据支撑。当前 `stock_daily` 表只有 OHLCV, 需要标注每日涨跌停状态。

**落地方案:**
1. 利用 `stock_daily` 表现有数据计算涨跌停状态:
   - `is_limit_up = (close == high) and (pct_change >= threshold - 0.01)`
   - `is_limit_down = (close == low) and (pct_change <= -threshold + 0.01)`
   - `is_suspended = (volume == 0)`
2. 阈值判断: 根据股票代码前缀自动判断板块 (688* 科创 20%, 300* 创业 20%, ST 5%, 主板 10%)
3. 数据存入 `stock_daily` 表新增字段或独立 `limit_status` 表
