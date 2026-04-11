# P0.1: 数据采集 + 数据清洗

> 最后更新: 2026-04-02
>
> A18-A23 为反爬加固 + 自选股情报, A24-A29 为架构 review 新增高优项 (数据质量/死信/幂等/新鲜度/配置统一/流式持久化),
> A30-A38 为高性能 review 新增项 (异步并发引擎/代理IP轮换/写缓冲/COPY批量写入/连接复用/背压/内存优化)
>
> 分两大阶段:
> - **Phase A — 数据采集基础设施 + 结构化行情数据**: 反爬/限流客户端 + 日线/ETF/财务/基本面/板块等核心数据，**优先完成**
> - **Phase B — LLM 数据清洗 (暂缓)**: 新闻/情绪/舆情的 LLM 结构化抽取，待 Phase A 完成后启动
>
> 返回总览: [TODO.md](TODO.md) | P0 已全部完成

---

## 采集基础设施 + 结构化行情数据采集 (38 项, ~29 天)

> **目标**: 构建反爬/限流基础设施，通过 MiniQMT (xtquant) 和 akshare 双源互补，将日线、ETF、
> 财务、基本面、板块等核心量化数据采集完整并入库 PostgreSQL。
>
> **为什么反爬/限流必须先做**:
> akshare 底层调用东方财富 API，2025-2026 年限流策略大幅收紧 — 连续调用 20 次即触发 IP 封禁。
> 5000+ 只股票 × 多种数据类型的批量采集 **必须** 有限流器 + 反爬客户端配合，否则跑不完就被封。
>
> **数据范围**:
> - 日线行情 (`stock_daily`): **近 10 年** (2016-01-01 ~ 今)
> - ETF / 可转债 / 指数 / 财务 / 基本面 / 板块: **近 3 年** (2023-01-01 ~ 今)
> - 分钟线 (`stock_minute`): **不采集历史**，仅盘中实时查看
>
> **数据源优先级**: MiniQMT (xtquant) > akshare > 东方财富 HTTP
>
> **现状**: 已从东方财富 dump 导入 stock_daily 15,695,552 行 (2000~2026)，
> 其余表 (ETF/财务/板块/实时) 均为空，需补全。

### A-i. 反爬 / 限流基础设施 (datacollect, 28 项, ~21 天)

> akshare 底层调用东方财富 API，限流极其严格。以下基础设施是所有 akshare 采集任务的前置依赖。
> A18-A23 为 2026-04 新增的反爬加固 + 自选股情报采集项。
> A24-A29 为架构 review 新增的数据质量 / 死信队列 / 幂等性 / 新鲜度监控 / 配置统一 / 流式持久化。
> A30-A38 为高性能 review 新增的异步并发 / 代理 IP 轮换 / 写缓冲 / COPY 批量写入 / 连接复用 / 背压 / 内存优化。

#### P0.1-A01: SmartHttpClient 反爬 HTTP 客户端

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
| **curl_cffi** | >=0.14 | ✅ 2026最新0.15.0 (+HTTP/3指纹) | TLS 指纹伪装核心。`impersonate="chrome"` 自动匹配最新 cipher suite/HTTP2/ALPN |
| fake-useragent | >=2.0 | ✅ | UA 轮换，支持浏览器类型过滤 |
| tenacity | >=9.0 | ✅ | 声明式重试策略 (指数退避 + 条件判断) |

**参考文档:**
- curl_cffi 官方: [github.com/lexiforest/curl_cffi](https://github.com/lexiforest/curl_cffi)
- [Web Scraping Without Getting Blocked: Using curl-cffi (2026)](https://www.blog.datahut.co/post/web-scraping-without-getting-blocked-curl-cffi)
- [Web Scraping Tools Comparison 2026](https://dev.to/vhub_systems_ed5641f65d59/web-scraping-tools-comparison-2026-requests-vs-curlcffi-vs-playwright-vs-scrapy-2fad)

**落地方案:**
```python
class SmartHttpClient:
    def __init__(self, config: DatacollectConfig):
        self.session = curl_cffi.requests.Session(impersonate="chrome")
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

#### P0.1-A02: TokenBucketLimiter 令牌桶限流器

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

#### P0.1-A03: BaseCollector 采集器抽象基类

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/base.py` |
| **工作量** | 0.5 天 |

**为什么要做:**
不同数据源 (akshare SDK、HTTP 爬虫、MiniQMT、Playwright) 的采集方式各不相同，但输出格式需统一。抽象基类确保所有采集器遵循相同的接口规范。

**落地方案:**
```python
@dataclass
class CollectResult:
    source: str           # "akshare", "qmt", "http", "browser"
    raw_text: str
    url: str | None
    collected_at: datetime
    metadata: dict

class BaseCollector(ABC):
    def __init__(self, client: SmartHttpClient, limiter: TokenBucketLimiter): ...
    @abstractmethod
    def collect(self, task: CollectTask) -> list[CollectResult]: ...
    @abstractmethod
    def health_check(self) -> bool: ...
```

**幂等性设计:**
- 入库使用 `INSERT ON CONFLICT DO UPDATE` (UPSERT) 而非 INSERT
- 采集日志记录 "最后成功采集日期"，支持断点续采

---

#### P0.1-A04: AkshareCollector

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/collectors/akshare_collector.py` |
| **工作量** | 1 天 |

**为什么要做:**
AKShare 是 MiniQMT 受限 API 的主要降级方案 (财务报表、板块资金、ETF 等)。封装 akshare 调用为标准采集器，配合限流器使用。

**技术选型:**

| 技术 | 版本 | 说明 |
|------|------|------|
| **akshare** | >=1.18 | 2026最新1.18.49，需 Python 3.9+ |

**落地方案:**
封装核心 akshare 接口，每次调用前通过 `TokenBucketLimiter.acquire()` 限流。
限流参数: 基础间隔 ≥5 秒 + ±20% 随机抖动，失败时指数退避最大等待 5 分钟。

---

#### P0.1-A05: 数据源注册表

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/registry.py` + `data_sources.json` |
| **工作量** | 1 天 |

**落地方案:**
JSON 配置驱动的注册表，新增/禁用数据源只需改配置文件，支持运行时热加载。

---

#### P0.1-A06: 采集日志 ORM

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/models.py` |
| **工作量** | 0.5 天 |

**落地方案:**
- 使用 PostgreSQL JSONB + `jsonb_path_ops` GIN 索引存储采集元数据
- 对 `collected_at` 字段创建 BRIN 索引 (时序数据最优)
- 历史数据 90 天自动归档

---

#### P0.1-A07: datacollect 模块初始化

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/__init__.py` + `src/common/config.py` |
| **工作量** | 0.5 天 |

**落地方案:**
在 `src/common/config.py` 中新增 `DatacollectConfig` (Pydantic Settings)，包含 akshare 限流参数、curl_cffi 代理设置、最大重试次数等，所有参数从 `.env` 读取。

---

#### P0.1-A18: AdaptiveLimiter 自适应限流器

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/adaptive_limiter.py` |
| **工作量** | 1 天 |

**为什么要做:**
静态限流间隔无法应对数据源动态变化的反爬策略。某些源在交易时段限流更严格，某些源在集中访问时临时加强封禁。需要根据实时反馈（429/403 比例、响应延迟、超时率）动态调整限流参数，遭遇限流自动减速，恢复正常后逐步加速。

**落地方案:**
- 滑动窗口 (5 分钟) 采集遥测指标: `success_rate`, `block_rate` (403/429), `avg_latency`, `timeout_rate`
- 动态调整规则: block_rate > 10% → 间隔 ×2; > 5% → ×1.5; avg_latency > 5s → ×1.3; 全部正常 10min → ×0.8 (不低于基线)
- 解析 `Retry-After` 响应头，尊重服务端指令
- 每个域名独立的 `AdaptiveLimiter` 实例，互不影响

**参考:**
- [ScrapingAnt — Adaptive Throttling Using Live Telemetry](https://scrapingant.com/blog/adaptive-throttling-using-live-telemetry-to-keep-scrapers)

---

#### P0.1-A19: CircuitBreaker 熔断器

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/circuit_breaker.py` |
| **工作量** | 0.5 天 |

**为什么要做:**
当某个数据源持续失败时，如果不停重试会浪费配额并可能触发更严厉的封禁。熔断器自动切断失败源的请求，等待 cooldown 后探测恢复，与 FallbackDispatcher 联动实现自动降级。

**落地方案:**
- 三态模型: CLOSED (正常) → OPEN (熔断, 连续 5 次失败) → HALF_OPEN (cooldown 5min 后探测)
- 探测成功 2 次 → 恢复 CLOSED; 探测失败 → 回到 OPEN, cooldown 翻倍
- 与 FallbackDispatcher 联动: 源 A 熔断 → 自动跳过 A, 使用 fallback chain 中的下一源

**参考:**
- [Scrapfly — Automatic Failover Strategies](https://scrapfly.io/blog/posts/automatic-failover-strategies-for-reliable-data-extraction)

---

#### P0.1-A20: AntiCrawlSentinel 卡顿侦测哨兵

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/sentinel.py` |
| **工作量** | 1 天 |

**为什么要做:**
传统方案"重试 3 次再降级"浪费时间。需要在第一次侦测到反爬信号时就立即中止当前源所有排队请求，熔断该源，切换到下一个数据源。

**侦测信号:**

| 信号 | 阈值 | 判定 |
|------|------|------|
| 单次 latency > 10s | 1 次 | 疑似卡顿 |
| 连续 2 次 latency > 5s | 2 次滑窗 | 确认卡顿 |
| 收到 429/403 | 1 次 | 确认反爬 |
| 200 但内容为空/验证码页 | 1 次 | 软封禁 |
| 连续 2 次 timeout | 2 次 | 源完全不可用 |

**落地方案:**
- 每次请求后 Sentinel 实时检查响应
- 侦测到反爬 → `CircuitBreaker.force_open()` + `FallbackDispatcher.skip_source()` → 即时切到下一源
- 软封禁检测: 200 但响应体 <50 字节 或包含 "验证码"/"captcha"/"请稍后再试" 等关键词
- 集成到 `SmartHttpClient`: 每次请求后自动调用 `sentinel.check_response()`

---

#### P0.1-A21: SourceHealth 数据源健康仪表盘

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/health.py` |
| **工作量** | 0.5 天 |

**为什么要做:**
需要对所有数据源的实时状态有全局视野，供 FallbackDispatcher 做智能排序、供运维做告警、供审计做事后分析。

**落地方案:**
- `SourceHealth` 数据类: total_requests / success_count / block_count / timeout_count / avg_latency_ms / circuit_state / current_interval
- `health_score` 属性 (0-100): success_rate × 60 + 低延迟加分 20 + 熔断状态加分 20
- FallbackDispatcher 按 health_score 排序，优先使用最健康的源
- API 端点 `GET /api/datacollect/health` 查看各源状态
- 凌晨 3:00 定时探活: 对所有数据源做 health_check，提前发现不可用源

---

#### P0.1-A22: WatchlistSync 自选股同步器

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/watchlist_intel.py` |
| **ORM** | 需新增 `WatchlistStock` + `WatchlistIntel` 模型 |
| **工作量** | 1 天 |

**为什么要做:**
MiniQMT 支持通过 `xtdata.get_stock_list_in_sector("我的自选")` 读取自选股列表。自选股是用户重点关注的标的，需要针对性地采集个股新闻、公告、讨论热度、资金异动等情报数据，为后续 P2 阶段的个股雷达 (`stockradar`) 提供数据。

**定位 (与 stockradar 的关系):**
- WatchlistIntel 在**数据采集层** (`datacollect`)，仅负责采集原始数据 + 落盘
- stockradar 在**分析引擎层** (`src/stockradar/`, P2-15)，消费 WatchlistIntel 的数据做 LLM 结构化抽取 (利好/利空/事件类型/影响幅度)
- 两者是上下游关系，不重复

**落地方案:**
- `WatchlistSync.sync()`: 每 2 小时从 QMT 拉取自选股，与 DB 做差异检测 (新增/移除)
- `WatchlistStock` ORM: code, name, added_at, removed_at, is_active
- QMT 断连时从 DB 最后快照读取; 支持 CSV/JSON 手动导入

---

#### P0.1-A23: WatchlistIntelCollector 自选股情报采集

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/watchlist_intel.py` (扩展) |
| **ORM** | `WatchlistIntel` (code, intel_type, title, content, source, raw_data, collected_at) |
| **工作量** | 1 天 |

**为什么要做:**
自选股情报是个股雷达 (P2) 的数据基础。P0.1 阶段先把原始数据采集到位，P2 阶段 stockradar 再用 LLM 做深度分析。

**采集内容:**

| 情报类型 | 数据源 (fallback) | 频率 |
|---------|-----------------|------|
| 个股新闻 | RSS → 东财个股资讯 HTTP → Tavily 搜索 | 每 2 小时 |
| 公司公告 | 东财公告 API → akshare → 巨潮资讯网 | 每日 1 次 |
| 雪球讨论 | OpenClaw → 雪球 API | 每日 2 次 |
| 资金异动 | efinance 龙虎榜 → akshare → tushare | 每日 1 次 |

**落地方案:**
- `WatchlistIntel` ORM: 存储原始情报，不做 NLP 分析
- 新增股票时**立即触发**该股情报采集 (不等待定时任务)
- APScheduler 集成: 盘前/午间/盘后/晚间各采集一轮

---

#### P0.1-A24: DataValidator 数据质量校验层

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/validator.py` |
| **工作量** | 1 天 |

**为什么要做:**
"Garbage in, garbage out" — 如果 akshare 返回缺失字段、类型错误或异常值 (如价格为负/成交量为空), 会静默流入后续 ML 训练, 导致不可预期的结果。需要在数据入库前增加校验层。

**校验层级:**

| 层级 | 校验内容 | 示例 |
|------|---------|------|
| Schema 层 | 字段类型、非空、唯一约束 | code 必须匹配 `^\d{6}\.(SH|SZ|BJ)$` |
| 业务规则层 | 价格/量/日期逻辑 | `open > 0`, `high >= low`, `volume >= 0`, 日期连续 |
| 统计层 | 异常值检测 | 日涨幅 \|pct_change\| < 22% (科创板), Z-score \|z\| < 10 |

**落地方案:**
```python
class DataValidator:
    def validate(self, df: pd.DataFrame, data_type: str) -> ValidationResult:
        schema = self._get_schema(data_type)
        errors = []
        errors.extend(self._check_schema(df, schema))
        errors.extend(self._check_business_rules(df, data_type))
        errors.extend(self._check_statistical(df))
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            rows_checked=len(df),
            rows_invalid=len(set(e.row_idx for e in errors)),
        )
```
集成到 `BaseCollector.collect()` 后处理: 采集完成后自动校验, 异常行写入告警日志, 严重异常 (如空 DataFrame) 阻止入库。

---

#### P0.1-A25: collect_dead_letter 死信队列

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/models.py` (扩展 ORM) |
| **工作量** | 0.5 天 |

**为什么要做:**
当采集任务失败 (反爬、超时、数据源异常) 后, 当前仅记录日志, 失败请求丢失无法追溯。死信队列将失败请求持久化到 DB, 支持事后分析和定时重放, 确保数据最终一致性。

**落地方案:**
```python
class CollectDeadLetter(Base):
    __tablename__ = "collect_dead_letter"

    id = Column(Integer, primary_key=True)
    task_id = Column(String(100), nullable=False)
    source = Column(String(50), nullable=False)
    data_type = Column(String(50), nullable=False)
    error_type = Column(String(50), nullable=False)  # timeout / blocked / parse_error / etc
    error_msg = Column(Text)
    payload = Column(JSONB)           # 原始任务参数, 用于重放
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    next_retry_at = Column(DateTime)  # 指数退避: base * 2^retry_count
    created_at = Column(DateTime, default=func.now())
    resolved_at = Column(DateTime)    # 重放成功后标记
```
- APScheduler 凌晨 2:00 定时任务: 扫描 `resolved_at IS NULL AND retry_count < max_retries` 的死信, 按 `next_retry_at` 排序重放
- 重放成功 → 标记 `resolved_at`; 重放失败 → `retry_count += 1`, 更新 `next_retry_at`

---

#### P0.1-A26: CollectTask 幂等性

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/base.py` + `models.py` |
| **工作量** | 0.5 天 |

**为什么要做:**
调度器可能因异常重启而重复提交相同采集任务, 导致同一天的数据被采集多次、重复入库。幂等性保证 "同一任务无论执行几次, 结果相同"。

**落地方案:**
```python
@dataclass
class CollectTask:
    source: str
    data_type: str
    params: dict
    idempotency_key: str = ""  # hash(source + data_type + date + sorted(params))

    def __post_init__(self):
        if not self.idempotency_key:
            raw = f"{self.source}:{self.data_type}:{self.params}"
            self.idempotency_key = hashlib.sha256(raw.encode()).hexdigest()[:16]
```
- DB 唯一约束: `UNIQUE(idempotency_key)` on `collect_log` 表
- 调度层去重: 提交任务前查询 `SELECT 1 FROM collect_log WHERE idempotency_key = ? AND status = 'success' AND created_at > NOW() - INTERVAL '24h'`, 存在则跳过
- 入库使用 `INSERT ON CONFLICT (idempotency_key) DO NOTHING`

---

#### P0.1-A27: DataFreshnessMonitor 数据新鲜度监控

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/freshness.py` |
| **工作量** | 0.5 天 |

**为什么要做:**
如果某张表的数据因采集失败/源不可用而滞后多天, 下游因子计算和策略信号会基于过期数据做出错误决策。需要主动监控数据新鲜度, 滞后超过阈值时告警。

**落地方案:**
```python
from exchange_calendars import get_calendar

class DataFreshnessMonitor:
    CORE_TABLES = {
        "stock_daily": 1,       # 允许滞后 1 个交易日
        "market_index": 1,
        "sector_data": 2,
        "stock_financial_report": 30,  # 财报季度更新
    }

    def __init__(self):
        self.calendar = get_calendar("XSHG")  # A 股交易日历

    def check_all(self) -> list[FreshnessAlert]:
        alerts = []
        today = datetime.date.today()
        if not self.calendar.is_session(today):
            return []  # 非交易日跳过
        for table, max_lag in self.CORE_TABLES.items():
            latest = db.execute(f"SELECT MAX(trade_date) FROM {table}").scalar()
            lag = self._trading_days_between(latest, today)
            if lag > max_lag:
                alerts.append(FreshnessAlert(table=table, lag=lag, threshold=max_lag))
        return alerts
```
- 每日 16:30 (收盘后) 执行新鲜度检查
- 滞后超过阈值 → 写入日志 + 推送告警 (P4 告警管线对接)
- 依赖: `exchange_calendars` 库

---

#### P0.1-A28: data_sources.json 配置统一

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/data_sources.json` (扩展) |
| **工作量** | 0.5 天 |

**为什么要做:**
当前部分数据源的函数映射硬编码在 Python 字典 `_DATA_TYPE_FUNC` 中, 新增/修改数据源需要改代码。统一到 `data_sources.json` 后, 所有数据源配置集中管理, 新增数据源只需改 JSON, 不改代码。

**落地方案:**

在现有 `data_sources.json` 中扩展每个数据类型的条目:
```json
{
  "stock_daily": {
    "description": "A股日线行情",
    "sources": [
      {
        "name": "qmt",
        "priority": 1,
        "module": "src.datacollect.collectors.xtdata_collector",
        "function": "download_stock_daily",
        "rate_limit": null
      },
      {
        "name": "akshare",
        "priority": 2,
        "module": "src.datacollect.collectors.akshare_collector",
        "function": "stock_zh_a_hist",
        "rate_limit": {"domain": "eastmoney.com", "interval": 7.0}
      }
    ]
  }
}
```
- `registry.py` 在初始化时从 JSON 加载, 替代硬编码映射
- 支持运行时热重载: 修改 JSON 后无需重启

---

#### P0.1-A29: BaseCollector.collect_stream() 流式持久化

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/base.py` (扩展) |
| **工作量** | 0.5 天 |

**为什么要做:**
全量采集 5000+ 只股票时, 如果在内存中攒完所有数据再一次性入库, 存在两个风险: (1) 内存溢出, (2) 中途失败导致已采集的数据全部丢失。流式持久化每处理一批就立即入库, 配合 A26 幂等性, 中途失败后可断点续采。

**落地方案:**
```python
class BaseCollector(ABC):
    STREAM_BATCH_SIZE = 100  # 每 100 只股票入库一次

    async def collect_stream(self, tasks: list[CollectTask]) -> StreamResult:
        total, success, failed = len(tasks), 0, 0
        for batch in chunked(tasks, self.STREAM_BATCH_SIZE):
            results = await asyncio.gather(
                *[self.collect(t) for t in batch],
                return_exceptions=True,
            )
            to_persist = []
            for task, result in zip(batch, results):
                if isinstance(result, Exception):
                    failed += 1
                    await self._enqueue_dead_letter(task, result)
                else:
                    success += 1
                    to_persist.extend(result)
            if to_persist:
                await self._persist_batch(to_persist)
            logger.info("stream_progress",
                total=total, success=success, failed=failed,
                batch_size=len(batch))
        return StreamResult(total=total, success=success, failed=failed)
```
- 与 A25 死信队列联动: 单只股票失败不影响整体, 失败任务进入死信队列
- 与 A26 幂等性联动: 重启后跳过已成功入库的数据

---

#### P0.1-A30: AsyncCollectEngine 异步采集引擎

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/async_engine.py` |
| **工作量** | 2 天 |

**为什么要做:**
当前 `FallbackDispatcher.fetch()` 是**全同步顺序执行** — 采集 5000+ 只股票时逐只串行, 单只耗时 5s 则总耗时 ~7 小时。需要引入 asyncio 协程并发, 跨不同标的同时采集, 大幅缩短总耗时。

**核心矛盾: 并发 vs 反爬**

对同一数据源的并发请求 (即使是不同股票) 会同时建立多条 TCP 连接到目标服务器, 触发 IP 级别的反爬检测。解决方案是**双层 Semaphore + Per-IP 速率限制器**三重防护:

| 层级 | 机制 | 目的 | 示例值 |
|------|------|------|--------|
| 全局 Semaphore | `asyncio.Semaphore(total)` | 系统总并发上限 | total=50 |
| Per-Source Semaphore | `asyncio.Semaphore(per_source)` | 单数据源最大并发 TCP 连接数 | akshare=2, QMT=50 |
| Per-Domain Rate Limiter (A32) | `AsyncTokenBucketLimiter` | 每秒请求频率上限 | akshare=0.15/s |

即使 50 个协程同时运行, 对 akshare 最多 2 条并发连接, 且受速率限制器约束 (每 7s 才发 1 个请求)。第 2 个线程只是在第 1 个线程等待限流 sleep 时预加载下一个任务。

**推荐 per-source 并发默认值** (通过 `data_sources.json` 的 `max_concurrent` 字段配置):

| 数据源 | max_concurrent | 理由 |
|--------|---------------|------|
| akshare | 2 | eastmoney 反爬极严; 2 线程 = 1 活跃 + 1 预加载 |
| eastmoney (HTTP) | 3 | 直接 HTTP, curl_cffi TLS 指纹辅助 |
| tushare | 5 | 官方 Token API, 限流按 Token 计 |
| baostock | 3 | 登录式会话, 中等限流 |
| QMT (xtquant) | 50 | 本地 SDK, 无网络反爬 |
| pytdx | 5 | TCP 协议, 反爬弱但服务器容量有限 |
| adata | 3 | 类似 akshare 模式 |

**SDK 适配策略:**

| 类型 | 适配方式 | 说明 |
|------|---------|------|
| 同步 SDK (akshare/baostock/pytdx) | `asyncio.to_thread()` 包装 | 每个并发占用 1 个 OS 线程 |
| 异步 HTTP (eastmoney) | `curl_cffi.AsyncSession` 原生 async | 无线程开销, 连接池复用 |
| 本地 SDK (QMT) | `asyncio.to_thread()` 或直接调用 | 无反爬, 可最大并发 |

**落地方案:**
```python
class AsyncCollectEngine:
    def __init__(self, registry: DataSourceRegistry):
        self._global_sem = asyncio.Semaphore(50)
        self._source_sems: dict[str, asyncio.Semaphore] = {
            src.name: asyncio.Semaphore(src.max_concurrent)
            for src in registry.list_enabled()
        }

    async def collect_all(self, tasks: list[CollectTask]) -> AsyncIterator[CollectResult]:
        async def _collect_one(task: CollectTask):
            source_sem = self._source_sems.get(task.source, self._global_sem)
            async with self._global_sem:
                async with source_sem:
                    return await asyncio.to_thread(self._collector.collect, task)

        for coro in asyncio.as_completed([_collect_one(t) for t in tasks]):
            yield await coro
```

**性能预估:**

| 场景 | 当前 | 优化后 | 提升 |
|------|------|--------|------|
| 5000 股日线 (akshare, 单 IP) | ~7h | ~3.5h (per-source=2) | 2x |
| 5000 股日线 (akshare, 10 代理 IP, A38) | ~7h | ~55min | 7.6x |
| 5000 股日线 (QMT 本地 SDK) | ~7h | ~8min (per-source=50) | 50x |

---

#### P0.1-A31: AsyncSmartHttpClient 异步 HTTP 客户端

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/async_client.py` |
| **工作量** | 0.5 天 |

**为什么要做:**
当前 `SmartHttpClient` 基于同步 `curl_cffi.requests.Session`, 每个线程需要独立 Session (`threading.local()`), 线程数量受限。`curl_cffi` 原生支持 `AsyncSession`, 可以在 asyncio 事件循环中直接使用, 单线程即可处理大量并发连接, 同时保留 TLS 指纹伪装能力。

**落地方案:**
```python
from curl_cffi import AsyncSession

class AsyncSmartHttpClient:
    def __init__(self, impersonate: str = "chrome", proxy_pool: ProxyPoolManager | None = None):
        self._session = AsyncSession(impersonate=impersonate)
        self._proxy_pool = proxy_pool
        self._retry = tenacity.AsyncRetrying(
            stop=stop_after_attempt(3),
            wait=wait_exponential_jitter(exp_base=2, jitter=2),
            retry=retry_if_exception_type((ConnectionError, TimeoutError, OSError)),
        )

    async def get(self, url: str, **kwargs) -> Response:
        proxy = await self._proxy_pool.acquire(domain) if self._proxy_pool else None
        async for attempt in self._retry:
            with attempt:
                resp = await self._session.get(url, proxy=proxy, **kwargs)
                resp.raise_for_status()
                return resp

    async def close(self):
        await self._session.close()
```

- `tenacity` 原生支持 `AsyncRetrying`, 无需额外适配
- 单个 `AsyncSession` 实例即可处理所有并发请求 (无需 `threading.local()`)
- 与 A38 ProxyPoolManager 集成: 每个请求传入不同的 proxy 参数

---

#### P0.1-A32: AsyncTokenBucketLimiter 异步限流器

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/async_rate_limiter.py` |
| **工作量** | 0.5 天 |

**为什么要做:**
当前 `TokenBucketLimiter.acquire()` 使用 `time.sleep()` 阻塞整个线程 — 在 asyncio 事件循环中会阻塞所有协程。需要替换为 `await asyncio.sleep()` 的非阻塞版本。

**落地方案:**
```python
class AsyncTokenBucketLimiter:
    def __init__(self, rate: float, burst: int, jitter_pct: float = 0.2):
        self._rate = rate
        self._burst = burst
        self._jitter_pct = jitter_pct
        self._tokens = float(burst)
        self._last_refill = asyncio.get_event_loop().time()
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return True
                wait = self._wait_seconds()
            await asyncio.sleep(wait)

    @classmethod
    def for_domain(cls, domain: str, rate: float, burst: int) -> "AsyncTokenBucketLimiter":
        ...
```
- `threading.Lock` → `asyncio.Lock`
- `time.sleep()` → `await asyncio.sleep()`
- `time.monotonic()` → `loop.time()`
- Per-domain 单例模式保留
- 也可考虑引入 `aiolimiter>=1.2` 库 (Leaky Bucket, 生产验证)

---

#### P0.1-A33: WriteBehindBuffer 写缓冲层

| 属性 | 内容 |
|------|------|
| **模块** | data |
| **文件** | `src/data/write_buffer.py` |
| **工作量** | 1 天 |

**为什么要做:**
当前采集与持久化紧耦合 — 采集一只股票, 立即写入 DB, 再采集下一只。DB 写入延迟 (锁竞争/vacuum/WAL) 直接拖慢采集速度。WriteBehindBuffer 在采集和 DB 之间插入异步缓冲层, 让采集协程不必等待 DB 写入完成。

**写缓冲 vs 写穿透对比:**

| 模式 | 写延迟 | 一致性 | 数据安全 |
|------|--------|--------|---------|
| Write-Through (当前) | 高 (等 DB) | 强一致 | 高 |
| Write-Behind (目标) | 极低 (只写缓冲) | 最终一致 | 配合死信队列 (A25) 保证 |

**落地方案:**
```python
class WriteBehindBuffer:
    def __init__(self, flush_interval: float = 1.0, batch_size: int = 5000):
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._flush_interval = flush_interval
        self._batch_size = batch_size
        self._running = False

    async def put(self, model: type, records: list[dict]):
        await self._queue.put((model, records))

    async def start(self):
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())

    async def _flush_loop(self):
        while self._running:
            batch = await self._drain_batch()
            if batch:
                await self._bulk_persist(batch)

    async def _drain_batch(self) -> list:
        batch = []
        try:
            while len(batch) < self._batch_size:
                item = await asyncio.wait_for(
                    self._queue.get(), timeout=self._flush_interval
                )
                batch.append(item)
        except asyncio.TimeoutError:
            pass
        return batch

    async def stop(self):
        self._running = False
        remaining = []
        while not self._queue.empty():
            remaining.append(self._queue.get_nowait())
        if remaining:
            await self._bulk_persist(remaining)
```
- `asyncio.Queue(maxsize=200)` 限制缓冲深度, 满时自动对采集端施加背压
- 后台 flusher 定时 drain: 满 `batch_size` 条或超时 `flush_interval` 秒即写入
- 优雅关闭: `stop()` 时 drain 剩余数据
- 崩溃安全: 配合 A25 死信队列, 未成功持久化的数据可通过重放恢复

---

#### P0.1-A34: BulkWriter COPY 协议 + 优化批量写入

| 属性 | 内容 |
|------|------|
| **模块** | data |
| **文件** | `src/data/bulk_writer.py` |
| **工作量** | 1 天 |

**为什么要做:**
当前 `market_data.py` 使用 `INSERT ... ON CONFLICT` (batch_size=1000), 性能基准约 ~5000 rows/sec。PostgreSQL COPY 协议跳过 SQL 解析和事务开销, 基准测试 (asyncpg) 可达 **~260 万 rows/sec**, 提升 400x+。但 COPY 不支持冲突处理, 需要双模式设计。

**性能对比 (PostgreSQL 100K 行):**

| 方法 | 相对速度 |
|------|---------|
| PostgreSQL COPY (asyncpg) | ~240x |
| Core `insert().values()` | ~40x |
| ORM 2.0 `session.execute(insert())` | ~20x |
| `session.add()` 循环 | 1x (基准) |

**双模式设计:**

| 模式 | 适用场景 | 实现 |
|------|---------|------|
| `copy` | 初始全量加载 (空表) | `asyncpg.copy_records_to_table()` |
| `upsert` | 增量同步 (有冲突) | `INSERT ON CONFLICT` batch_size=5000-10000 |

**落地方案:**
```python
class BulkWriter:
    async def write(self, model: type, records: list[dict], mode: str = "upsert"):
        if mode == "copy" and await self._is_table_empty(model):
            await self._copy_insert(model, records)
        else:
            await self._batch_upsert(model, records, batch_size=5000)

    async def _copy_insert(self, model: type, records: list[dict]):
        """COPY 协议批量插入 (仅空表, ~260万行/秒)"""
        table = model.__tablename__
        columns = list(records[0].keys())
        rows = [tuple(r[c] for c in columns) for r in records]
        async with self._pool.acquire() as conn:
            await conn.copy_records_to_table(table, records=rows, columns=columns)

    async def _batch_upsert(self, model: type, records: list[dict], batch_size: int = 5000):
        """分批 UPSERT (支持冲突处理, 每批独立事务)"""
        for i in range(0, len(records), batch_size):
            batch = records[i:i + batch_size]
            async with self._session_factory() as session:
                stmt = insert(model).values(batch)
                stmt = stmt.on_conflict_do_update(...)
                await session.execute(stmt)
                await session.commit()
```
- 关键改进: **每批独立事务** (取代当前整个 sync 一个大事务), 崩溃时仅丢失最后一批
- 增量模式 batch_size 从 1000 提升到 5000-10000
- 需要新增依赖: `asyncpg>=0.30` (COPY 协议 + 异步 PostgreSQL 驱动)

---

#### P0.1-A35: CollectorConnectionPool 采集器连接复用

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/collectors/baostock_collector.py` + `pytdx_collector.py` (改造) |
| **工作量** | 0.5 天 |

**为什么要做:**
`BaostockCollector` 每次查询都执行 `login()` + 业务 + `logout()` — TCP 连接 + 认证开销 ~30ms/次。5000 只股票累计浪费 ~2.5 分钟。`PytdxCollector` 同理, 每次 `connect()` + `disconnect()`。应在 Collector 初始化时建立连接, 全生命周期复用。

**落地方案:**
```python
class BaostockCollector(BaseCollector):
    def __init__(self, ...):
        super().__init__(...)
        self._logged_in = False

    def _ensure_login(self):
        if not self._logged_in:
            bs.login()
            self._logged_in = True

    def collect(self, task: CollectTask) -> CollectResult:
        self._ensure_login()
        ...  # 正常业务逻辑, 不再每次 login/logout

    def close(self):
        if self._logged_in:
            bs.logout()
            self._logged_in = False

class PytdxCollector(BaseCollector):
    def __init__(self, ...):
        super().__init__(...)
        self._api = TdxHq_API()
        self._connected = False

    def _ensure_connected(self):
        if not self._connected:
            self._api.connect(self._best_ip, self._port)
            self._connected = True

    def close(self):
        if self._connected:
            self._api.disconnect()
            self._connected = False
```
- 两者均实现 `__enter__`/`__exit__` (或 `__aenter__`/`__aexit__`) 用于 context manager
- 连接断开时自动重连 (检测 `ConnectionError` → reset flag → 下次调用 `_ensure_*`)
- `FallbackDispatcher` 在关闭时调用各 collector 的 `close()`

---

#### P0.1-A36: Pipeline 背压设计

| 属性 | 内容 |
|------|------|
| **模块** | datacollect + data |
| **文件** | `src/datacollect/async_engine.py` (扩展 A30) |
| **工作量** | 0.5 天 |

**为什么要做:**
异步管线中, 如果采集端 (生产者) 速度远超 DB 写入端 (消费者), 数据会在内存中无限堆积直至 OOM。背压 (Backpressure) 机制让慢的阶段自动反向限速快的阶段。

**三阶段异步管线:**

```
Stage 1: Fetch      ──► Queue(maxsize=50) ──►
Stage 2: Validate   ──► Queue(maxsize=100) ──►
Stage 3: Persist    (WriteBehindBuffer, A33)
```

| 阶段 | 并发控制 | 背压机制 |
|------|---------|---------|
| Fetch | 双层 Semaphore (A30) | Queue 满时 `put()` 自动阻塞 |
| Validate | DataValidator (A24) | Queue 满时自动阻塞 |
| Persist | WriteBehindBuffer (A33) | 批量写入, 失败进死信 (A25) |

当 DB (Stage 3) 变慢时:
1. Queue 2 填满 → Stage 2 的 `put()` 阻塞 → Stage 2 减速
2. Queue 1 填满 → Stage 1 的 `put()` 阻塞 → 采集减速
3. 采集减速 → Semaphore 槽位不释放 → 新任务暂停调度

**监控集成 (P4):**
- Queue 深度暴露为 Prometheus Gauge: `qt_pipeline_queue_depth{stage="fetch|validate|persist"}`
- 各阶段超时检测: `asyncio.wait_for(timeout=30)`, 超时触发告警

---

#### P0.1-A37: 内存高效分块处理

| 属性 | 内容 |
|------|------|
| **模块** | datacollect + data |
| **文件** | `src/datacollect/base.py` + `src/data/market_data.py` (改造) |
| **工作量** | 0.5 天 |

**为什么要做:**
当前每只股票的 DataFrame 全部加载到内存后再分批写入。分钟线数据单只股票可达数十万行, 5000 只同时在内存中会导致 OOM。需要限制峰值内存占用。

**落地方案:**
- 大 DataFrame (>100K 行) 在传递给 WriteBehindBuffer 前, 先按 chunk 拆分
- 每只股票持久化完成后显式 `del df` 释放引用
- 启用 `pandas.options.mode.copy_on_write = True` (pandas 2.0+), 减少 DataFrame 复制开销
- 每次采集后记录 `DataFrame.memory_usage(deep=True).sum()` 到日志, 监控内存趋势
- 分钟线数据保持 download_engine 的生成器模式, 一次只处理 1 只股票的数据

```python
CHUNK_THRESHOLD = 100_000

async def _persist_with_chunking(self, df: pd.DataFrame, model: type):
    if len(df) > CHUNK_THRESHOLD:
        for chunk in np.array_split(df, len(df) // CHUNK_THRESHOLD + 1):
            await self._write_buffer.put(model, chunk.to_dict("records"))
    else:
        await self._write_buffer.put(model, df.to_dict("records"))
    mem_mb = df.memory_usage(deep=True).sum() / 1024 / 1024
    logger.debug("persist_chunk", rows=len(df), memory_mb=f"{mem_mb:.1f}")
    del df
```

---

#### P0.1-A38: ProxyPoolManager 代理 IP 轮换

| 属性 | 内容 |
|------|------|
| **模块** | datacollect |
| **文件** | `src/datacollect/proxy_pool.py` (升级现有骨架) |
| **工作量** | 1.5 天 |

**为什么要做:**
不使用代理时, per-source 并发受限于单 IP 安全速率 (akshare=2 并发, 速率 0.15/s)。代理 IP 轮换让**每个并发协程通过不同出口 IP 访问**, 目标服务器看到的是 N 个独立用户低频访问, 从根本上突破单 IP 反爬限制。

**有效并发公式:** `实际并发 = min(代理IP数, per_source_cap) × 单IP安全速率`

例: 10 代理 IP × 0.15 req/s/IP = 1.5 req/s → 5000 只股票 ~55 分钟 (vs 单 IP 7h, **7.6x**)

**各采集器代理集成方式:**

| 采集器 | 集成方式 | 难度 |
|--------|---------|------|
| SmartHttpClient (eastmoney) | `AsyncSession.get(url, proxy=...)` per-request | 简单 |
| akshare | `AkshareConfig.set_proxies(proxy)` + per-thread 锁保护 | 中等 |
| tushare | 不需要 (Token API, 无 IP 反爬) | N/A |
| baostock/pytdx | 不适用 (TCP 协议, 非 HTTP) | N/A |
| QMT | 不需要 (本地 SDK) | N/A |

**落地方案:**
```python
class ProxyPoolManager:
    def __init__(self, proxies: list[ProxyConfig]):
        self._pool: deque[ProxyConfig] = deque(proxies)
        self._per_ip_limiters: dict[str, AsyncTokenBucketLimiter] = {}
        self._blacklist: set[str] = set()

    async def acquire(self, domain: str) -> ProxyConfig:
        """获取下一个健康代理, 附带独立的 per-IP 速率限制器"""
        for _ in range(len(self._pool)):
            proxy = self._pool[0]
            self._pool.rotate(-1)
            if proxy.ip not in self._blacklist:
                limiter = self._per_ip_limiters.setdefault(
                    f"{proxy.ip}:{domain}",
                    AsyncTokenBucketLimiter(rate=0.15, burst=1),
                )
                await limiter.acquire()
                return proxy
        raise AllProxiesBlacklisted()

    async def report_blocked(self, proxy: ProxyConfig):
        """标记代理被封, 冷却 10 分钟"""
        self._blacklist.add(proxy.ip)
        asyncio.get_event_loop().call_later(600, self._blacklist.discard, proxy.ip)
```

**akshare 代理轮换策略** (处理全局状态限制):
```python
async def _collect_akshare_with_proxy(self, task: CollectTask):
    proxy = await self._proxy_pool.acquire("eastmoney.com")
    try:
        def _sync_call():
            AkshareConfig.set_proxies(proxy.as_dict())
            return self._collector.collect(task)
        return await asyncio.to_thread(_sync_call)
    except (HTTPError, ConnectionError) as e:
        if is_blocked(e):
            await self._proxy_pool.report_blocked(proxy)
        raise
```

akshare 的 `AkshareConfig.set_proxies()` 是全局状态, 通过 A30 的 per-source Semaphore 序列化访问 — 每个并发槽持有不同代理, Semaphore 数量 = `min(代理数, 安全并发上限)`。

**代理源选型:**

| 提供商 | 类型 | 费用 | 适用场景 |
|--------|------|------|---------|
| 自建 VPS | 数据中心 IP | ~$5/月/IP | tushare 等宽松站点 |
| IPIDEA / Smartproxy | 住宅旋转 | ~$7-15/GB | eastmoney 等严格反爬 |
| 免费代理列表 | 混合 | 免费 | 不推荐 (不稳定) |

**配置 (`.env`):**
```bash
DATACOLLECT_PROXY_ENABLED=false              # 默认不启用, 按需开启
DATACOLLECT_PROXY_URLS=http://user:pass@p1:port,http://user:pass@p2:port,...
DATACOLLECT_PROXY_ROTATE_STRATEGY=round_robin  # round_robin | random | least_used
DATACOLLECT_PROXY_HEALTH_CHECK_INTERVAL=300   # 代理健康检查间隔 (秒)
DATACOLLECT_PROXY_BLACKLIST_COOLDOWN=600      # 被封代理冷却时间 (秒)
```

**优雅降级:** `PROXY_ENABLED=false` 或所有代理被封时, 自动回退到直连 + A30 低并发默认值 (per-source=2)。

---

### A-ii. 数据采集任务 (10 项, ~8 天)

> 以下任务依赖 A-i 的基础设施 (限流/反爬)。MiniQMT 直连不受限流影响，akshare 降级路径需要限流器。

#### P0.1-A08: 数据库级断点续传引擎

| 属性 | 内容 |
|------|------|
| **模块** | data |
| **文件** | `src/data/download_progress.py` |
| **ORM** | `StockDownloadProgress` (已就位) |
| **工作量** | 1.5 天 |
| **移植参考** | `A800/fin-r1-live/data-hub/history_downloader_with_resume.py` + `resume_manager.py` |

**为什么要做:**
5000+ 只股票 × 多种数据类型的全量下载不可能一次完成。当前 `download_engine.py` 的进度仅存在内存中，
进程重启即丢失。需要将 per-stock 进度持久化到 `stock_download_progress` 表，实现数据库级断点续传。

**落地方案:**
- `DownloadProgressDAO`: `init_progress`, `update_progress`, `mark_failed`, `get_incomplete_stocks`, `get_download_summary`
- 集成到现有 `DownloadEngine`，每只股票下载完成后更新进度表
- CLI 命令: `python -m src.data.download_progress status|resume|retry-failed|reset`
- 启动时自动检测未完成任务并续传

---

#### P0.1-A09: 股票列表与基本面采集

| 属性 | 内容 |
|------|------|
| **模块** | data |
| **文件** | `src/data/sync.py` (扩展) |
| **ORM** | `Stock` (已就位) |
| **工作量** | 0.5 天 |
| **数据源** | MiniQMT `get_stock_list_in_sector` + `get_instrument_detail` |

**目标:**
- 采集全 A 股列表 (SH/SZ/BJ) 写入 `stocks` 表
- 补全 `name`, `exchange`, `industry`, `sector`, `list_date`, `pe_ttm`, `pb`, `roe`, `market_cap`
- 当前 `stocks` 表为空，需全量初始化

**降级方案:** MiniQMT 不可用时用 akshare `stock_info_a_code_name` + `stock_individual_info_em`

---

#### P0.1-A10: 日线行情增量同步

| 属性 | 内容 |
|------|------|
| **模块** | data |
| **文件** | `src/data/market_data.py` (扩展) |
| **ORM** | `StockDaily` (已就位, 已有 15,695,552 行 dump 数据) |
| **工作量** | 0.5 天 |
| **数据源** | MiniQMT `download_history_data` + `get_market_data_ex` |

**目标:**
- dump 数据截止 2026-03-17，需增量补全至今
- 补全 `turnover_rate` 和 `amplitude` 字段 (dump 中为空)
- 后续每日收盘后自动增量同步 (配合 `scheduler.py`)
- 范围: 近 10 年 (已有数据回溯到 2000 年，超额完成)

**降级方案:** akshare `stock_zh_a_hist`

---

#### P0.1-A11: 大盘指数数据采集

| 属性 | 内容 |
|------|------|
| **模块** | data |
| **文件** | `src/data/market_data.py` (扩展) |
| **ORM** | `MarketIndex` (已就位, 当前 0 行) |
| **工作量** | 0.5 天 |
| **数据源** | MiniQMT `download_history_data` (指数代码) |

**目标:**
- 采集主要指数: 上证综指(000001.SH)、深证成指(399001.SZ)、沪深300(000300.SH)、
  中证500(000905.SH)、中证1000(000852.SH)、创业板指(399006.SZ)、科创50(000688.SH)
- 字段: OHLC + change + change_pct + volume + amount
- 范围: 近 3 年

**降级方案:** akshare `stock_zh_index_daily_em`

---

#### P0.1-A12: ETF 数据采集

| 属性 | 内容 |
|------|------|
| **模块** | data |
| **文件** | `src/data/cb_data.py` (扩展, 或新建 `src/data/etf_data.py`) |
| **ORM** | 需新增 `ETFInfo` + `ETFDaily` 模型 |
| **工作量** | 1 天 |
| **数据源** | MiniQMT `download_etf_info` + `download_history_data` |

**目标:**
- ETF 基础信息: 代码、名称、跟踪指数、管理费率、成立日期、最新规模
- ETF 日线行情: OHLCV + 折溢价率 + 净值
- 主要 ETF (~800 只): 沪深 300 ETF、中证 500 ETF、行业 ETF、跨境 ETF 等
- 范围: 近 3 年

**降级方案:** akshare `fund_etf_spot_em` + `fund_etf_hist_em`

**注意:** 华泰 MiniQMT 对 `download_etf_info` 返回 ErrorID 300000，需要用 akshare 兜底

---

#### P0.1-A13: 财务报表数据采集

| 属性 | 内容 |
|------|------|
| **模块** | data |
| **文件** | `src/data/financial_data.py` (扩展) |
| **ORM** | `StockFinancialReport` (已扩展至 35 字段, 当前 0 行) |
| **工作量** | 1 天 |
| **数据源** | MiniQMT `download_financial_data` / akshare |

**目标:**
- 资产负债表: 总资产/总负债/股东权益/流动资产/流动负债/存货/应收/货币资金/固定资产
- 利润表: 营收/营业利润/净利润/毛利/营业成本/三费/研发费用
- 现金流量表: 经营/投资/筹资现金流净额
- 衍生比率: 毛利率/净利率/ROE/ROA/资产负债率/流动比率/速动比率
- 范围: 近 3 年 (约 12 个季报周期)

**注意:** MiniQMT `download_financial_data` 在之前测试中极慢/阻塞，优先用 akshare:
- `ak.stock_financial_report_sina` (三大报表)
- `ak.stock_financial_analysis_indicator` (财务指标)

---

#### P0.1-A14: 财务分析指标采集

| 属性 | 内容 |
|------|------|
| **模块** | data |
| **文件** | `src/data/financial_data.py` (扩展) |
| **ORM** | `StockFinancialIndicator` (已扩展至 30 字段, 当前 0 行) |
| **工作量** | 0.5 天 |
| **数据源** | akshare `stock_financial_analysis_indicator` |

**目标:**
- 每股指标: EPS(基本/稀释)、BPS、DPS、每股经营现金流
- 盈利能力: ROE(加权/摊薄)、ROA、净利率、毛利率、核心利润率
- 营运能力: 总资产周转率、存货周转率/天数、应收周转率/天数
- 偿债能力: 资产负债率、产权比率、流动比率、速动比率、现金比率、利息保障倍数
- 成长能力: 营收增长率、净利润增长率、总资产增长率、净资产增长率
- 范围: 近 3 年

---

#### P0.1-A15: 板块行情数据采集

| 属性 | 内容 |
|------|------|
| **模块** | data |
| **文件** | 新建 `src/data/sector_market_data.py` |
| **ORM** | `SectorData` (已就位, 当前 0 行) |
| **工作量** | 1 天 |
| **数据源** | akshare `stock_board_industry_hist_em` / `stock_sector_fund_flow_rank` |

**目标:**
- 行业板块日行情: 板块名称、交易日、涨跌幅
- 板块资金流向: 净流入/净流出
- 板块领涨股
- 范围: 近 3 年
- 用途: 板块轮动因子、行业动量策略

**注意:** MiniQMT 的 `download_sector_data` 在测试中阻塞，使用 akshare 作为主数据源

---

#### P0.1-A16: 可转债数据补全

| 属性 | 内容 |
|------|------|
| **模块** | data |
| **文件** | `src/data/cb_data.py` (扩展) |
| **ORM** | `ConvertibleBond` + `CBDaily` (已就位, 当前 0 行) |
| **工作量** | 0.5 天 |
| **数据源** | MiniQMT `get_cb_info` + `download_history_data` |

**目标:**
- 可转债基础信息: 代码、名称、正股、转股价、评级、规模、转股溢价率
- 可转债日线行情: OHLCV
- 范围: 近 3 年 (当前存续约 500+ 只)

**降级方案:** akshare `bond_cb_jsl` + `bond_cb_redeem_jsl`

---

#### P0.1-A17: 实时行情快照采集

| 属性 | 内容 |
|------|------|
| **模块** | data |
| **文件** | 新建 `src/data/realtime_snapshot.py` |
| **ORM** | `StockRealtime` (已就位, 当前 0 行) |
| **工作量** | 1 天 |
| **数据源** | MiniQMT `get_full_tick` / `subscribe_quote` |

**目标:**
- 盘中定时 (每 30 秒 ~ 1 分钟) 采集全市场实时快照
- 字段: 价格/涨跌/成交量/振幅/换手率/涨速/5 分钟涨幅/市值/PE/PB
- 存储最近 5 个交易日快照，历史自动归档
- 用途: 盘中异动监控、实时因子计算、实盘信号触发

**注意:** 分钟线历史数据暂不采集。`stock_minute` 表仅用于盘中实时查看，不做历史回填。

---

### Phase A 数据覆盖汇总

| 数据类型 | 表名 | 历史范围 | 数据源 | 现状 |
|----------|------|---------|--------|------|
| 股票列表/基本面 | `stocks` | 全量快照 | MiniQMT / akshare | 0 行, 待采集 |
| 日线行情 | `stock_daily` | 10 年 (2016~) | MiniQMT / dump已有 | 15,695,552 行, 需增量补全 |
| 大盘指数 | `market_index` | 3 年 | MiniQMT / akshare | 0 行, 待采集 |
| ETF 信息+行情 | `etf_info` + `etf_daily` | 3 年 | MiniQMT / akshare | **需新增 ORM** |
| 财务报表 | `stock_financial_report` | 3 年 | akshare 优先 | 0 行, 待采集 |
| 财务指标 | `stock_financial_indicator` | 3 年 | akshare | 0 行, 待采集 |
| 板块行情 | `sector_data` | 3 年 | akshare | 0 行, 待采集 |
| 可转债 | `convertible_bond` + `cb_daily` | 3 年 | MiniQMT / akshare | 0 行, 待采集 |
| 实时快照 | `stock_realtime` | 最近 5 日 | MiniQMT 实时 | 0 行, 待实现 |
| 分钟线 | `stock_minute` | **不采集历史** | MiniQMT 盘中实时 | 仅实时查看 |
| 下载进度 | `stock_download_progress` | — | 引擎自动维护 | 5,489 行 (dump), 需接入引擎 |
| 自选股列表 | `watchlist_stocks` | 动态 (每日更新) | MiniQMT `我的自选` | **需新增 ORM**, A22 |
| 自选股情报 | `watchlist_intel` | 持续采集 | RSS/东财/雪球/efinance | **需新增 ORM**, A23 |