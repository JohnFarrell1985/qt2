"""datacollect.collectors — 各数据源采集器实现"""
from src.datacollect.collectors.adata_collector import AdataCollector
from src.datacollect.collectors.akshare_collector import AkshareCollector
from src.datacollect.collectors.baostock_collector import BaostockCollector
from src.datacollect.collectors.eastmoney_collector import EastmoneyCollector
from src.datacollect.collectors.pytdx_collector import PytdxCollector
from src.datacollect.collectors.tushare_collector import TushareCollector

__all__ = [
    "AdataCollector",
    "AkshareCollector",
    "BaostockCollector",
    "EastmoneyCollector",
    "PytdxCollector",
    "TushareCollector",
]
