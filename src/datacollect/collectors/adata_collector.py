"""AData 数据采集器 — 多数据源融合, 动态代理

通过 BaseCollector 接口统一管理, 内置限流和错误处理。
adata 仅在方法内部延迟导入, CI 环境无需安装该 SDK。

AData 特点: 自动聚合东财、新浪、腾讯等多源数据, 内置代理切换。
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from src.common.config import settings
from src.common.logger import get_logger
from src.datacollect.base import BaseCollector, CollectResult, CollectTask
from src.datacollect.rate_limiter import TokenBucketLimiter

logger = get_logger(__name__)

_CFG = settings.datacollect


class AdataCollector(BaseCollector):
    """基于 AData 的 A 股数据采集器。

    AData 提供多数据源融合能力, 自动聚合东财、新浪、腾讯等数据源,
    支持动态代理切换, 无需 Token 即可使用。
    """

    SOURCE = "adata"

    def __init__(self, limiter: TokenBucketLimiter | None = None):
        if limiter is None:
            limiter = TokenBucketLimiter.for_domain(
                "adata",
                rate=_CFG.adata_rate,
                burst=_CFG.adata_burst,
            )
        super().__init__(limiter)

    def call_adata(self, module_path: str, method_name: str, **kwargs: Any) -> Any:
        """调用 adata API, 带限流控制。

        通过 module_path 逐级定位到目标模块, 然后调用指定方法。

        Args:
            module_path: 模块路径 (如 "stock.info", "stock.market")
            method_name: 方法名 (如 "all_code", "get_market")
            **kwargs: 传递给 adata 方法的参数

        Returns:
            adata 方法的返回值 (通常为 DataFrame)

        Raises:
            RuntimeError: adata 未安装
            AttributeError: 模块路径或方法名不存在
        """
        try:
            import adata
        except ImportError:
            raise RuntimeError("adata 未安装, 无法进行数据采集")

        obj: Any = adata
        for part in module_path.split("."):
            obj = getattr(obj, part)
        fn = getattr(obj, method_name)

        if self._limiter:
            self._limiter.acquire()

        t0 = time.monotonic()
        try:
            result = fn(**kwargs)
            elapsed = (time.monotonic() - t0) * 1000
            logger.debug(
                "adata.%s.%s 调用成功 (%.0fms)", module_path, method_name, elapsed,
            )
            return result
        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            logger.warning(
                "adata.%s.%s 调用失败 (%.0fms): %s",
                module_path, method_name, elapsed, e,
            )
            raise

    # ----------------------------------------------------------------
    # 便捷查询方法
    # ----------------------------------------------------------------

    def get_stock_list(self) -> Any:
        """获取全部 A 股股票列表。"""
        return self.call_adata("stock.info", "all_code")

    def get_market(
        self,
        stock_code: str,
        k_type: int = 1,
        start_date: str = "",
    ) -> Any:
        """获取个股 K 线数据。

        Args:
            stock_code: 股票代码 (如 "000001")
            k_type: K 线周期 (1=日, 2=周, 3=月)
            start_date: 起始日期 (如 "2023-01-01")
        """
        return self.call_adata(
            "stock.market",
            "get_market",
            stock_code=stock_code,
            k_type=k_type,
            start_date=start_date,
        )

    def get_realtime(self) -> Any:
        """获取全市场实时行情快照。"""
        return self.call_adata("stock.market", "get_market_realtime")

    def get_concept_constituent(self, concept_code: str) -> Any:
        """获取概念板块成分股。

        Args:
            concept_code: 概念板块代码
        """
        return self.call_adata(
            "stock.info.concept",
            "concept_constituent",
            concept_code=concept_code,
        )

    def get_cb_list(self) -> Any:
        """获取全部可转债列表。"""
        return self.call_adata("bond.info", "all_convert_code")

    def get_cb_market(self, stock_code: str, start_date: str = "") -> Any:
        """获取可转债行情数据。

        Args:
            stock_code: 可转债代码
            start_date: 起始日期 (如 "2023-01-01")
        """
        return self.call_adata(
            "bond.market",
            "get_market",
            stock_code=stock_code,
            start_date=start_date,
        )

    # ----------------------------------------------------------------
    # BaseCollector 抽象方法实现
    # ----------------------------------------------------------------

    def collect(self, task: CollectTask) -> CollectResult:
        """执行采集任务 — 从 task.params 读取 module_path / method_name 和参数。

        task.params 结构:
            - module_path (str): adata 模块路径 (必需, 如 "stock.info")
            - method_name (str): 方法名 (必需, 如 "all_code")
            - 其余键值对作为方法参数传入
        """
        params = dict(task.params)
        module_path = params.pop("module_path", "")
        method_name = params.pop("method_name", "")
        if not module_path or not method_name:
            raise ValueError(
                "task.params 缺少必需字段 'module_path' 和/或 'method_name'"
            )

        t0 = time.monotonic()
        data = self.call_adata(module_path, method_name, **params)
        elapsed_ms = (time.monotonic() - t0) * 1000

        records = len(data) if hasattr(data, "__len__") else 0
        return CollectResult(
            source=self.SOURCE,
            data=data,
            collected_at=datetime.now(),
            metadata={
                "task_id": task.task_id,
                "module_path": module_path,
                "method_name": method_name,
                "params": params,
                "records_count": records,
                "elapsed_ms": round(elapsed_ms, 1),
            },
        )

    def health_check(self) -> bool:
        """检查 adata 数据源可用性, 尝试获取股票列表验证连通性。"""
        try:
            df = self.get_stock_list()
            ok = df is not None and len(df) > 0
            logger.info(
                "adata 健康检查: %s (rows=%d)",
                "OK" if ok else "EMPTY",
                len(df) if ok else 0,
            )
            return ok
        except Exception as e:
            logger.warning("adata 健康检查失败: %s", e)
            return False
