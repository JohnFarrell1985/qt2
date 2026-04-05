# P0: 紧急 / 基础 (Bug 修复 + 核心骨架)

> 最后更新: 2026-04-04
>
> 23 项 | 预估工作量 ~20 天
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
| 数据采集 | `src/datacollect/` | [doc/12-数据采集模块.md](12-数据采集模块.md) |
| 数据清洗 | `src/dataclean/` | [doc/13-数据清洗与LLM.md](13-数据清洗与LLM.md) |
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
