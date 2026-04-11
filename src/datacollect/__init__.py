"""datacollect — 数据采集模块

提供统一的外部数据源采集框架:
- SmartHttpClient / AsyncSmartHttpClient: HTTP 客户端 (同步/异步)
- TokenBucketLimiter / AsyncTokenBucketLimiter: 令牌桶限流器 (同步/异步)
- BaseCollector / CollectResult / CollectTask / StreamResult: 采集器基类与数据结构
- AdaptiveLimiter / CircuitBreaker / AntiCrawlSentinel: 反爬基础设施
- SourceHealthDashboard: 数据源健康仪表盘
- DataValidator: 数据质量校验层
- DeadLetterDAO / IdempotencyChecker: 死信队列 + 幂等性
- DataFreshnessMonitor: 数据新鲜度监控
- AsyncCollectEngine: 异步采集引擎 (双层 Semaphore + Pipeline)
- ProxyPoolManager: 代理 IP 轮换
- WatchlistSync / WatchlistIntelCollector: 自选股同步与情报采集
- AkshareCollector / TushareCollector / ... : A 股数据采集器
- YfinanceCollector / SinaGlobalCollector / NewsRssCollector: Tier 2 全球情报采集器
- SentimentBridge: 全球市场快照 → SentimentDaily 桥接
- FallbackDispatcher: 降级调度器
- DataSourceRegistry / DataSourceDef: 数据源注册中心
- CollectLog / CollectDeadLetter: ORM 模型
"""
from src.datacollect.adaptive_limiter import AdaptiveLimiter
from src.datacollect.async_client import AsyncSmartHttpClient
from src.datacollect.async_engine import AsyncCollectEngine
from src.datacollect.async_rate_limiter import AsyncTokenBucketLimiter
from src.datacollect.base import BaseCollector, CollectResult, CollectTask, StreamResult
from src.datacollect.chunking import chunk_dataframe, log_memory_usage, release_dataframe
from src.datacollect.circuit_breaker import CircuitBreaker, CircuitState
from src.datacollect.client import SmartHttpClient
from src.datacollect.collectors.adata_collector import AdataCollector
from src.datacollect.collectors.akshare_collector import AkshareCollector
from src.datacollect.collectors.baostock_collector import BaostockCollector
from src.datacollect.collectors.eastmoney_collector import EastmoneyCollector
from src.datacollect.collectors.news_rss_collector import NewsRssCollector
from src.datacollect.collectors.pytdx_collector import PytdxCollector
from src.datacollect.collectors.sina_global_collector import SinaGlobalCollector
from src.datacollect.collectors.tushare_collector import TushareCollector
from src.datacollect.collectors.yfinance_collector import YfinanceCollector
from src.datacollect.dead_letter import DeadLetterDAO
from src.datacollect.dispatcher import FallbackDispatcher
from src.datacollect.freshness import DataFreshnessMonitor
from src.datacollect.health import SourceHealthDashboard, SourceHealthMetrics
from src.datacollect.idempotency import IdempotencyChecker
from src.datacollect.models import CollectDeadLetter, CollectLog
from src.datacollect.proxy_pool import ProxyConfig, ProxyPoolManager
from src.datacollect.rate_limiter import TokenBucketLimiter
from src.datacollect.registry import DataSourceDef, DataSourceRegistry
from src.datacollect.sentinel import AntiCrawlSentinel, ResponseCheck, SentinelVerdict
from src.datacollect.sentiment_bridge import SentimentBridge
from src.datacollect.validator import DataValidator, ValidationResult
from src.datacollect.watchlist_intel import WatchlistIntelCollector, WatchlistSync

__all__ = [
    "AdaptiveLimiter",
    "AdataCollector",
    "AkshareCollector",
    "AntiCrawlSentinel",
    "AsyncCollectEngine",
    "AsyncSmartHttpClient",
    "AsyncTokenBucketLimiter",
    "BaostockCollector",
    "BaseCollector",
    "CircuitBreaker",
    "CircuitState",
    "CollectDeadLetter",
    "CollectLog",
    "CollectResult",
    "CollectTask",
    "DataFreshnessMonitor",
    "DataSourceDef",
    "DataSourceRegistry",
    "DataValidator",
    "DeadLetterDAO",
    "EastmoneyCollector",
    "FallbackDispatcher",
    "NewsRssCollector",
    "IdempotencyChecker",
    "ProxyConfig",
    "ProxyPoolManager",
    "PytdxCollector",
    "ResponseCheck",
    "SentimentBridge",
    "SentinelVerdict",
    "SinaGlobalCollector",
    "SmartHttpClient",
    "SourceHealthDashboard",
    "SourceHealthMetrics",
    "StreamResult",
    "TokenBucketLimiter",
    "TushareCollector",
    "ValidationResult",
    "WatchlistIntelCollector",
    "WatchlistSync",
    "YfinanceCollector",
    "chunk_dataframe",
    "log_memory_usage",
    "release_dataframe",
]
