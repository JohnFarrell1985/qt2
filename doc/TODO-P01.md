# P0.1: 数据采集 + 数据清洗 (爬虫攻防, 暂缓)

> 最后更新: 2026-04-05
>
> 15 项 | 预估工作量 ~9.5 天
>
> **说明**: 从 P0 拆出。数据采集涉及反爬对抗 (TLS 指纹/限流/Playwright), 耗时较长且不阻塞核心量化修复。
> 待 P0 Bug 修复和基础设施就绪后再启动。
>
> 返回总览: [TODO.md](TODO.md) | P0 已全部完成

---

## datacollect 模块 (7 项, ~5.5 天)

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
| **curl_cffi** | >=0.14 | ✅ 2026最新0.15.0 (+HTTP/3指纹) | TLS 指纹伪装核心。`impersonate="chrome"` 自动匹配最新 cipher suite/HTTP2/ALPN |
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
    def dedup_key(self, result: CollectResult) -> str:
        """幂等性去重 key, 基于 (source, date, identifier) 防止重复入库"""
        return f"{result.source}:{result.collected_at.date()}:{result.metadata.get('id', result.url)}"
```

**幂等性设计 (架构审查新增):**
- 所有采集器的 `collect()` 结果通过 `dedup_key()` 去重
- 入库使用 `INSERT ON CONFLICT DO UPDATE` (UPSERT) 而非 INSERT
- 采集日志记录 "最后成功采集日期", 支持断点续采
- 若采集任务中途失败, 重新执行不会产生重复数据

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
| **akshare** | >=1.18 | ✅ 2026最新1.18.49 | 需 Python 3.9+，`pip install akshare --upgrade` |

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
| PostgreSQL JSONB | 16+ | ✅ | 存储灵活的元数据字段 |

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

## dataclean 模块 (8 项, ~4 天)

> 数据清洗是 datacollect 的直接下游, 无采集数据无法端到端验证, 一并暂缓。

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
| **openai** SDK | >=2.0 | ✅ 2026最新2.30.0 | DeepSeek/Qwen 均兼容此 SDK |
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
