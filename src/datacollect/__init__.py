"""datacollect — 数据采集模块

提供统一的外部数据源采集框架:
- SmartHttpClient: 带指纹模拟和重试的 HTTP 客户端
- TokenBucketLimiter: 令牌桶限流器
- BaseCollector / CollectResult / CollectTask: 采集器基类与数据结构
- AkshareCollector / TushareCollector / AdataCollector / EastmoneyCollector: 数据采集器
- FallbackDispatcher: 降级调度器
- DataSourceRegistry / DataSourceDef: 数据源注册中心
- CollectLog: 采集日志 ORM 模型
"""
from src.datacollect.base import BaseCollector, CollectResult, CollectTask
from src.datacollect.client import SmartHttpClient
from src.datacollect.collectors.adata_collector import AdataCollector
from src.datacollect.collectors.akshare_collector import AkshareCollector
from src.datacollect.collectors.baostock_collector import BaostockCollector
from src.datacollect.collectors.eastmoney_collector import EastmoneyCollector
from src.datacollect.collectors.pytdx_collector import PytdxCollector
from src.datacollect.collectors.tushare_collector import TushareCollector
from src.datacollect.dispatcher import FallbackDispatcher
from src.datacollect.models import CollectLog
from src.datacollect.rate_limiter import TokenBucketLimiter
from src.datacollect.registry import DataSourceDef, DataSourceRegistry

__all__ = [
    "AdataCollector",
    "AkshareCollector",
    "BaostockCollector",
    "BaseCollector",
    "CollectLog",
    "CollectResult",
    "CollectTask",
    "DataSourceDef",
    "DataSourceRegistry",
    "EastmoneyCollector",
    "FallbackDispatcher",
    "PytdxCollector",
    "SmartHttpClient",
    "TokenBucketLimiter",
    "TushareCollector",
]
