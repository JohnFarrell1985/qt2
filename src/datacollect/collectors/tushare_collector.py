"""Tushare Pro 数据采集器 — 数据最全面, 需要注册获取 Token

通过 BaseCollector 接口统一管理, 内置限流和错误处理。
tushare 仅在方法内部延迟导入, CI 环境无需安装该 SDK。
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


class TushareCollector(BaseCollector):
    """基于 Tushare Pro 的 A 股数据采集器。

    Tushare Pro 提供最全面的 A 股金融数据, 包括日线行情、财务指标、
    指数数据等, 需要注册并获取 Token 后方可使用。

    若 TUSHARE_TOKEN 未配置, 采集器标记为不可用。
    """

    SOURCE = "tushare"

    def __init__(self, limiter: TokenBucketLimiter | None = None):
        if limiter is None:
            limiter = TokenBucketLimiter.for_domain(
                "tushare",
                rate=_CFG.tushare_rate,
                burst=_CFG.tushare_burst,
            )
        super().__init__(limiter)
        self._token = _CFG.tushare_token

    @property
    def available(self) -> bool:
        """Token 已配置时才视为可用。"""
        return bool(self._token)

    def _get_pro(self) -> Any:
        """获取 tushare pro_api 实例 (延迟导入)。"""
        if not self._token:
            raise RuntimeError("TUSHARE_TOKEN 未配置, 无法创建 pro_api 实例")
        try:
            import tushare as ts
        except ImportError:
            raise RuntimeError("tushare 未安装, 无法进行数据采集")
        return ts.pro_api(self._token)

    def query(self, api_name: str, **kwargs: Any) -> Any:
        """调用 tushare pro API, 带限流控制。

        Args:
            api_name: tushare pro 接口名 (如 "stock_basic", "daily",
                      "index_daily", "fina_indicator", "trade_cal" 等)
            **kwargs: 传递给 tushare 接口的参数

        Returns:
            tushare 返回的 DataFrame

        Raises:
            RuntimeError: Token 未配置或 tushare 不可用
        """
        if self._limiter:
            self._limiter.acquire()

        pro = self._get_pro()

        t0 = time.monotonic()
        try:
            fn = getattr(pro, api_name, None)
            if fn is None:
                result = pro.query(api_name, **kwargs)
            else:
                result = fn(**kwargs)
            elapsed = (time.monotonic() - t0) * 1000
            logger.debug("tushare.%s 调用成功 (%.0fms)", api_name, elapsed)
            return result
        except Exception as e:
            elapsed = (time.monotonic() - t0) * 1000
            logger.warning("tushare.%s 调用失败 (%.0fms): %s", api_name, elapsed, e)
            raise

    # ----------------------------------------------------------------
    # 便捷查询方法
    # ----------------------------------------------------------------

    def query_stock_basic(self, **kwargs: Any) -> Any:
        """股票基础信息 (需 120 积分)。"""
        return self.query("stock_basic", exchange="", list_status="L", **kwargs)

    def query_daily(
        self,
        ts_code: str = "",
        trade_date: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> Any:
        """日线行情。"""
        params: dict[str, str] = {}
        if ts_code:
            params["ts_code"] = ts_code
        if trade_date:
            params["trade_date"] = trade_date
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return self.query("daily", **params)

    def query_index_daily(
        self,
        ts_code: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> Any:
        """指数日线。"""
        return self.query(
            "index_daily",
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )

    def query_fina_indicator(
        self,
        ts_code: str,
        start_date: str = "",
        end_date: str = "",
    ) -> Any:
        """财务指标。"""
        return self.query(
            "fina_indicator",
            ts_code=ts_code,
            start_date=start_date,
            end_date=end_date,
        )

    def query_cb_basic(self, **kwargs: Any) -> Any:
        """可转债基本信息。"""
        return self.query("cb_basic", **kwargs)

    def query_cb_daily(
        self,
        ts_code: str = "",
        trade_date: str = "",
        start_date: str = "",
        end_date: str = "",
    ) -> Any:
        """可转债日线行情。"""
        params: dict[str, str] = {}
        if ts_code:
            params["ts_code"] = ts_code
        if trade_date:
            params["trade_date"] = trade_date
        if start_date:
            params["start_date"] = start_date
        if end_date:
            params["end_date"] = end_date
        return self.query("cb_daily", **params)

    # ----------------------------------------------------------------
    # BaseCollector 抽象方法实现
    # ----------------------------------------------------------------

    def collect(self, task: CollectTask) -> CollectResult:
        """执行采集任务 — 从 task.params 读取 func_name 和参数。

        task.params 结构:
            - func_name (str): tushare pro 接口名 (必需)
            - 其余键值对作为接口参数传入
        """
        params = dict(task.params)
        func_name = params.pop("func_name", "")
        if not func_name:
            raise ValueError("task.params 缺少必需字段 'func_name'")

        t0 = time.monotonic()
        data = self.query(func_name, **params)
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
        """检查 tushare 数据源可用性。

        Token 未配置时直接返回 False; 否则尝试查询交易日历验证连通性。
        """
        if not self._token:
            logger.info("tushare Token 未配置, 数据源不可用")
            return False
        try:
            df = self.query(
                "trade_cal",
                exchange="SSE",
                is_open="1",
                start_date="20260101",
                end_date="20260131",
            )
            ok = df is not None and len(df) > 0
            logger.info(
                "tushare 健康检查: %s (rows=%d)",
                "OK" if ok else "EMPTY",
                len(df) if ok else 0,
            )
            return ok
        except Exception as e:
            logger.warning("tushare 健康检查失败: %s", e)
            return False
