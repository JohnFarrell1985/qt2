# P0.1: 数据采集 + 数据清洗

> 最后更新: 2026-04-11
>
> 分两大阶段:
> - **Phase A — 数据采集基础设施 + 结构化行情数据**: 反爬/限流客户端 + 日线/ETF/财务/基本面/板块等核心数据，**优先完成**
> - **Phase B — LLM 数据清洗 (暂缓)**: 新闻/情绪/舆情的 LLM 结构化抽取，待 Phase A 完成后启动
>
> 返回总览: [TODO.md](TODO.md) | P0 已全部完成

---

## 采集基础设施 + 结构化行情数据采集 (17 项, ~13.5 天)

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

### A-i. 反爬 / 限流基础设施 (datacollect, 7 项, ~5.5 天)

> akshare 底层调用东方财富 API，限流极其严格。以下基础设施是所有 akshare 采集任务的前置依赖。

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