"""新浪财经全球市场采集器 — Tier 2 情报信号

通过新浪财经 HTTP API 采集全球指数、外汇、商品期货实时行情。
作为 yfinance 的备用/补充数据源。
"""
from __future__ import annotations

import re
import time
from datetime import datetime, date

from src.common.logger import get_logger
from src.datacollect.base import BaseCollector, CollectResult, CollectTask
from src.datacollect.client import SmartHttpClient
from src.datacollect.rate_limiter import TokenBucketLimiter

logger = get_logger(__name__)

_SINA_HQ_URL = "https://hq.sinajs.cn/list="

SINA_SYMBOL_MAP: dict[str, dict[str, str]] = {
    "global_index": {
        "DJI": "int_dji",
        "NASDAQ": "int_nasdaq",
        "SPX": "int_sp500",
        "FTSE": "int_ftse",
        "DAX": "int_dax",
        "NIKKEI": "int_nikkei",
        "HSI": "int_hangseng",
    },
    "forex": {
        "USDCNY": "fx_susdcny",
        "EURUSD": "fx_seurusd",
        "USDJPY": "fx_susdjpy",
    },
    "gold": {
        "XAUUSD": "hf_GC",
    },
    "crude_oil": {
        "WTI": "hf_CL",
        "BRENT": "hf_OIL",
    },
    "ftse_a50": {
        "FTSE_A50": "hf_CHA50CFD",
    },
}

_FUNC_MAP: dict[str, str] = {
    "global_index": "fetch_global_index",
    "forex": "fetch_forex",
    "gold": "fetch_gold",
    "crude_oil": "fetch_crude_oil",
    "ftse_a50": "fetch_ftse_a50",
}


class SinaGlobalCollector(BaseCollector):
    """新浪财经全球市场采集器 — 实时快照。

    Tier 2 备用源, 通过新浪 HTTP API 获取全球行情。
    """

    SOURCE = "sina_global"

    def __init__(
        self,
        limiter: TokenBucketLimiter | None = None,
        client: SmartHttpClient | None = None,
    ):
        if limiter is None:
            limiter = TokenBucketLimiter.for_domain("sina", rate=0.2, burst=3)
        super().__init__(limiter)
        self._client = client or SmartHttpClient()

    _HEADERS = {
        "Referer": "https://finance.sina.com.cn",
        "Accept": "text/plain, */*",
    }

    def _fetch_quotes(self, symbol_group: dict[str, str]) -> list[dict]:
        """Fetch quotes from Sina HQ API and parse var hq_str_ response."""
        if self._limiter:
            self._limiter.acquire()

        sina_codes = ",".join(symbol_group.values())
        url = _SINA_HQ_URL + sina_codes

        t0 = time.monotonic()
        try:
            resp = self._client.get(url, headers=self._HEADERS)
            text = resp.text if hasattr(resp, "text") else str(resp.content, "gbk")
        except Exception as e:
            logger.warning("新浪行情请求失败: %s", e)
            return []
        elapsed = (time.monotonic() - t0) * 1000
        logger.debug("sina hq GET (%.0fms)", elapsed)

        reverse_map = {v: k for k, v in symbol_group.items()}
        rows: list[dict] = []

        for line in text.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            match = re.match(r'var hq_str_(\w+)="(.*)";', line)
            if not match:
                continue
            sina_code = match.group(1)
            data_str = match.group(2)
            label = reverse_map.get(sina_code)
            if not label or not data_str:
                continue

            parts = data_str.split(",")
            try:
                close = float(parts[1]) if len(parts) > 1 and parts[1] else None
                prev_close = float(parts[7]) if len(parts) > 7 and parts[7] else None
                change_pct = None
                if close and prev_close and prev_close != 0:
                    change_pct = round((close - prev_close) / prev_close * 100, 4)
                rows.append({
                    "symbol": label,
                    "close_price": close,
                    "change_pct": change_pct,
                    "trade_date": date.today(),
                    "raw": {"parts": parts[:10]},
                })
            except (ValueError, IndexError) as e:
                logger.debug("新浪行情解析 %s 失败: %s", sina_code, e)

        return rows

    def fetch_global_index(self) -> list[dict]:
        return self._fetch_quotes(SINA_SYMBOL_MAP["global_index"])

    def fetch_forex(self) -> list[dict]:
        return self._fetch_quotes(SINA_SYMBOL_MAP["forex"])

    def fetch_gold(self) -> list[dict]:
        return self._fetch_quotes(SINA_SYMBOL_MAP["gold"])

    def fetch_crude_oil(self) -> list[dict]:
        return self._fetch_quotes(SINA_SYMBOL_MAP["crude_oil"])

    def fetch_ftse_a50(self) -> list[dict]:
        return self._fetch_quotes(SINA_SYMBOL_MAP["ftse_a50"])

    def collect(self, task: CollectTask) -> CollectResult:
        params = dict(task.params)
        func_name = params.pop("func_name", "") or _FUNC_MAP.get(task.data_type, "")
        if not func_name:
            raise ValueError(
                f"SinaGlobalCollector: 无法确定采集方法, data_type={task.data_type}"
            )

        fn = getattr(self, func_name, None)
        if fn is None or not callable(fn):
            raise AttributeError(f"SinaGlobalCollector 没有方法: {func_name}")

        t0 = time.monotonic()
        data = fn(**params)
        elapsed_ms = (time.monotonic() - t0) * 1000

        return CollectResult(
            source=self.SOURCE,
            data=data,
            collected_at=datetime.now(),
            metadata={
                "task_id": task.task_id,
                "func_name": func_name,
                "records_count": len(data) if data else 0,
                "elapsed_ms": round(elapsed_ms, 1),
            },
        )

    def health_check(self) -> bool:
        try:
            rows = self.fetch_global_index()
            ok = len(rows) > 0
            logger.info("sina_global 健康检查: %s (%d quotes)", "OK" if ok else "EMPTY", len(rows))
            return ok
        except Exception as e:
            logger.warning("sina_global 健康检查失败: %s", e)
            return False

    @classmethod
    def func_for_data_type(cls, data_type: str) -> str | None:
        return _FUNC_MAP.get(data_type)
