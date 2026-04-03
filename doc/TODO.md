# qt-quant 综合待办清单 (详细版)

> 最后更新: 2026-04-03
>
> 本清单合并了两部分内容:
> 1. **量化体系优化** — 以专业量化研究视角审查现有代码后发现的缺陷和改进点
> 2. **新模块开发** — doc/11 (情绪引擎)、doc/12 (数据采集)、doc/13 (数据清洗) 中设计完成但代码尚未实现的部分
>
> 每项任务均包含: **为什么要做** → **业界最佳实践** → **技术选型与版本** → **参考文档** → **落地方案**

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
| 数据采集 | `src/datacollect/` | [doc/12-数据采集模块.md](12-数据采集模块.md) |
| 数据清洗 | `src/dataclean/` | [doc/13-数据清洗与LLM.md](13-数据清洗与LLM.md) |
| 情绪引擎 | `src/sentiment/` | [doc/11-市场情绪引擎.md](11-市场情绪引擎.md) |
| 个股雷达 | `src/stockradar/` | doc/13 引擎扩展章节 |
| 资金流向 | `src/fundflow/` | doc/13 引擎扩展章节 |
| 风险预警 | `src/riskmonitor/` | doc/13 引擎扩展章节 |
| 行业轮动 | `src/sectorwatch/` | doc/13 引擎扩展章节 |
| 宏观经济 | `src/macrotrack/` | doc/13 引擎扩展章节 |

---

## P0: 紧急 / 基础 (Bug 修复 + 核心骨架)

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
| pandas | >=2.0 | ✅ 2026最新2.2.x | ATR 计算 (rolling window) |
| numpy | >=1.26 | ✅ | 向量化运算 |

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
| statsmodels | >=0.14 | ✅ 2026最新0.14.4 | OLS 回归做中性化 |
| pandas | >=2.0 | ✅ | 行业哑变量 + 截面操作 |
| 申万行业分类 | 2021版 | ✅ (A股通用标准) | 31 个一级行业 |

**参考文档:**
- Barra CNE5 Model: [xinyue6688/Barra-CNE5](https://github.com/xinyue6688/Barra-CNE5)
- Barra CNE6 + LightGBM: [finexsf/Barra-CNE6-LightGBM](https://github.com/finexsf/Barra-CNE6-LightGBM)
- 国君金工: [基于Barra CNE6的A股风险模型实践](https://finance.sina.com.cn/stock/stockzmt/2024-06-04/doc-inaxpkzq3963139.shtml)
- DolphinDB: [Barra 多因子风险模型实践](https://docs.dolphindb.com/zh/tutorials/barra_multi_factor_risk_model_0.html)

**落地方案:**
1. 在 `FactorDataset.build()` 中，调用 `preprocess_cross_section(df, neutralize_industry=True)`
2. 在 `MultiFactorScoringStrategy` 的因子打分前，按日期截面调用 `neutralize()`
3. 使用申万一级行业代码 (31 个行业)，从 QMT 数据或 akshare `stock_board_industry_name_em()` 获取
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
| scipy.stats | >=1.12 | `median_abs_deviation()` |
| pandas | >=2.0 | `groupby(date).transform()` 截面操作 |

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

---

### P0-04: 回测与实盘管道不一致

| 属性 | 内容 |
|------|------|
| **模块** | backtest |
| **文件** | `src/backtest/` 新增 `orchestrator_backtester.py` |
| **工作量** | 3-5 天 |

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
5. 保留 `strategy_runner.py` 作为快速单策略验证工具
6. 输出复用现有 `PerformanceAnalyzer`

---

### P0-05: SmartHttpClient 反爬 HTTP 客户端

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/client.py` |
| **工作量** | 1 天 |

**为什么要做:**
标准 `requests` 库发送的 HTTP 请求 TLS 指纹 (JA3 Hash) 是固定的，与真实浏览器完全不同。2025-2026 年，东方财富、新浪财经、雪球等 A 股数据源均已部署 TLS 指纹检测，`requests` 成功率仅 ~15%。我们需要一个能伪装真实浏览器 TLS 指纹的 HTTP 客户端。

**业界最佳实践 (2026):**
- **TLS 指纹伪装**: 使用 `curl_cffi` 的 `impersonate="chrome124"` 将成功率从 15% 提升到 82%
- **分层反爬策略**: `requests` (无反爬) → `curl_cffi` (TLS 级) → `Playwright` (JS 级)，按需升级
- **会话一致性**: 同一采集任务复用同一个 Session，保持 Cookie/UA/TLS 指纹一致
- **指数退避 + 抖动**: 失败时 `delay = base * 2^n + random(0, base)`

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| **curl_cffi** | >=0.7.4 | ✅ 2026活跃维护 | TLS 指纹伪装核心。`impersonate="chrome124"` 自动匹配 cipher suite/HTTP2/ALPN |
| fake-useragent | >=2.0 | ✅ | UA 轮换，支持浏览器类型过滤 |
| tenacity | >=9.0 | ✅ | 声明式重试策略 (指数退避 + 条件判断) |

**参考文档:**
- curl_cffi 官方: [github.com/lexiforest/curl_cffi](https://github.com/lexiforest/curl_cffi)
- [Web Scraping Without Getting Blocked: Using curl-cffi (2026)](https://www.blog.datahut.co/post/web-scraping-without-getting-blocked-curl-cffi)
- [Web Scraping Tools Comparison 2026: requests vs curl_cffi vs Playwright vs Scrapy](https://dev.to/vhub_systems_ed5641f65d59/web-scraping-tools-comparison-2026-requests-vs-curlcffi-vs-playwright-vs-scrapy-2fad)
- [How to Bypass Akamai Bot Detection in 2026](https://dev.to/vhub_systems_ed5641f65d59/how-to-bypass-akamai-bot-detection-in-2026-curl-cffi-residential-proxies-5h3k)

**落地方案:**
```python
class SmartHttpClient:
    def __init__(self, config: DatacollectConfig):
        self.session = curl_cffi.requests.Session(impersonate="chrome124")
        self.ua_rotator = UserAgent(browsers=["chrome", "edge"])
        self.retry = tenacity.retry(
            stop=stop_after_attempt(config.max_retries),
            wait=wait_exponential(multiplier=1, max=60) + wait_random(0, 2),
            retry=retry_if_exception_type((ConnectionError, TimeoutError))
        )

    @retry
    def get(self, url, **kwargs) -> Response:
        headers = {"User-Agent": self.ua_rotator.random, ...}
        return self.session.get(url, headers=headers, timeout=30, **kwargs)
```

---

### P0-06: TokenBucketLimiter 令牌桶限流器

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/rate_limiter.py` |
| **工作量** | 0.5 天 |

**为什么要做:**
AKShare 的东方财富数据源 2025-2026 年已大幅收紧限流策略 — 连续调用不超过 20 次 (间隔 0.5 秒) 即触发 IP 封禁，封禁持续数分钟。不同数据源的限流阈值不同 (东财严、新浪松)，需要按域名独立控制请求频率。

**业界最佳实践:**
- **令牌桶算法 (Token Bucket)**: 比固定间隔更灵活，允许突发请求但控制平均速率
- **按域名隔离**: 每个域名独立的令牌桶，互不影响
- **交易时段感知**: 股市交易时段 (9:30-15:00) 增加 30% 请求间隔，非交易时段可放宽
- **抖动 (Jitter)**: ±20% 随机抖动避免固定间隔被检测

**技术选型:**

| 技术 | 版本 | 说明 |
|------|------|------|
| asyncio + threading.Lock | Python 内置 | 线程安全令牌桶 |
| time.monotonic | Python 内置 | 单调时钟避免系统时间跳变 |

**参考文档:**
- AKShare 限流 Issue: [github.com/akfamily/akshare/issues/6214](https://github.com/akfamily/akshare/issues/6214)
- [突破数据采集瓶颈：AKShare股票接口稳定性优化全指南](https://blog.gitcode.com/09b7eb8cf41a3603262ee7b8bce3a2cb.html)
- Wikipedia: [Token Bucket](https://en.wikipedia.org/wiki/Token_bucket)

**落地方案:**
```python
class TokenBucketLimiter:
    def __init__(self, rate: float, burst: int):
        self.rate = rate          # tokens per second
        self.burst = burst        # max burst size
        self.tokens = burst
        self.last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, jitter_pct: float = 0.2):
        with self._lock:
            self._refill()
            if self.tokens < 1:
                wait = (1 - self.tokens) / self.rate
                wait *= 1 + random.uniform(-jitter_pct, jitter_pct)
                time.sleep(wait)
                self._refill()
            self.tokens -= 1
```
配置示例 (`.env`): `DATACOLLECT_AKSHARE_RATE=0.15` (每秒 0.15 次 = 约 7 秒一次)

---

### P0-07: BaseCollector 采集器抽象基类

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/base.py` |
| **工作量** | 0.5 天 |

**为什么要做:**
不同数据源 (akshare SDK、HTTP 爬虫、Playwright 浏览器、Tavily API、OpenClaw) 的采集方式各不相同，但输出格式需要统一以便下游清洗模块处理。抽象基类确保所有采集器遵循相同的接口规范。

**业界最佳实践:**
- **策略模式 (Strategy Pattern)**: 每种采集方式是一个策略实现
- **Scrapy/Crawlee 架构**: Spider 基类定义 `start_requests() → parse() → Item`，所有爬虫继承
- **统一结果格式**: `CollectResult(source, raw_text, url, collected_at, metadata)` 作为模块间契约

**参考文档:**
- Scrapy Architecture: [docs.scrapy.org/en/latest/topics/architecture.html](https://docs.scrapy.org/en/latest/topics/architecture.html)
- Python abc 模块: [docs.python.org/3/library/abc.html](https://docs.python.org/3/library/abc.html)

**落地方案:**
```python
@dataclass
class CollectResult:
    source: str           # "akshare", "http", "browser", "tavily", "openclaw"
    raw_text: str         # 原始内容
    url: str | None
    collected_at: datetime
    metadata: dict        # 额外元数据 (HTTP status, 耗时等)

class BaseCollector(ABC):
    def __init__(self, client: SmartHttpClient, limiter: TokenBucketLimiter): ...
    @abstractmethod
    def collect(self, task: CollectTask) -> list[CollectResult]: ...
    @abstractmethod
    def health_check(self) -> bool: ...
```

---

### P0-08: AkshareCollector

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/collectors/akshare_collector.py` |
| **工作量** | 1 天 |

**为什么要做:**
AKShare 是免费 A 股数据的首选来源 (北向资金、两融、板块资金、涨跌统计等情绪核心数据)。但 2025-2026 年东方财富源的限流策略大幅收紧，需要将 akshare 调用封装为标准采集器，配合限流器使用。

**业界最佳实践:**
- AKShare 限流处理: 基础间隔 ≥5 秒 + ±20% 随机抖动
- 连接池管理: 最大并发 3-5 个连接
- 交易时段增加 30% 间隔
- 失败时指数退避，最大等待 5 分钟

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| **akshare** | >=1.14 | ✅ 持续更新 | 需 Python 3.9+，`pip install akshare --upgrade` |

**参考文档:**
- AKShare 官方文档: [akshare.akfamily.xyz](https://akshare.akfamily.xyz/)
- [AKShare 限流问题 Issue #6214](https://github.com/akfamily/akshare/issues/6214)
- [3个AKShare常见问题排除](https://blog.gitcode.com/d27091aef55f47f199f01d57c9e3e0ca.html)

**落地方案:**
封装 30+ 个核心 akshare 接口 (北向资金 `stock_hsgt_north_net_flow_in_em`、两融 `stock_margin_detail_sse`、板块 `stock_board_industry_cons_em` 等)，每次调用前通过 `TokenBucketLimiter.acquire()` 限流。

---

### P0-09: 数据源注册表

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/registry.py` + `data_sources.json` |
| **工作量** | 1 天 |

**为什么要做:**
数据源会不断增减 (新增 Tavily、下线某个网站)，硬编码不可维护。JSON 配置驱动的注册表使得新增/禁用数据源只需改配置文件。

**业界最佳实践:**
- **配置即代码**: Qlib 的 `provider_uri` 和 Crawlee 的 router 均使用配置驱动
- **热加载**: 注册表支持运行时重载，无需重启服务

**落地方案:**
```json
{
  "north_flow": {
    "collector": "akshare",
    "function": "stock_hsgt_north_net_flow_in_em",
    "schedule": "15:30",
    "rate_limit": {"domain": "eastmoney.com", "rate": 0.15},
    "cleaner": "passthrough",
    "enabled": true
  }
}
```

---

### P0-10: 采集日志 ORM

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/models.py` |
| **工作量** | 0.5 天 |

**为什么要做:**
采集任务需要完整的审计日志 — 何时采集、是否成功、耗时多少、失败原因是什么。这是排查数据质量问题的唯一依据。

**技术选型:**

| 技术 | 版本 | 说明 |
|------|------|------|
| SQLAlchemy | >=2.0 | ORM 定义 |
| PostgreSQL JSONB | 16+ | 存储灵活的元数据字段 |

**参考文档:**
- PostgreSQL JSONB 索引优化: [PostgreSQL JSONB Indexing Strategies (2025)](https://www.rickychilcott.com/2025/09/22/postgresql-indexing-strategies-for-jsonb-columns/)
- [PostgreSQL Performance: JSONB (2026)](https://releaserun.com/postgresql-performance-in-2026-jsonb-full-text-search-and-query-optimization/)

**落地方案:**
- 使用 `jsonb_path_ops` GIN 索引，比默认 GIN 小 30-40%
- 对 `collected_at` 字段创建 BRIN 索引 (时序数据最优)
- 历史数据 90 天自动归档 (APScheduler 清理任务)

---

### P0-11: datacollect 模块初始化

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/__init__.py` + `src/common/config.py` |
| **工作量** | 0.5 天 |

**落地方案:**
在 `src/common/config.py` 中新增 `DatacollectConfig` (Pydantic Settings)，包含 akshare 限流参数、curl_cffi 代理设置、最大重试次数等，所有参数从 `.env` 读取。

---

### P0-12: LLMClient 统一客户端

| 属性 | 内容 |
|------|------|
| **模块** | dataclean |
| **文件** | `src/dataclean/llm_client.py` |
| **工作量** | 1 天 |

**为什么要做:**
数据清洗 (非结构化新闻 → 结构化情绪分数) 依赖 LLM 做结构化抽取。需要支持 DeepSeek 和 Qwen 两个模型的自动降级 — 主模型超时/限流时自动切换到备用模型。

**业界最佳实践 (2026):**
- DeepSeek 和 Qwen 均兼容 OpenAI SDK 协议，使用 `response_format={"type": "json_object"}` 输出 JSON
- **Prompt 中必须显式提及 "json"**: DeepSeek/Qwen 不支持 OpenAI 的 `json_schema` 模式，需要将 Pydantic Schema 嵌入 System Prompt
- **成本**: DeepSeek V3 约 ¥2/百万 token (输入)，Qwen-Max 约 ¥20/百万 token — DeepSeek 作为主模型，Qwen 作为降级备选

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| **openai** SDK | >=1.60 | ✅ 2026最新 | DeepSeek/Qwen 均兼容此 SDK |
| **pydantic** | >=2.6 | ✅ | Schema 定义 + `.model_json_schema()` 导出 |
| tenacity | >=9.0 | ✅ | 重试 + 降级逻辑 |

**参考文档:**
- DeepSeek API 文档: [platform.deepseek.com/api-docs](https://platform.deepseek.com/api-docs)
- Qwen API 文档: [dashscope.aliyuncs.com](https://dashscope.aliyuncs.com/)
- [Enabling Qwen and DeepSeek for Structured Output](https://www.oreateai.com/blog/bridging-the-gap-enabling-qwen-and-deepseek-for-structured-output-in-microsofts-agent-framework/)
- [DeepSeek AI for Finance – Workflows & Prompts](https://deepseeksai.com/for-finance/)

**落地方案:**
```python
class LLMClient:
    PROVIDERS = [
        {"name": "deepseek", "base_url": "https://api.deepseek.com", "model": "deepseek-chat"},
        {"name": "qwen",     "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-max"},
    ]

    def extract(self, text: str, schema: type[BaseModel]) -> BaseModel:
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        system_prompt = f"Extract structured info as JSON matching this schema:\n{schema_json}"
        for provider in self.PROVIDERS:
            try:
                return self._call(provider, system_prompt, text, schema)
            except (Timeout, RateLimitError):
                continue
        return self._rule_fallback(text, schema)  # 全部失败时用 RuleCleaner
```

---

### P0-13 ~ P0-19: dataclean 模块其余组件

| # | 描述 | 文件 | 工作量 |
|---|------|------|--------|
| P0-13 | `BaseCleaner` + `CleanResult` 抽象基类 | `src/dataclean/base.py` | 0.5 天 |
| P0-14 | `SentimentExtraction` Pydantic Schema (情绪分/实体/事件类型) | `src/dataclean/schemas/sentiment.py` | 0.5 天 |
| P0-15 | `SentimentCleaner` LLM 清洗器 | `src/dataclean/cleaners/sentiment_cleaner.py` | 1 天 |
| P0-16 | `PassthroughCleaner` 直通清洗器 (akshare DataFrame) | `src/dataclean/cleaners/passthrough_cleaner.py` | 0.5 天 |
| P0-17 | `RuleCleaner` 规则降级清洗 (关键词+正则) | `src/dataclean/cleaners/rule_cleaner.py` | 0.5 天 |
| P0-18 | 情绪清洗 System Prompt 模板 | `src/dataclean/prompts/sentiment_prompt.py` | 0.5 天 |
| P0-19 | 模块初始化 + `.env` 参数 | `src/dataclean/__init__.py` + config | 0.5 天 |

**为什么要做:**
原始数据格式混杂 (HTML、JSON、纯文本)，需要经过清洗转换为标准 Pydantic Schema 后才能入库。三层清洗器 (LLM → 规则 → 直通) 形成降级链:
- **SentimentCleaner**: LLM 做精准情绪抽取 (成本 ~¥0.002/条，精度高)
- **RuleCleaner**: LLM 不可用时的正则/关键词兜底 (免费，精度一般)
- **PassthroughCleaner**: akshare 返回的已结构化 DataFrame 直接入库

**参考文档:** 详见 [doc/13-数据清洗与LLM.md](13-数据清洗与LLM.md)

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

## P1: 重要 (量化核心 + 模块完善)

### P1-01: Purged Walk-Forward Cross-Validation

| 属性 | 内容 |
|------|------|
| **模块** | ml |
| **文件** | `src/ml/cross_validation.py` (新增), `src/ml/dataset.py` |
| **工作量** | 2-3 天 |

**为什么要做:**
当前 ML 模块使用简单的 train/val/test 三段切分。这在金融时间序列中会导致严重的**标签泄露 (look-ahead bias)**:
- `label_period=2` 意味着 T 日的标签依赖 T+1 和 T+2 的价格
- 简单切分时，训练集末尾的样本标签可能与验证集开头的样本在时间上重叠
- **后果**: 回测 Sharpe 可能虚高 30-50%，实盘完全无法复现

**业界最佳实践:**
- **Marcos López de Prado (2018)**: 在 *Advances in Financial Machine Learning* 第7章提出 **Purged K-Fold CV**:
  - **Purging**: 从训练集中删除所有与测试集标签时间范围重叠的样本
  - **Embargo**: 在测试集之后额外添加一个时间缓冲区 (通常为样本总数的 5%)，排除因市场滞后效应导致的信息泄露
- **Combinatorial Purged CV (CPCV)**: de Prado 的改进版，从 N 个折中选 k 个作为测试集，生成更多回测路径
- **Rolling Walk-Forward**: 每 6 个月前滚重新训练，确保模型始终使用最新数据

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| **skfolio** | >=0.5 | ✅ 2025-2026活跃 | 提供 `WalkForward` 和 `CombinatorialPurgedCV`，scikit-learn 兼容 |
| **mlfinlab** | >=2.0 | ✅ | Hudson & Thames 实现，`PurgedKFold` + `ml_cross_val_score` |
| 自研 | - | - | 也可基于 scikit-learn `BaseCrossValidator` 自行实现 |

**参考文档:**
- Marcos López de Prado, *Advances in Financial Machine Learning*, Ch.7 (原始论文)
- Wikipedia: [Purged Cross-Validation](https://en.wikipedia.org/wiki/Purged_cross-validation)
- skfolio 文档: [skfolio.org/user_guide/model_selection.html](https://skfolio.org/user_guide/model_selection.html)
- Hudson & Thames: [PurgedKFold Notebook](https://github.com/hudson-and-thames/example-notebooks/blob/main/Cross_validation/Chapter7_Cross_Validation.ipynb)
- [KFold CV with Purging and Embargo (Medium)](https://antonio-velazquez-bustamante.medium.com/kfold-cross-validation-with-purging-and-embargo-the-ultimate-cross-validation-technique-for-time-2d656ea6f476)

**落地方案:**
```python
class PurgedTimeSeriesSplit(BaseCrossValidator):
    def __init__(self, n_splits=5, purge_days=3, embargo_pct=0.05):
        self.n_splits = n_splits
        self.purge_days = purge_days
        self.embargo_pct = embargo_pct

    def split(self, X, y=None, groups=None):
        # groups = date column
        dates = groups.unique().sort_values()
        fold_size = len(dates) // self.n_splits
        for i in range(self.n_splits):
            test_start = dates[i * fold_size]
            test_end = dates[(i+1) * fold_size - 1]
            # Purge: remove train samples whose labels overlap test
            train_end = test_start - timedelta(days=self.purge_days)
            # Embargo: exclude samples after test
            embargo_end = test_end + timedelta(days=int(len(dates) * self.embargo_pct))
            ...
```

---

### P1-02: Rolling Walk-Forward 重训练

| 属性 | 内容 |
|------|------|
| **模块** | ml |
| **文件** | `src/ml/auto_iterate.py` |
| **工作量** | 2 天 |

**为什么要做:**
A 股市场风格每 3-6 个月显著切换 (如 2024 小盘成长 → 2025 大盘价值)。固定训练集的模型会逐渐失效 (alpha decay)。研究显示美国市场年化 alpha 衰减成本为 5.6%，欧洲为 9.9%。

**业界最佳实践:**
- **Qlib Rolling Retrain Pipeline**: 24 月训练 + 6 月验证 + 6 月测试，每 6 月前滚
- **动量策略生命周期**: ~10 个月后转负，必须在此之前重训练
- **自动化**: 每周/月自动触发重训练，不依赖人工判断

**参考文档:**
- Qlib Workflow: [github.com/microsoft/qlib](https://github.com/microsoft/qlib)
- [Signal Decay Analysis: Understanding Alpha Lifecycles](https://microalphas.com/signal-decay-patterns/)
- [Multi-Factor Strategies Framework for Independent Quants](https://dev.to/quant001/multi-factor-strategies-arent-exclusive-to-big-firms-a-research-framework-for-independent-quants-38ka)

---

### P1-03: 因子衰减监控

| 属性 | 内容 |
|------|------|
| **模块** | monitoring |
| **文件** | 新增 `src/monitoring/factor_monitor.py` |
| **工作量** | 2 天 |

**为什么要做:**
因子有效性会随时间衰减 (alpha decay)。2026 年的研究显示稳定股票因子 60% 衰减、动量因子约 10 个月后转负。没有监控 = 策略失效也不自知。

**业界最佳实践:**
- **核心 KPI (每日监控)**: 滚动 IC (20/60 日)、ICIR、因子换手率、hit-rate by decile
- **阈值**: IC 连续 20 天 < 0.02 → 告警; ICIR < 0.5 → 降权
- **PSI (Population Stability Index)**: 检测因子分布漂移，PSI > 0.2 → 中度关注，> 0.4 → 严重
- **KS 检验**: 比较训练期和实盘期的因子分布差异
- **分级响应**: 告警 → 缩减仓位 → 停止新开仓 → 隔离策略 → 触发重训练

**技术选型:**

| 技术 | 版本 | 说明 |
|------|------|------|
| scipy.stats | >=1.12 | `ks_2samp()` KS 检验 |
| numpy | >=1.26 | PSI 计算 |
| Alphalens-reloaded | >=0.0.14 | 因子分析可视化 (可选) |

**参考文档:**
- [Concept Drift Alarms for Quant Signals](https://stockalpha.ai/alpha-learning/concept-drift-alarms-for-quant-signals-detecting-when-alpha-decays)
- [Signal Decay Analysis](https://microalphas.com/signal-decay-patterns/)
- [Alphalens 因子评估指南](https://medium.com/@er.mananjain26/separating-signal-from-noise-a-practical-guide-to-evaluating-alpha-factors-with-alphalens-b883070aab14)

---

### P1-04: 模型漂移检测

| 属性 | 内容 |
|------|------|
| **模块** | monitoring |
| **文件** | 新增 `src/monitoring/model_monitor.py` |
| **工作量** | 2 天 |

**为什么要做:**
LightGBM 模型的预测能力会随市场结构变化退化 (concept drift)。PSI 可检测输入特征分布是否偏移。

**业界最佳实践:**
- **预测值 vs 实际收益滚动相关性**: 每日计算 20 日滚动 correlation
- **PSI**: `PSI = Σ (actual% - expected%) × ln(actual% / expected%)`，对每个特征独立计算
- **Bayesian Change-Point Detection**: 识别时序结构性断点
- **Shadow Backtest**: 实时用最新数据跑影子回测，与实盘比对

**参考文档:** 同 P1-03

---

### P1-05: 组合优化器

| 属性 | 内容 |
|------|------|
| **模块** | portfolio |
| **文件** | 新增 `src/portfolio/optimizer.py` |
| **工作量** | 3-5 天 |

**为什么要做:**
当前 `PositionSizer` 只支持等权/ATR/Kelly 三种简单分配，不控制:
- 行业集中度 (可能 80% 资金在一个行业)
- 风格暴露 (可能全是小盘股)
- 换手率 (高频换仓侵蚀 alpha)
- 组合风险最优化

**业界最佳实践:**
- **Markowitz Mean-Variance (1952)**: 经典框架，但对预期收益估计敏感
- **Risk Parity**: 风险贡献均等化，不依赖收益预测，稳健性更好
- **HRP (Hierarchical Risk Parity)**: López de Prado 提出，使用层次聚类确定资产权重，比传统 MVO 更稳定
- **约束优化**: 行业暴露 ≤ 15%、单只 ≤ 5%、日换手率 ≤ 20%

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| **skfolio** | >=0.5 | ✅ 2026活跃 | 基于 scikit-learn 的组合优化库，支持 MVO/Risk Parity/HRP/Black-Litterman，内置 WalkForward CV |
| **cvxpy** | >=1.5 | ✅ | 凸优化求解器，skfolio 底层依赖 |
| **Riskfolio-Lib** | >=7.2 | ✅ | 另一选择，24+ 凸风险度量 |
| **riskparity.py** | >=0.1 | ✅ | 专用风险平价库 |

**参考文档:**
- skfolio 官方: [skfolio.org](https://skfolio.org/) (scikit-learn 原生集成)
- skfolio 优化指南: [skfolio.org/user_guide/optimization.html](https://skfolio.org/user_guide/optimization.html)
- Riskfolio-Lib: [riskfolio-lib.readthedocs.io](https://riskfolio-lib.readthedocs.io/en/latest)
- [Portfolio Optimization with Python (2026)](https://pub.towardsai.net/portfolio-optimization-with-python-mean-variance-vs-risk-parity-vs-min-vol-28fee8192d2f)
- [cvxpy Portfolio Optimization Tutorial](https://trader-algoritmico.com/blog/portfolio-optimization-with-cvxpy-mean-variance-vs-hrp-in-python)

**落地方案 (推荐 skfolio):**
```python
from skfolio import Population
from skfolio.optimization import MeanRisk, ObjectiveFunction, RiskMeasure
from skfolio.model_selection import WalkForward

model = MeanRisk(
    objective_function=ObjectiveFunction.MAXIMIZE_RATIO,  # Max Sharpe
    risk_measure=RiskMeasure.CVAR,
    max_weight=0.05,  # 单只 ≤ 5%
)
cv = WalkForward(train_size=252*2, test_size=63)  # 2年训练+3月测试
```

---

### P1-06: 风险归因 (简化 Barra 模型)

| 属性 | 内容 |
|------|------|
| **模块** | portfolio |
| **文件** | 新增 `src/portfolio/risk_attribution.py` |
| **工作量** | 3 天 |

**为什么要做:**
不做风险归因就无法回答: "我的收益来自选股能力 (alpha) 还是行业暴露 (beta)？" 如果收益主要来自行业 beta，那策略在行业轮动时会崩溃。

**业界最佳实践:**
- **Barra CNE5/CNE6**: 中信建投、国泰君安的标配。10 大风格因子 (规模/价值/动量/波动率/流动性等) + 31 行业因子
- **截面回归**: `R_stock = α + Σ(β_style × Style_factor) + Σ(β_industry × Industry_dummy) + ε`
- **协方差估计**: Newey-West 调整 + 特征值风险调整 + 波动率偏误调整

**技术选型:**

| 技术 | 版本 | 说明 |
|------|------|------|
| statsmodels | >=0.14 | 截面 OLS 回归 |
| numpy/pandas | - | 因子矩阵构建 |

**参考文档:**
- Barra CNE5 Python: [github.com/xinyue6688/Barra-CNE5](https://github.com/xinyue6688/Barra-CNE5)
- Barra CNE6 + LGB: [github.com/finexsf/Barra-CNE6-LightGBM](https://github.com/finexsf/Barra-CNE6-LightGBM)
- [基于Barra CNE6的A股风险模型实践 (国君金工)](https://finance.sina.com.cn/stock/stockzmt/2024-06-04/doc-inaxpkzq3963139.shtml)
- [DolphinDB Barra 多因子风险模型](https://docs.dolphindb.com/zh/tutorials/barra_multi_factor_risk_model_0.html)
- [量化投资进阶：Barra多因子模型](https://cloud.baidu.com/article/3791053)

**落地方案 (简化版 5 因子):**
```python
STYLE_FACTORS = ["size", "value", "momentum", "volatility", "liquidity"]

def attribute_returns(portfolio_returns, factor_exposures):
    """简化 Barra 归因: 将组合收益分解为 alpha + 风格 + 行业"""
    X = factor_exposures[STYLE_FACTORS + INDUSTRY_DUMMIES]
    model = sm.OLS(portfolio_returns, sm.add_constant(X)).fit()
    attribution = {
        "alpha": model.params["const"],
        "style": {f: model.params[f] * factor_exposures[f].mean() for f in STYLE_FACTORS},
        "industry": ...,
        "residual": model.resid.std()
    }
    return attribution
```

---

### P1-07: 换手率约束

| 属性 | 内容 |
|------|------|
| **模块** | strategy |
| **文件** | `src/strategy/signal_arbiter.py` 或 `position_sizer.py` |
| **工作量** | 1 天 |

**为什么要做:**
高换手率侵蚀 alpha。回测中频繁换仓看似 "精准"，但实盘中手续费 + 滑点 + 冲击成本会吃掉大部分收益。A 股印花税 0.05% + 佣金 0.025% ≈ 单边 0.075%，双边 0.15%，年化换手率 200% 就意味着 30% 的费率成本。

**落地方案:**
在 `SignalArbiter` 中增加 `max_daily_turnover` 参数 (如 20%)，当日买卖金额 / 总资产超过阈值时截断低优先级信号。

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
| **APScheduler** | >=4.0 (alpha) / 3.10 (stable) | ✅ 2025-2026 | 轻量级进程内调度，支持 cron/interval/date 三种触发器 |

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

### P1-16 ~ P1-19: sentiment 完善

| # | 描述 | 文件 | 工作量 |
|---|------|------|--------|
| P1-16 | `composite_index.py` 6维情绪合成指数 | `src/sentiment/composite_index.py` | 1.5 天 |
| P1-17 | `macro_classifier.py` 宏观状态分类器 | `src/sentiment/macro_classifier.py` | 2 天 |
| P1-18 | Orchestrator 集成 Profile | `src/strategy/orchestrator.py` | 1.5 天 |
| P1-19 | 情绪 API 完整化 | `src/api/routers/sentiment_router.py` | 1.5 天 |

**为什么要做:** 情绪合成指数 (CSI) 将 6 个维度 (量价/资金/情绪/波动/结构/衍生品) 加权合成为单一数值，驱动宏观状态分类器输出 6 种状态 (牛市/震荡偏多/震荡/震荡偏空/熊市/极端恐慌)。每种状态对应一套策略参数 Profile。

**落地参考:** 详见 [doc/11-市场情绪引擎.md](11-市场情绪引擎.md)

---

## P2: 增强 (高级功能 + 扩展引擎)

### P2-01: 滑点模型

| 属性 | 内容 |
|------|------|
| **模块** | backtest |
| **文件** | `src/backtest/fees.py` |
| **工作量** | 1 天 |

**为什么要做:**
回测与实盘的收益差距通常在 -20% 到 -50%，其中滑点和冲击成本是最大来源。当前回测只有固定费率，没有基于成交量的动态滑点。

**业界最佳实践:**
- **Almgren-Chriss 模型**: 经典市场冲击模型，`impact = η × σ × (V_order / V_avg)^β`
- **简化版 (散户适用)**: `slippage = base_spread + impact_coeff × (order_size / daily_volume) × volatility`
- **不对称费率**: A 股卖出有 0.05% 印花税，买入没有

**技术选型:**

| 技术 | 版本 | 说明 |
|------|------|------|
| 自研 SlippageModel | - | 固定 bps + 成交量冲击 |

**参考文档:**
- [Almgren-Chriss Market Impact Model](https://github.com/shubhamcodez/Market-Impact-Model)
- [Realistic Backtesting: Transaction Costs, Slippage (2025)](https://hyper-quant.tech/research/realistic-backtesting-methodology)
- [Estimating Implicit Transaction Costs (Medium)](https://medium.com/@msndourr/estimating-implicit-transaction-costs-under-a-linear-market-impact-model-c30f26cfd5a7)

**落地方案:**
```python
class SlippageModel:
    def __init__(self, fixed_bps=5, impact_coeff=0.1):
        self.fixed_bps = fixed_bps
        self.impact_coeff = impact_coeff

    def estimate(self, order_value, daily_volume, volatility):
        fixed = order_value * self.fixed_bps / 10000
        impact = self.impact_coeff * (order_value / daily_volume) * volatility * order_value
        return fixed + impact
```

---

### P2-02: XGBoost / CatBoost 真正实现 + Ensemble

| 属性 | 内容 |
|------|------|
| **模块** | ml |
| **文件** | `src/ml/xgb_model.py`, `src/ml/catboost_model.py` |
| **工作量** | 2 天 |

**为什么要做:**
当前 XGB/CatBoost 是空壳 (调 LGB 并打 warning)。模型集成 (ensemble) 可降低单模型过拟合风险:
- LGB: 速度最快，叶子生长策略
- XGB: 更正则化，层级生长策略
- CatBoost: 原生类别特征处理，有序提升 (ordered boosting)

**业界最佳实践:**
- **Rank Averaging**: 每个模型输出排名 (而非原始预测值)，取排名均值。这消除了模型间尺度差异
- **Stacking**: 三模型预测值作为 meta-learner (如 Ridge/Logistic) 的输入
- **实战效果**: Kaggle 金融竞赛中 XGB+LGB+CatBoost stacking 是标配方案，Sharpe 提升 10-20%
- **PenguinBoost (2025)**: 专为金融设计的混合 GBDT 库，内置 Era Boosting 和特征中性化

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| **xgboost** | >=2.1 | ✅ 2026活跃 | `pip install xgboost` |
| **catboost** | >=1.2 | ✅ 2025最新 | `pip install catboost` |
| **penguinboost** | >=0.3.3 | ✅ 2025 | 金融专用 GBDT (可选) |

**参考文档:**
- [Stacking Ensembles: XGBoost + LightGBM + CatBoost (Medium)](https://medium.com/@stevechesa/stacking-ensembles-combining-xgboost-lightgbm-and-catboost-to-improve-model-performance-d4247d092c2e)
- [Quantitative ML/DL Ensemble AlgoTrading](https://github.com/suraj-phanindra/quantitative-ml-dl-ensemble-algotrading)
- [Kaggle Ensemble: XGB + LGB + CatBoost](https://www.kaggle.com/code/suhanigupta04/ensemble-xgb-lgb-catboost-predict-scores)
- PenguinBoost: [pypi.org/project/penguinboost](https://pypi.org/project/penguinboost/0.3.3/)

---

### P2-03: 绩效分析增强

| 属性 | 内容 |
|------|------|
| **模块** | backtest |
| **文件** | `src/backtest/performance.py` |
| **工作量** | 2 天 |

**为什么要做:**
当前绩效只有基础指标 (年化收益/Sharpe/最大回撤)。缺少:
- 月度收益热力图 (直观发现季节性)
- 滚动 Sharpe/Alpha (检测策略是否阶段性失效)
- Bootstrap 显著性检验 (Sharpe > 0 的 p-value)
- 信息比率 IR + Tracking Error (相对基准评估)

**参考文档:**
- quantstats: [github.com/ranaroussi/quantstats](https://github.com/ranaroussi/quantstats) (自动生成完整报告)

---

### P2-04: Survivorship Bias / PIT 数据管理

| 属性 | 内容 |
|------|------|
| **模块** | data |
| **文件** | 新增 `src/data/universe_manager.py` |
| **工作量** | 2 天 |

**为什么要做:**
不处理幸存者偏差的回测结果是虚假的:
- **年化收益虚高 1.5-4.5%** (累积 35-45%)
- **Sharpe 虚高 20-30%**
- **最大回撤低估 15-25%**

原因: 只用当前存活股票回测，遗漏了退市 (往往暴跌 80%+) 和被剔除指数成分的股票。

**业界最佳实践:**
- **SCD Type 2 (缓慢变化维度)**: 记录每只股票的生命周期 (`start_date`, `end_date`, `status_at_end`)
- **Point-in-Time 查询**: "T 日哪些股票是可交易的？" 而非 "今天的股票列表回溯到过去"
- **财务数据用 `announce_date`**: 而非 `report_date`，避免使用尚未公布的财报数据

**参考文档:**
- [量化回测中的幸存者偏差 (长牛笔记)](https://stay-bullish.com/p/survivor-bias-in-quantitative-backtesting)
- [破除量化回测中的幸存者偏差 (gs-quant)](https://blog.csdn.net/gitblog_00036/article/details/151534400)
- [量化回测的致命陷阱：深入解析生存偏差](https://technologynova.org/%E9%87%8F%E5%8C%96%E5%9B%9E%E6%B5%8B%E7%9A%84%E8%87%B4%E5%91%BD%E9%99%B7%E9%98%B1)
- [Historical Constituents of an Equity Index in Python](https://concretumgroup.com/historical-constituents-of-an-equity-index-in-python-norgate-data/)

---

### P2-05: 交易成本归因

| 属性 | 内容 |
|------|------|
| **模块** | backtest |
| **文件** | `src/backtest/performance.py` |
| **工作量** | 1 天 |

**落地方案:** 回测报告增加: 年化换手率、交易成本占毛收益比、扣费后 Sharpe、分策略换手统计。

---

### P2-06: 多周期标签

| 属性 | 内容 |
|------|------|
| **模块** | ml |
| **文件** | `src/ml/dataset.py` |
| **工作量** | 1 天 |

**为什么要做:** 不同持仓周期对应不同的 alpha 模式。日内反转、3-5 日动量、20 日趋势可能同时存在。单一 `label_period=2` 只捕获一种模式。

**落地方案:** `FactorDataset` 同时生成 1/3/5/10/20 日前向收益标签，多模型并行训练后加权合成。

---

### P2-07 ~ P2-09: 数据采集高级功能

| # | 描述 | 技术 | 文件 | 工作量 |
|---|------|------|------|--------|
| P2-07 | `TavilyCollector` 搜索 API | Tavily Python SDK v0.5+ | `collectors/tavily_collector.py` | 1 天 |
| P2-08 | `BrowserCollector` Playwright | Playwright >=1.48 | `collectors/browser_collector.py` | 1.5 天 |
| P2-09 | `HttpCollector` 通用 HTTP | curl_cffi >=0.7 | `collectors/http_collector.py` | 1 天 |

**P2-07 Tavily 参考:**
- Tavily Python SDK: [github.com/tavily-ai/tavily-python](https://github.com/tavily-ai/tavily-python) (2026.03 更新)
- Market Researcher 示例: [docs.tavily.com/examples/use-cases/market-researcher](https://docs.tavily.com/examples/use-cases/market-researcher)
- 开源 Market Researcher: [github.com/tavily-ai/market-researcher](https://github.com/tavily-ai/market-researcher)

**P2-08 Playwright 反爬要点 (2026):**
- 禁用 `navigator.webdriver` 标志
- 伪造 `navigator.plugins` 和 WebGL 指纹
- 会话一致性 > 随机化 (viewport/UA/locale/timezone 对齐)
- 居民代理 IP > 数据中心 IP
- 参考: [How Sites Detect Headless Browsers (2026)](https://dev.to/vhub_systems_ed5641f65d59/how-sites-detect-headless-browsers-and-how-to-evade-each-signal-2026-guide-2jj0)
- 参考: [Playwright Anti-Bot Detection (2026)](https://alterlab.io/blog/playwright-anti-bot-detection-what-actually-works-in-2026)

---

### P2-10 ~ P2-12: 数据清洗高级 Schema

| # | 描述 | 文件 | 工作量 |
|---|------|------|--------|
| P2-10 | `SectorSignalExtraction` Schema (行业轮动) | `schemas/sector_signal.py` | 1 天 |
| P2-11 | `FundFlowExtraction` Schema (资金流向) | `schemas/fund_flow.py` | 0.5 天 |
| P2-12 | `MacroIndicatorExtraction` Schema (宏观经济) | `schemas/macro_indicator.py` | 0.5 天 |

---

### P2-13 ~ P2-14: 情绪引擎高级功能

| # | 描述 | 文件 | 工作量 |
|---|------|------|--------|
| P2-13 | `feature_builder.py` 情绪特征工程 → LGB | `src/sentiment/feature_builder.py` | 2 天 |
| P2-14 | 合成指数权重自动学习 | `src/sentiment/composite_index.py` | 1 天 |

**P2-13 为什么要做:** 情绪指标需要二次加工才能喂给 LGB:
- 滚动均值 (5/10/20日): 平滑噪声
- Z-score: 标准化可跨指标比较
- 差分: 捕捉变化速度
- 分位数分类 (恐慌/正常/过热): LGB 对分类特征更友好

**P2-14:** 用 LGB 的 `feature_importance` 自动学习 6 维权重，替代 `.env` 手动配置。

---

### P2-15 ~ P2-17: 扩展分析引擎

| # | 引擎 | 描述 | 路径 | 工作量 |
|---|------|------|------|--------|
| P2-15 | stockradar | 个股舆情/事件/利好利空 → 信号增强 | `src/stockradar/` | 3 天 |
| P2-16 | fundflow | 北向/融资/大单深度分析 → 跟随聪明钱 | `src/fundflow/` | 3 天 |
| P2-17 | riskmonitor | 黑天鹅/政策突变/闪崩 → 紧急止损 | `src/riskmonitor/` | 2 天 |

---

## P3: 长期 (可选优化 + 远期规划)

### P3-01: SHAP 可解释性

| 属性 | 内容 |
|------|------|
| **模块** | ml |
| **文件** | `src/ml/lgb_model.py` 或新增 `explainability.py` |
| **工作量** | 1 天 |

**为什么要做:**
LGB 的 `feature_importance(gain)` 只告诉你 "哪个因子重要"，但不告诉你 "重要性方向" 和 "对单只股票的预测贡献"。SHAP 可以:
- **全局**: 哪些因子最影响预测？方向如何？(Summary Plot)
- **局部**: 这只股票被预测为涨，主要因为哪些因子？(Waterfall Plot)
- **因子选择**: SHAP 值可以替代 IC 做更精准的因子筛选

2025 年研究证实: SHAP 选出 Top-5 因子重训 LGB → 等权组合跑赢大盘。

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| **shap** | >=0.50.0 | ✅ 2026最新 | `TreeExplainer` 对 LGB 有原生优化，O(TLD) 复杂度 |

**参考文档:**
- SHAP 官方: [github.com/shap/shap](https://github.com/shap/shap)
- [SHAP Values Python Guide (2026)](https://pythondatabench.com/article/shap-values-python-practical-guide-explaining-ml-models)
- [Stock Return Forecasting Using SHAP (2025 论文)](https://www.atlantis-press.com/proceedings/iciaai-25/126015307)
- [Interpreting LightGBM with SHAP](https://toxigon.com/interpreting-lightgbm-models-with-shap-values)
- [interpretable-lightgbm 工具库](https://github.com/ccomkhj/interpretable-lightgbm)

**落地方案:**
```python
import shap

explainer = shap.TreeExplainer(lgb_model)
shap_values = explainer.shap_values(X_test)

# 全局特征重要性
shap.summary_plot(shap_values, X_test, feature_names=factor_names)
# 单只股票归因
shap.waterfall_plot(shap.Explanation(shap_values[0], base_values=explainer.expected_value))
```

---

### P3-02: 实验管理 (MLflow)

| 属性 | 内容 |
|------|------|
| **模块** | ml |
| **文件** | 新增 `src/ml/experiment_tracker.py` |
| **工作量** | 1 天 |

**为什么要做:**
当前 ML 迭代没有实验追踪 — 无法回答 "上次用哪个因子组合、什么超参、训练了多长时间、结果如何"。每次迭代结果丢失，重复实验浪费算力。

**业界最佳实践:**
- **MLflow**: Apache 2.0 开源，支持自部署。2026 年最新版支持 PostgreSQL 后端 + S3 artifact 存储
- **核心功能**: 记录超参 (LR, num_leaves, max_depth) → 记录指标 (IC, ICIR, Sharpe) → 存储模型 artifact → Model Registry 管理模型版本
- **2026 金融应用**: [Financial Market Intelligence Platform](https://github.com/cdobratz/market-intelligence-mvp) 使用 MLflow + Airflow + FastAPI 的完整管道

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| **mlflow** | >=2.20 | ✅ 2026活跃 | 核心: tracking + model registry |
| sqlite (轻量) 或 PostgreSQL | - | - | MLflow 后端存储 |

**参考文档:**
- MLflow 官方: [mlflow.org](https://mlflow.org/)
- [MLflow 完整指南 (2026.03)](https://www.marktechpost.com/2026/03/01/a-complete-end-to-end-coding-guide-to-mlflow-experiment-tracking/)
- [MLflow Production Guide (2026.03)](https://www.youngju.dev/blog/ai-platform/2026-03-07-ai-platform-mlflow-experiment-tracking-model-registry.en)
- [MLflow Experiment Tracking Tutorial (2026)](https://oneuptime.com/blog/post/2026-01-27-mlflow-experiment-tracking/view)

---

### P3-03: 轻量级事件总线

| 属性 | 内容 |
|------|------|
| **模块** | common |
| **文件** | 新增 `src/common/event_bus.py` |
| **工作量** | 3 天 |

**为什么要做:**
当前模块间通过函数调用串联 (采集→清洗→情绪→策略→交易)。如果要新增一个 "数据采集完成后同时触发清洗+个股雷达+风险预警"，需要修改采集模块的代码。事件总线实现 "发布者不知道谁在监听"。

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| **blinker** | >=1.9 | ✅ 2024 | Flask 内部使用的信号库，轻量 |
| **PyPubSub** | >=4.0.7 | ✅ 2025.12 | 话题式发布订阅 |
| asyncio 自研 | Python 内置 | ✅ | 支持异步处理器 |

**参考文档:**
- Blinker: [blinker GitHub](https://github.com/pallets-eco/blinker) + [Python Signals for Decoupling](https://dev.to/recca0120/blinker-python-signals-for-decoupling-modules-441p)
- PyPubSub: [pypubsub.readthedocs.io](https://pypubsub.readthedocs.io/)
- [Event Bus with asyncio in Python (2026)](https://oneuptime.com/blog/post/2026-01-25-event-bus-asyncio-python/view)

---

### P3-04: 数据版本化

| 属性 | 内容 |
|------|------|
| **模块** | data |
| **文件** | `src/data/` |
| **工作量** | 2 天 |

**为什么要做:** 确保回测可复现 — 同一份因子数据 + 同一个模型 = 相同的回测结果。数据更新后需要保留历史快照。

---

### P3-05: ProxyPool 代理池

| 属性 | 内容 |
|------|------|
| **文件** | `src/datacollect/proxy_pool.py` |
| **工作量** | 1 天 |

**为什么要做:** 当 IP 被封禁时的最后手段。curl_cffi + 居民代理可将成功率从 82% 提升到 91%。

**参考:** [How to Bypass Akamai Bot Detection 2026](https://dev.to/vhub_systems_ed5641f65d59/how-to-bypass-akamai-bot-detection-in-2026-curl-cffi-residential-proxies-5h3k)

---

### P3-06: 本地 FinBERT NLP

| 属性 | 内容 |
|------|------|
| **文件** | `src/dataclean/cleaners/finbert_cleaner.py` |
| **工作量** | 2 天 |

**为什么要做:**
LLM API 有成本和延迟。FinBERT 110M 参数，家用 GPU (GTX 1660+) 或 CPU 即可运行，替代 API 做高频情感分析。

**2025 最新进展: FinBERT2**
- 在 32B token 中文金融语料上预训练 — 最大的中文金融预训练模型
- 分类任务: 比 GPT-4-turbo 和 Claude 3.5 Sonnet 高 9.7%-12.3%
- 检索任务: 比 OpenAI text-embedding-3-large 高 4.2%
- MIT 开源协议

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| **FinBERT2** | 2025 | ✅ 最新 | [valuesimplex/FinBERT](https://github.com/valuesimplex/FinBERT) |
| transformers | >=4.46 | ✅ | HuggingFace 推理框架 |
| torch | >=2.4 | ✅ | GPU/CPU 推理 |

**参考文档:**
- FinBERT2 论文: [arxiv.org/abs/2506.06335](https://arxiv.org/abs/2506.06335)
- FinBERT2 代码: [github.com/valuesimplex/FinBERT](https://github.com/valuesimplex/FinBERT)
- FinBERT 官网: [finbert.org](https://finbert.org/)
- [FinBERT 金融情感分析完整指南 (2025)](https://blog.gitcode.com/573f7b1a41018f183b1d047a1a701979.html)

---

### P3-07: GenericExtraction Schema

| 属性 | 内容 |
|------|------|
| **文件** | `src/dataclean/schemas/generic.py` |
| **工作量** | 0.5 天 |

通用自定义清洗模板，用户可定义任意抽取字段。

---

### P3-08: 热门股/一日游识别模型

| 属性 | 内容 |
|------|------|
| **文件** | `src/sentiment/` 或 `src/ml/` |
| **工作量** | 2 天 |

**为什么要做:** A 股短线最大陷阱是 "一日游" (今天涨停明天砸盘)。量化识别特征:
- 量化席位占比 > 50% + 游资 < 20%
- 封成比 < 0.5 + 换手率 > 15%
- 板块涨停 < 3 只
- 无基本面驱动

**落地:** LGB 二分类 (目标: 次日跌幅 ≥ 2%)，RPS + 封板质量 + 板块联动 + 资金结构作为特征。

---

### P3-09 ~ P3-10: 远期扩展引擎

| # | 引擎 | 描述 | 路径 | 工作量 |
|---|------|------|------|--------|
| P3-09 | sectorwatch | 行业轮动/政策驱动 → 行业配置 | `src/sectorwatch/` | 3 天 |
| P3-10 | macrotrack | GDP/CPI/PMI/利率 → 长期趋势 | `src/macrotrack/` | 3 天 |

---

## 核心技术栈一览

| 类别 | 技术 | 版本 | 最新状态 | 用途 |
|------|------|------|---------|------|
| **ML 框架** | LightGBM | >=4.5 | ✅ 2026活跃 | 主模型 |
| | XGBoost | >=2.1 | ✅ 2026活跃 | Ensemble |
| | CatBoost | >=1.2 | ✅ 2025 | Ensemble |
| **ML 工具** | shap | >=0.50 | ✅ 2026 | 可解释性 |
| | mlflow | >=2.20 | ✅ 2026活跃 | 实验管理 |
| | scikit-learn | >=1.5 | ✅ | CV/Pipeline |
| **组合优化** | skfolio | >=0.5 | ✅ 2026 | 组合优化 (sklearn 兼容) |
| | cvxpy | >=1.5 | ✅ | 凸优化求解 |
| **数据采集** | curl_cffi | >=0.7.4 | ✅ 2026活跃 | TLS 指纹伪装 |
| | Playwright | >=1.48 | ✅ 2026活跃 | 浏览器采集 |
| | akshare | >=1.14 | ✅ 持续更新 | A股免费数据 |
| | tavily-python | >=0.5 | ✅ 2026.03 | 搜索 API |
| **LLM** | openai SDK | >=1.60 | ✅ | DeepSeek/Qwen 统一客户端 |
| | pydantic | >=2.6 | ✅ | Schema 定义 |
| **NLP** | FinBERT2 | 2025 | ✅ 最新 | 中文金融情感 |
| | transformers | >=4.46 | ✅ | HuggingFace 推理 |
| **调度** | APScheduler | 3.10/4.0α | ✅ | 定时采集 |
| **事件** | blinker | >=1.9 | ✅ | 模块解耦 |
| **数据库** | PostgreSQL | >=16 | ✅ | JSONB 存储 |
| | SQLAlchemy | >=2.0 | ✅ | ORM |
| **统计** | statsmodels | >=0.14 | ✅ | 回归/中性化 |
| | scipy | >=1.12 | ✅ | 统计检验 |

---

## 对标参考项目

| 项目 | Star | 说明 | 链接 |
|------|------|------|------|
| **Microsoft Qlib** | 39.8k | AI 量化投资平台，统一管道设计标杆 | [github.com/microsoft/qlib](https://github.com/microsoft/qlib) |
| **Barra-CNE5** | - | A 股风险模型 Python 实现 | [github.com/xinyue6688/Barra-CNE5](https://github.com/xinyue6688/Barra-CNE5) |
| **Barra-CNE6-LightGBM** | - | Barra CNE6 + LGB 选股 | [github.com/finexsf/Barra-CNE6-LightGBM](https://github.com/finexsf/Barra-CNE6-LightGBM) |
| **skfolio** | - | scikit-learn 原生组合优化 | [skfolio.org](https://skfolio.org/) |
| **FinBERT2** | - | 最强中文金融 NLP 模型 | [github.com/valuesimplex/FinBERT](https://github.com/valuesimplex/FinBERT) |
| **Tavily Market Researcher** | - | AI 搜索驱动金融研究 | [github.com/tavily-ai/market-researcher](https://github.com/tavily-ai/market-researcher) |
| **Market Intelligence MVP** | - | MLflow+Airflow+FastAPI 金融 ML | [github.com/cdobratz/market-intelligence-mvp](https://github.com/cdobratz/market-intelligence-mvp) |

---

## 统计汇总

| 优先级 | 项目数 | 预估总工作量 | 核心价值 |
|--------|--------|-------------|---------|
| **P0** | 23 项 | ~20 天 | Bug 修复 + 三大新模块骨架 (datacollect/dataclean/sentiment) |
| **P1** | 19 项 | ~30 天 | 量化核心提升 (CV/监控/组合优化) + 模块完善 |
| **P2** | 17 项 | ~22 天 | 高级功能 + 扩展引擎 (个股雷达/资金流向/风险预警) |
| **P3** | 10 项 | ~18 天 | 长期可选 (SHAP/事件总线/FinBERT/行业轮动/宏观经济) |
| **合计** | **69 项** | **~90 天** | — |

---

## 建议执行顺序

```
Phase 0 (第 1-3 周):
  P0-01~03  修复已有代码 bug (ATR/中性化/预处理)
  P0-05~11  datacollect 核心 (HTTP客户端/限流/采集器/注册表)
  P0-12~19  dataclean 核心 (LLM客户端/Schema/清洗器)
  P0-20~23  sentiment 核心 (ORM/量价情绪/Profile/API)

Phase 1 (第 4-7 周):
  P0-04     OrchestratorBacktester (回测统一)
  P1-01~02  Purged CV + Walk-Forward 重训练
  P1-05~06  组合优化 + 风险归因
  P1-08~11  datacollect 完善 (路由/OpenClaw/调度)
  P1-12~15  dataclean 完善 (扩展Schema/注册表)
  P1-16~19  sentiment 完善 (合成指数/分类器/Profile集成)

Phase 2 (第 8-11 周):
  P1-03~04  因子/模型监控
  P1-07     换手率约束
  P2-01~06  量化增强 (滑点/XGB/绩效/PIT/多周期)
  P2-07~14  采集+清洗+情绪高级功能
  P2-15~17  扩展引擎 (个股雷达/资金/风险)

Phase 3 (第 12 周+):
  P3-01~10  按需选择实现
```
