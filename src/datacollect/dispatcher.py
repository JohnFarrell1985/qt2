"""降级调度器 — 按数据类型自动尝试降级链中的数据源

FallbackDispatcher 根据 data_sources.json 配置的降级链,
依次尝试可用的数据源, 直到成功获取数据或全部失败。
"""
from __future__ import annotations

import sys
import time
from typing import Any

from src.common.logger import get_logger
from src.datacollect.base import BaseCollector, CollectResult, CollectTask
from src.datacollect.registry import DataSourceRegistry

logger = get_logger(__name__)

_DATA_TYPE_FUNC: dict[str, dict[str, str]] = {
    "stock_list": {
        "akshare": "stock_zh_a_spot_em",
        "baostock": "query_stock_basic",
        "tushare": "stock_basic",
        "adata": "stock_list",
        "eastmoney": "fetch_stock_list",
        "pytdx": "stock_list",
    },
    "daily_kline": {
        "akshare": "stock_zh_a_hist",
        "baostock": "daily_kline",
        "tushare": "daily",
        "adata": "daily_kline",
        "eastmoney": "fetch_kline",
        "pytdx": "daily_kline",
    },
    "index_daily": {
        "akshare": "stock_zh_index_daily_em",
        "baostock": "index_daily",
        "tushare": "index_daily",
        "eastmoney": "fetch_kline",
    },
    "minute_kline": {
        "baostock": "minute_kline",
        "pytdx": "minute_kline",
    },
    "financial": {
        "baostock": "financial",
        "akshare": "stock_financial_abstract_em",
        "tushare": "fina_indicator",
    },
    "etf": {
        "akshare": "fund_etf_spot_em",
        "tushare": "fund_daily",
        "adata": "etf",
    },
    "sector": {
        "akshare": "stock_board_industry_name_em",
        "adata": "sector",
        "eastmoney": "fetch_realtime",
    },
    "cb": {
        "akshare": "bond_cb_jsl",
    },
    "realtime": {
        "akshare": "stock_zh_a_spot_em",
        "adata": "realtime",
        "pytdx": "realtime",
        "eastmoney": "fetch_realtime",
    },
}


class FallbackDispatcher:
    """按数据类型自动尝试降级链中的数据源。

    Usage::

        dispatcher = FallbackDispatcher()
        result = dispatcher.fetch(
            "daily_kline",
            code="000001",
            start_date="20230101",
            end_date="20260101",
        )
    """

    def __init__(self, registry: DataSourceRegistry | None = None):
        self._registry = registry or DataSourceRegistry.from_json()
        self._collectors: dict[str, BaseCollector] = {}

    def _get_collector(self, source_name: str) -> BaseCollector | None:
        """延迟实例化并缓存指定数据源的采集器。

        通过 DataSourceDef.collector_class 动态导入并创建采集器实例。
        如果依赖包未安装或创建失败, 返回 None。
        """
        if source_name in self._collectors:
            return self._collectors[source_name]

        source_def = self._registry.get(source_name)
        if not source_def or not source_def.collector_class:
            return None

        if source_def.package:
            try:
                __import__(source_def.package)
            except ImportError:
                logger.debug(
                    "包 %s 未安装, 跳过 %s", source_def.package, source_name,
                )
                return None

        try:
            module_path, class_name = source_def.collector_class.rsplit(".", 1)
            module = __import__(module_path, fromlist=[class_name])
            cls = getattr(module, class_name)
            collector = cls()
            self._collectors[source_name] = collector
            return collector
        except Exception as e:
            logger.warning("创建 %s 采集器失败: %s", source_name, e)
            return None

    @staticmethod
    def _resolve_func_name(data_type: str, source_name: str) -> str | None:
        """根据 data_type 和 source_name 查找对应的采集函数名。"""
        type_map = _DATA_TYPE_FUNC.get(data_type)
        if type_map:
            return type_map.get(source_name)
        return None

    def fetch(self, data_type: str, **params: Any) -> CollectResult:
        """按降级链尝试获取数据。

        Args:
            data_type: 数据类型 (daily_kline, stock_list, index_daily, ...)
            **params: 传递给采集器的参数 (code, start_date, end_date 等)

        Returns:
            采集结果

        Raises:
            RuntimeError: 所有数据源都失败
        """
        chain = self._registry.get_fallback_chain(data_type)
        if not chain:
            raise RuntimeError(f"未配置 data_type={data_type} 的降级链")

        errors: list[tuple[str, str]] = []
        for source_name in chain:
            collector = self._get_collector(source_name)
            if collector is None:
                continue

            func_name = self._resolve_func_name(data_type, source_name)
            if not func_name:
                logger.debug(
                    "data_type=%s 未映射 source=%s 的函数名, 跳过",
                    data_type, source_name,
                )
                continue

            task = CollectTask(
                source=source_name,
                params={"func_name": func_name, **params},
            )
            try:
                t0 = time.monotonic()
                result = collector.collect(task)
                elapsed = (time.monotonic() - t0) * 1000

                if result.data is not None and (
                    not hasattr(result.data, "empty") or not result.data.empty
                ):
                    logger.info(
                        "fetch(%s) 通过 %s 成功 (%.0fms)",
                        data_type, source_name, elapsed,
                    )
                    return result

                logger.debug(
                    "fetch(%s) 通过 %s 返回空数据, 继续降级",
                    data_type, source_name,
                )
            except Exception as e:
                logger.warning(
                    "fetch(%s) 通过 %s 失败: %s", data_type, source_name, e,
                )
                errors.append((source_name, str(e)))

        raise RuntimeError(
            f"所有数据源均失败 (data_type={data_type}): "
            + ", ".join(f"{name}: {err}" for name, err in errors)
        )

    def check_availability(self) -> dict[str, bool]:
        """检查所有已启用数据源的健康状态。

        Returns:
            {source_name: is_healthy}
        """
        results: dict[str, bool] = {}
        for source_def in self._registry.list_enabled():
            collector = self._get_collector(source_def.name)
            if collector is None:
                results[source_def.name] = False
                continue
            try:
                results[source_def.name] = collector.health_check()
            except Exception:
                results[source_def.name] = False
        return results

    @property
    def registry(self) -> DataSourceRegistry:
        return self._registry


def _cli_check() -> None:
    """CLI: 检查所有已启用数据源的可用性。"""
    dispatcher = FallbackDispatcher()
    print("检查数据源可用性...")
    print("-" * 50)

    availability = dispatcher.check_availability()
    for name, healthy in availability.items():
        status = "OK" if healthy else "FAIL"
        source_def = dispatcher.registry.get(name)
        display = source_def.display_name if source_def else name
        print(f"  [{status:4s}] {display} ({name})")

    total = len(availability)
    ok_count = sum(1 for v in availability.values() if v)
    print("-" * 50)
    print(f"结果: {ok_count}/{total} 个数据源可用")


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and args[0] == "check":
        _cli_check()
    else:
        print("用法: python -m src.datacollect.dispatcher check")
        sys.exit(1)
