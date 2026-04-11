"""东方财富 HTTP 直连采集器 — 使用 SmartHttpClient 反爬

直接调用东方财富公开 HTTP API, 无需安装任何第三方数据 SDK。
通过 SmartHttpClient 实现浏览器指纹模拟 + UA 轮换 + 自动重试。
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from src.common.config import settings
from src.common.logger import get_logger
from src.datacollect.base import BaseCollector, CollectResult, CollectTask
from src.datacollect.client import SmartHttpClient
from src.datacollect.rate_limiter import TokenBucketLimiter

logger = get_logger(__name__)

_CFG = settings.datacollect

_BASE_URL = "https://push2.eastmoney.com/api/qt/clist/get"
_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"

_STOCK_LIST_FIELDS = "f1,f2,f3,f4,f5,f6,f7,f12,f13,f14"
_STOCK_LIST_FS = "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048"

_KLINE_FIELDS1 = "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13"
_KLINE_FIELDS2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"

_KLINE_COLUMNS = [
    "date", "open", "close", "high", "low",
    "volume", "amount", "amplitude", "change_pct",
    "change", "turnover",
]

_FUNC_MAP: dict[str, str] = {
    "stock_list": "fetch_stock_list",
    "daily_kline": "fetch_kline",
    "index_daily": "fetch_kline",
    "realtime": "fetch_realtime",
}


class EastmoneyCollector(BaseCollector):
    """东方财富 HTTP 直连采集器 — 使用 SmartHttpClient 反爬。

    直接请求东方财富公开 API 端点, 解析 JSON 响应。
    不依赖任何第三方数据 SDK, 仅需 SmartHttpClient + pandas。
    """

    SOURCE = "eastmoney"

    def __init__(
        self,
        limiter: TokenBucketLimiter | None = None,
        client: SmartHttpClient | None = None,
    ):
        if limiter is None:
            limiter = TokenBucketLimiter.for_domain(
                "eastmoney",
                rate=_CFG.eastmoney_rate,
                burst=_CFG.eastmoney_burst,
            )
        super().__init__(limiter)
        self._client = client or SmartHttpClient()

    @staticmethod
    def _secid(code: str) -> str:
        """将 6 位股票代码转换为东财 secid 格式。

        沪市 (6 开头) -> "1.600000", 深市 -> "0.000001"
        """
        if code.startswith("6"):
            return f"1.{code}"
        return f"0.{code}"

    def _request(self, url: str, params: dict[str, Any]) -> dict:
        """发起限流 + 反爬 HTTP GET, 返回 JSON 字典。"""
        if self._limiter:
            self._limiter.acquire()

        t0 = time.monotonic()
        resp = self._client.get(url, params=params)
        body: dict = resp.json()
        elapsed = (time.monotonic() - t0) * 1000
        logger.debug("eastmoney GET %s (%.0fms)", url.split("/")[-1], elapsed)

        if body.get("rc") != 0 and body.get("rc") is not None:
            raise RuntimeError(
                f"东财 API 错误: rc={body.get('rc')}, msg={body.get('msg', '')}"
            )
        return body

    def fetch_stock_list(self) -> Any:
        """获取全部 A 股股票列表。

        Returns:
            DataFrame — 列: code, name, price, change_pct, volume, amount
        """
        import pandas as pd

        params = {
            "pn": "1",
            "pz": "5000",
            "fs": _STOCK_LIST_FS,
            "fields": _STOCK_LIST_FIELDS,
        }
        body = self._request(_BASE_URL, params)

        diff = body.get("data", {}).get("diff") or []
        if not diff:
            logger.warning("fetch_stock_list: 返回空列表")
            return pd.DataFrame()

        rows = []
        for item in diff:
            rows.append({
                "code": str(item.get("f12", "")),
                "name": str(item.get("f14", "")),
                "price": item.get("f2"),
                "change_pct": item.get("f3"),
                "volume": item.get("f5"),
                "amount": item.get("f6"),
            })
        df = pd.DataFrame(rows)
        logger.info("fetch_stock_list: 获取 %d 只股票", len(df))
        return df

    def fetch_kline(
        self,
        code: str,
        start_date: str = "20230101",
        end_date: str = "20500101",
        klt: int = 101,
        fqt: int = 1,
    ) -> Any:
        """获取 K 线数据。

        Args:
            code: 6 位股票代码 (如 "000001")
            start_date: 起始日期 YYYYMMDD
            end_date: 截止日期 YYYYMMDD
            klt: K 线类型 (101=日, 102=周, 103=月)
            fqt: 复权类型 (0=不复权, 1=前复权, 2=后复权)

        Returns:
            DataFrame — 列: date, open, close, high, low, volume, amount, ...
        """
        import pandas as pd

        secid = self._secid(code)
        params = {
            "secid": secid,
            "klt": str(klt),
            "fqt": str(fqt),
            "lmt": "0",
            "beg": start_date,
            "end": end_date,
            "fields1": _KLINE_FIELDS1,
            "fields2": _KLINE_FIELDS2,
        }
        body = self._request(_KLINE_URL, params)

        klines = body.get("data", {}).get("klines") or []
        if not klines:
            logger.warning("fetch_kline(%s): 返回空 K 线", code)
            return pd.DataFrame(columns=["code"] + _KLINE_COLUMNS)

        rows = []
        for line in klines:
            parts = line.split(",")
            if len(parts) < len(_KLINE_COLUMNS):
                continue
            rows.append(parts[: len(_KLINE_COLUMNS)])

        df = pd.DataFrame(rows, columns=_KLINE_COLUMNS)
        df.insert(0, "code", code)

        numeric_cols = [c for c in _KLINE_COLUMNS if c != "date"]
        for col in numeric_cols:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        logger.info("fetch_kline(%s): 获取 %d 条 K 线", code, len(df))
        return df

    def fetch_realtime(self) -> Any:
        """获取全部 A 股实时行情快照。

        Returns:
            DataFrame — 列: code, name, price, change_pct, volume, amount
        """
        import pandas as pd

        params = {
            "pn": "1",
            "pz": "5000",
            "fs": _STOCK_LIST_FS,
            "fields": _STOCK_LIST_FIELDS,
        }
        body = self._request(_BASE_URL, params)

        diff = body.get("data", {}).get("diff") or []
        if not diff:
            logger.warning("fetch_realtime: 返回空列表")
            return pd.DataFrame()

        rows = []
        for item in diff:
            rows.append({
                "code": str(item.get("f12", "")),
                "name": str(item.get("f14", "")),
                "price": item.get("f2"),
                "change_pct": item.get("f3"),
                "volume": item.get("f5"),
                "amount": item.get("f6"),
            })
        df = pd.DataFrame(rows)
        logger.info("fetch_realtime: 获取 %d 条实时行情", len(df))
        return df

    def collect(self, task: CollectTask) -> CollectResult:
        """执行采集任务 — 从 task.params 读取 func_name 和参数。

        task.params 结构:
            - func_name (str): 方法名 (fetch_stock_list / fetch_kline / fetch_realtime)
            - 其余键值对作为方法参数传入
        """
        params = dict(task.params)
        func_name = params.pop("func_name", "")
        if not func_name:
            raise ValueError("task.params 缺少必需字段 'func_name'")

        fn = getattr(self, func_name, None)
        if fn is None or not callable(fn):
            raise AttributeError(f"EastmoneyCollector 没有方法: {func_name}")

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
        """通过获取股票列表验证东财 API 可用性。"""
        try:
            df = self.fetch_stock_list()
            ok = df is not None and len(df) > 0
            logger.info(
                "eastmoney 健康检查: %s (rows=%d)",
                "OK" if ok else "EMPTY",
                len(df) if ok else 0,
            )
            return ok
        except Exception as e:
            logger.warning("eastmoney 健康检查失败: %s", e)
            return False

    @classmethod
    def func_for_data_type(cls, data_type: str) -> str | None:
        """将通用 data_type 映射到本采集器的方法名。"""
        return _FUNC_MAP.get(data_type)
