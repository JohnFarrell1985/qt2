"""AkShare 数据采集器 — 封装 akshare 函数调用

通过 BaseCollector 接口统一管理, 内置限流和错误处理。
akshare 仅在函数内部延迟导入, CI 环境无需安装该 SDK。
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


class AkshareCollector(BaseCollector):
    """基于 akshare 的 A 股数据采集器。

    所有 akshare 函数通过 call_ak() 统一调用, 自动限流和重试。
    """

    SOURCE = "akshare"

    def __init__(self, limiter: TokenBucketLimiter | None = None):
        if limiter is None:
            limiter = TokenBucketLimiter.for_domain(
                "akshare",
                rate=_CFG.akshare_rate,
                burst=_CFG.akshare_burst,
            )
        super().__init__(limiter)

    def call_ak(self, func_name: str, **kwargs: Any) -> Any:
        """调用指定的 akshare 函数, 带限流控制。

        Args:
            func_name: akshare 模块中的函数名 (如 "stock_zh_a_spot_em")
            **kwargs: 传递给 akshare 函数的参数

        Returns:
            akshare 函数的返回值 (通常为 DataFrame)

        Raises:
            AttributeError: func_name 不存在
            RuntimeError: akshare 不可用或调用失败
        """
        try:
            import akshare as ak
        except ImportError:
            raise RuntimeError("akshare 未安装, 无法进行数据采集")

        fn = getattr(ak, func_name, None)
        if fn is None:
            raise AttributeError(f"akshare 没有函数: {func_name}")

        if self._limiter:
            self._limiter.acquire()

        t0 = time.monotonic()
        try:
            result = fn(**kwargs)
            elapsed = (time.monotonic() - t0) * 1000
            logger.debug("ak.%s 调用成功 (%.0fms)", func_name, elapsed)
            return result
        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            logger.warning("ak.%s 调用失败 (%.0fms): %s", func_name, elapsed, e)
            raise

    def collect(self, task: CollectTask) -> CollectResult:
        """执行采集任务 — 从 task.params 读取 func_name 和参数。

        task.params 结构:
            - func_name (str): akshare 函数名 (必需)
            - 其余键值对作为函数参数传入
        """
        params = dict(task.params)
        func_name = params.pop("func_name", "")
        if not func_name:
            raise ValueError("task.params 缺少必需字段 'func_name'")

        t0 = time.monotonic()
        data = self.call_ak(func_name, **params)
        elapsed_ms = (time.monotonic() - t0) * 1000

        records = len(data) if hasattr(data, "__len__") else 0
        return CollectResult(
            source=self.SOURCE,
            data=data,
            collected_at=datetime.now(),
            metadata={
                "task_id": task.task_id,
                "func_name": func_name,
                "params": params,
                "records_count": records,
                "elapsed_ms": round(elapsed_ms, 1),
            },
        )

    def health_check(self) -> bool:
        """用 stock_info_a_code_name 做轻量连通性检测。

        stock_zh_a_spot_em 需分页拉取全量 A 股 (58 页 / 5 分钟+),
        不适合做 health_check; stock_info_a_code_name 仅返回代码+名称,
        单次请求 < 3s。
        """
        try:
            df = self.call_ak("stock_info_a_code_name")
            ok = df is not None and len(df) > 0
            logger.info("akshare 健康检查: %s (rows=%d)", "OK" if ok else "EMPTY", len(df) if ok else 0)
            return ok
        except Exception as e:
            logger.warning("akshare 健康检查失败: %s", e)
            return False
