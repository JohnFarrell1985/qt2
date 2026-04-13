"""Yahoo Finance 全球市场采集器 — Tier 2 情报信号

采集全球指数、VIX、黄金、原油、外汇、国债收益率等外围市场数据,
用于 SentimentDaily.global_mood 合成。yfinance 仅在方法内延迟导入。
"""
from __future__ import annotations

import time
from datetime import datetime, date

from src.common.logger import get_logger
from src.datacollect.base import BaseCollector, CollectResult, CollectTask
from src.datacollect.rate_limiter import TokenBucketLimiter

logger = get_logger(__name__)

TICKER_MAP: dict[str, dict[str, str]] = {
    "global_index": {
        "SPX": "^GSPC",
        "NASDAQ": "^IXIC",
        "DJI": "^DJI",
        "HSI": "^HSI",
        "NIKKEI": "^N225",
        "FTSE": "^FTSE",
        "DAX": "^GDAXI",
    },
    "vix": {"VIX": "^VIX"},
    "gold": {"XAUUSD": "GC=F"},
    "crude_oil": {"WTI": "CL=F", "BRENT": "BZ=F"},
    "forex": {"USDCNY": "CNY=X", "DXY": "DX-Y.NYB"},
    "bond_yield": {"US10Y": "^TNX", "US2Y": "^IRX"},
    "ftse_a50": {"FTSE_A50": "XIN9.FGI"},
}

_FUNC_MAP: dict[str, str] = {
    "global_index": "fetch_global_index",
    "vix": "fetch_vix",
    "gold": "fetch_gold",
    "crude_oil": "fetch_crude_oil",
    "forex": "fetch_forex",
    "bond_yield": "fetch_bond_yield",
    "ftse_a50": "fetch_ftse_a50",
}


class YfinanceCollector(BaseCollector):
    """Yahoo Finance 全球市场采集器。

    Tier 2 轻量采集, 用于盘前情报信号, 非交易标的数据。
    """

    SOURCE = "yfinance"

    def __init__(self, limiter: TokenBucketLimiter | None = None):
        if limiter is None:
            from src.common.config import settings
            limiter = TokenBucketLimiter.for_domain(
                "yfinance",
                rate=settings.datacollect.yfinance_rate,
                burst=settings.datacollect.yfinance_burst,
            )
        super().__init__(limiter)

    def _download(self, tickers: dict[str, str], period: str = "5d") -> list[dict]:
        """Download data for a group of tickers and return normalized rows."""
        try:
            import yfinance as yf
        except ImportError:
            raise RuntimeError("yfinance 未安装, 无法采集全球市场数据")

        if self._limiter:
            self._limiter.acquire()

        ticker_str = " ".join(tickers.values())
        t0 = time.monotonic()
        data = yf.download(ticker_str, period=period, progress=False, group_by="ticker")
        elapsed = (time.monotonic() - t0) * 1000
        logger.debug("yfinance download %d tickers (%.0fms)", len(tickers), elapsed)

        rows: list[dict] = []
        for label, yf_ticker in tickers.items():
            try:
                if len(tickers) == 1:
                    df = data
                else:
                    df = data[yf_ticker] if yf_ticker in data.columns.get_level_values(0) else None
                if df is None or df.empty:
                    continue
                last = df.iloc[-1]
                prev = df.iloc[-2] if len(df) >= 2 else last
                close = float(last["Close"]) if last["Close"] == last["Close"] else None
                prev_close = float(prev["Close"]) if prev["Close"] == prev["Close"] else None
                change_pct = None
                if close is not None and prev_close and prev_close != 0:
                    change_pct = round((close - prev_close) / prev_close * 100, 4)
                rows.append({
                    "symbol": label,
                    "close_price": close,
                    "change_pct": change_pct,
                    "trade_date": df.index[-1].date() if hasattr(df.index[-1], "date") else date.today(),
                    "raw": {
                        "open": float(last.get("Open", 0)),
                        "high": float(last.get("High", 0)),
                        "low": float(last.get("Low", 0)),
                        "close": close,
                        "volume": int(last.get("Volume", 0)) if last.get("Volume") == last.get("Volume") else 0,
                    },
                })
            except Exception as e:
                logger.warning("yfinance parse %s failed: %s", label, e)
        return rows

    def fetch_global_index(self) -> list[dict]:
        return self._download(TICKER_MAP["global_index"])

    def fetch_vix(self) -> list[dict]:
        return self._download(TICKER_MAP["vix"])

    def fetch_gold(self) -> list[dict]:
        return self._download(TICKER_MAP["gold"])

    def fetch_crude_oil(self) -> list[dict]:
        return self._download(TICKER_MAP["crude_oil"])

    def fetch_forex(self) -> list[dict]:
        return self._download(TICKER_MAP["forex"])

    def fetch_bond_yield(self) -> list[dict]:
        return self._download(TICKER_MAP["bond_yield"])

    def fetch_ftse_a50(self) -> list[dict]:
        return self._download(TICKER_MAP["ftse_a50"])

    def collect(self, task: CollectTask) -> CollectResult:
        params = dict(task.params)
        func_name = params.pop("func_name", "") or _FUNC_MAP.get(task.data_type, "")
        if not func_name:
            raise ValueError(
                f"YfinanceCollector: 无法确定采集方法, data_type={task.data_type}, params={task.params}"
            )

        fn = getattr(self, func_name, None)
        if fn is None or not callable(fn):
            raise AttributeError(f"YfinanceCollector 没有方法: {func_name}")

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
            rows = self.fetch_vix()
            ok = len(rows) > 0
            logger.info("yfinance 健康检查: %s", "OK" if ok else "EMPTY")
            return ok
        except Exception as e:
            logger.warning("yfinance 健康检查失败: %s", e)
            return False

    @classmethod
    def func_for_data_type(cls, data_type: str) -> str | None:
        return _FUNC_MAP.get(data_type)
