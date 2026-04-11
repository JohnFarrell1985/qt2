"""PyTDX 数据采集器 — 直连通达信行情服务器

通过 BaseCollector 接口统一管理, 内置限流和错误处理。
pytdx 仅在函数内部延迟导入, CI 环境无需安装该 SDK。
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

MARKET_SZ = 0
MARKET_SH = 1

KLINE_CATEGORY = {
    "5min": 0, "15min": 1, "30min": 2, "1h": 3,
    "daily": 4, "weekly": 5, "monthly": 6,
    "1min": 7, "tick": 8, "daily_9": 9,
    "quarterly": 10, "yearly": 11,
}


class PytdxCollector(BaseCollector):
    """基于 pytdx 的 A 股数据采集器。

    特点:
    - 直连通达信行情服务器, 无需注册、无需 Token
    - 支持实时行情和历史 K 线
    - 股票代码为纯 6 位数字, market=0 深圳, market=1 上海
    - 自动探测最快服务器
    """

    SOURCE = "pytdx"

    def __init__(self, limiter: TokenBucketLimiter | None = None):
        if limiter is None:
            limiter = TokenBucketLimiter.for_domain(
                "pytdx",
                rate=_CFG.pytdx_rate,
                burst=_CFG.pytdx_burst,
            )
        super().__init__(limiter)
        self._best_ip: dict[str, Any] | None = None

    def _select_best_ip(self) -> dict[str, Any]:
        """探测最快的通达信服务器 (结果缓存)。"""
        if self._best_ip is not None:
            return self._best_ip

        try:
            from pytdx.util.best_ip import select_best_ip
        except ImportError:
            raise RuntimeError("pytdx 未安装, 无法进行数据采集")

        ip_info = select_best_ip()
        if not ip_info:
            raise RuntimeError("pytdx 无法探测到可用的行情服务器")
        self._best_ip = ip_info
        logger.info("pytdx 最佳服务器: %s:%s", ip_info.get("ip"), ip_info.get("port"))
        return self._best_ip

    def _connect_api(self):
        """创建并连接 TdxHq_API 实例 (延迟导入)。

        Returns:
            已连接的 TdxHq_API 实例

        Raises:
            RuntimeError: pytdx 不可用或连接失败
        """
        try:
            from pytdx.hq import TdxHq_API
        except ImportError:
            raise RuntimeError("pytdx 未安装, 无法进行数据采集")

        ip_info = self._select_best_ip()
        api = TdxHq_API()
        api.connect(ip_info["ip"], int(ip_info["port"]))
        return api

    def get_security_bars(
        self,
        code: str,
        market: int,
        category: int = 9,
        start: int = 0,
        count: int = 800,
    ):
        """获取 K 线数据。

        Args:
            code: 6 位股票代码 (如 "600000")
            market: 0=深圳, 1=上海
            category: K 线类型 (0=5min, 4=日线, 9=日线 等, 参见 KLINE_CATEGORY)
            start: 起始偏移位置
            count: 获取条数 (最大 800)
        """
        if self._limiter:
            self._limiter.acquire()

        api = self._connect_api()
        try:
            df = api.get_security_bars(category, market, code, start, count)
            if df is None or (hasattr(df, "empty") and df.empty):
                import pandas as pd
                logger.warning(
                    "pytdx K线数据为空: market=%d code=%s category=%d",
                    market, code, category,
                )
                return pd.DataFrame()
            logger.debug(
                "pytdx K线查询: market=%d code=%s category=%d (%d 行)",
                market, code, category, len(df),
            )
            return df
        finally:
            api.disconnect()

    def get_security_quotes(self, stock_list: list[tuple[int, str]]):
        """获取实时行情快照。

        Args:
            stock_list: [(market, code), ...] 如 [(1, "600000"), (0, "000001")]
        """
        if self._limiter:
            self._limiter.acquire()

        api = self._connect_api()
        try:
            df = api.get_security_quotes(stock_list)
            if df is None or (hasattr(df, "empty") and df.empty):
                import pandas as pd
                logger.warning("pytdx 实时行情为空: %s", stock_list)
                return pd.DataFrame()
            logger.debug("pytdx 实时行情: %d 只股票", len(df))
            return df
        finally:
            api.disconnect()

    def get_security_list(self, market: int, start: int = 0):
        """获取股票列表。

        Args:
            market: 0=深圳, 1=上海
            start: 起始偏移位置
        """
        if self._limiter:
            self._limiter.acquire()

        api = self._connect_api()
        try:
            df = api.get_security_list(market, start)
            if df is None or (hasattr(df, "empty") and df.empty):
                import pandas as pd
                logger.warning("pytdx 股票列表为空: market=%d", market)
                return pd.DataFrame()
            logger.debug("pytdx 股票列表: market=%d (%d 行)", market, len(df))
            return df
        finally:
            api.disconnect()

    def get_index_bars(
        self,
        code: str,
        market: int,
        category: int = 9,
        start: int = 0,
        count: int = 800,
    ):
        """获取指数 K 线数据。

        Args:
            code: 指数代码 (如 "000001" 上证指数)
            market: 0=深圳, 1=上海
            category: K 线类型
            start: 起始偏移位置
            count: 获取条数
        """
        if self._limiter:
            self._limiter.acquire()

        api = self._connect_api()
        try:
            df = api.get_index_bars(category, market, code, start, count)
            if df is None or (hasattr(df, "empty") and df.empty):
                import pandas as pd
                logger.warning(
                    "pytdx 指数K线为空: market=%d code=%s", market, code,
                )
                return pd.DataFrame()
            logger.debug(
                "pytdx 指数K线: market=%d code=%s (%d 行)",
                market, code, len(df),
            )
            return df
        finally:
            api.disconnect()

    def collect(self, task: CollectTask) -> CollectResult:
        """执行采集任务 — 从 task.params 读取 func_name 和参数。

        task.params 结构:
            - func_name (str): 方法名 (必需, 如 "get_security_bars")
            - 其余键值对作为方法参数传入
        """
        params = dict(task.params)
        func_name = params.pop("func_name", "")
        if not func_name:
            raise ValueError("task.params 缺少必需字段 'func_name'")

        fn = getattr(self, func_name, None)
        if fn is None or func_name.startswith("_"):
            raise AttributeError(
                f"PytdxCollector 没有公开方法: {func_name}"
            )

        t0 = time.monotonic()
        data = fn(**params)
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
        """尝试连接通达信服务器验证可用性。"""
        try:
            api = self._connect_api()
            api.disconnect()
            return True
        except Exception as e:
            logger.warning("pytdx 健康检查失败: %s", e)
            return False
