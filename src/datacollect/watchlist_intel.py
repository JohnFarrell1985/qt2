"""自选股同步 + 情报采集

A22 WatchlistSync: 从 QMT / CSV / JSON / 手动输入同步自选股
A23 WatchlistIntelCollector: 采集自选股相关新闻/公告/资金异动
"""
from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from src.common.db import get_session
from src.common.logger import get_logger
from src.datacollect.base import BaseCollector, CollectResult, CollectTask
from src.datacollect.rate_limiter import TokenBucketLimiter

logger = get_logger(__name__)


class WatchlistSync:
    """自选股同步器 — 从多个来源同步自选股到 DB。"""

    def sync_from_qmt(self) -> dict[str, int]:
        """从 QMT 拉取自选股并与 DB 做差异同步。

        Returns:
            {"added": N, "removed": N, "unchanged": N}
        """
        try:
            from xtquant import xtdata
        except ImportError:
            logger.warning("xtquant not available, skipping QMT watchlist sync")
            return {"added": 0, "removed": 0, "unchanged": 0, "error": "xtquant_unavailable"}

        try:
            codes = xtdata.get_stock_list_in_sector("我的自选")
        except Exception as exc:
            logger.error("QMT get_stock_list_in_sector failed: %s", exc)
            return {"added": 0, "removed": 0, "unchanged": 0, "error": str(exc)}

        return self._sync_codes(codes, source="qmt")

    def sync_from_csv(self, filepath: str | Path) -> dict[str, int]:
        """从 CSV 文件导入自选股。CSV 格式: code,name (第一行为表头)。"""
        filepath = Path(filepath)
        if not filepath.exists():
            logger.error("CSV file not found: %s", filepath)
            return {"added": 0, "removed": 0, "unchanged": 0, "error": "file_not_found"}

        codes: list[str] = []
        names: dict[str, str] = {}
        with open(filepath, encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = row.get("code", "").strip()
                name = row.get("name", "").strip()
                if code:
                    codes.append(code)
                    if name:
                        names[code] = name

        return self._sync_codes(codes, source="csv", names=names)

    def sync_from_json(self, filepath: str | Path) -> dict[str, int]:
        """从 JSON 文件导入自选股。格式: [{"code": "...", "name": "..."}]。"""
        filepath = Path(filepath)
        if not filepath.exists():
            logger.error("JSON file not found: %s", filepath)
            return {"added": 0, "removed": 0, "unchanged": 0, "error": "file_not_found"}

        with open(filepath, encoding="utf-8") as f:
            items: list[dict] = json.load(f)

        codes = [item["code"] for item in items if "code" in item]
        names = {item["code"]: item.get("name", "") for item in items if "code" in item}
        return self._sync_codes(codes, source="json", names=names)

    def add_manual(self, code: str, name: str = "") -> bool:
        """手动添加单只自选股。"""
        from src.data.models import WatchlistStock

        with get_session() as session:
            existing = (
                session.query(WatchlistStock)
                .filter(WatchlistStock.code == code, WatchlistStock.is_active.is_(True))
                .first()
            )
            if existing:
                logger.info("watchlist stock %s already exists", code)
                return False
            stock = WatchlistStock(code=code, name=name, source="manual", is_active=True)
            session.add(stock)
            logger.info("manually added watchlist stock: %s", code)
        return True

    def remove(self, code: str) -> bool:
        """移除自选股 (软删除)。"""
        from src.data.models import WatchlistStock

        with get_session() as session:
            stock = (
                session.query(WatchlistStock)
                .filter(WatchlistStock.code == code, WatchlistStock.is_active.is_(True))
                .first()
            )
            if stock is None:
                return False
            stock.is_active = False
            stock.removed_at = datetime.now()
            logger.info("removed watchlist stock: %s", code)
        return True

    def get_active(self) -> list[dict]:
        """获取所有活跃自选股。"""
        from src.data.models import WatchlistStock

        with get_session() as session:
            stocks = (
                session.query(WatchlistStock)
                .filter(WatchlistStock.is_active.is_(True))
                .order_by(WatchlistStock.code)
                .all()
            )
            return [
                {"code": s.code, "name": s.name, "source": s.source, "added_at": s.added_at}
                for s in stocks
            ]

    def _sync_codes(
        self,
        codes: list[str],
        source: str,
        names: dict[str, str] | None = None,
    ) -> dict[str, int]:
        """Internal sync: diff DB with incoming codes, add/remove as needed."""
        from src.data.models import WatchlistStock

        names = names or {}

        with get_session() as session:
            existing = (
                session.query(WatchlistStock)
                .filter(WatchlistStock.is_active.is_(True))
                .all()
            )
            existing_codes = {s.code for s in existing}
            incoming_codes = set(codes)

            to_add = incoming_codes - existing_codes
            to_remove = existing_codes - incoming_codes

            added = 0
            for code in to_add:
                session.add(WatchlistStock(
                    code=code,
                    name=names.get(code, ""),
                    source=source,
                    is_active=True,
                ))
                added += 1

            removed = 0
            for stock in existing:
                if stock.code in to_remove:
                    stock.is_active = False
                    stock.removed_at = datetime.now()
                    removed += 1

            unchanged = len(existing_codes & incoming_codes)

        logger.info(
            "watchlist sync from %s: added=%d removed=%d unchanged=%d",
            source, added, removed, unchanged,
        )
        return {"added": added, "removed": removed, "unchanged": unchanged}


class WatchlistIntelCollector(BaseCollector):
    """自选股情报采集器 — 采集新闻/公告/资金异动。

    情报类型:
        - news: 个股新闻 (来源: akshare 东财)
        - announcement: 公司公告 (来源: akshare)
        - capital_flow: 资金异动/龙虎榜 (来源: akshare)
    """

    INTEL_TYPES = ("news", "announcement", "capital_flow")

    def __init__(self, limiter: TokenBucketLimiter | None = None):
        super().__init__(limiter=limiter)

    def collect(self, task: CollectTask) -> CollectResult:
        """采集指定标的的情报数据。

        task.params should contain:
            - code: str (stock code)
            - intel_type: str (news/announcement/capital_flow)
        """
        code = task.params.get("code", "")
        intel_type = task.params.get("intel_type", "news")

        if not code:
            raise ValueError("task.params must contain 'code'")

        if self._limiter:
            self._limiter.acquire()

        dispatch = {
            "news": self._collect_news,
            "announcement": self._collect_announcements,
            "capital_flow": self._collect_capital_flow,
        }
        handler = dispatch.get(intel_type)
        if handler is None:
            raise ValueError(f"Unknown intel_type: {intel_type}")

        data = handler(code)
        return CollectResult(
            source="akshare",
            data=data,
            metadata={"code": code, "intel_type": intel_type, "count": len(data)},
        )

    def health_check(self) -> bool:
        try:
            import akshare  # noqa: F401
            return True
        except ImportError:
            return False

    def collect_and_save(self, code: str, intel_types: list[str] | None = None) -> dict[str, int]:
        """Collect and save intel for a single stock.

        Returns:
            dict mapping intel_type to number of records saved
        """
        intel_types = intel_types or list(self.INTEL_TYPES)
        stats: dict[str, int] = {}

        for it in intel_types:
            task = CollectTask(
                source="akshare",
                data_type=f"watchlist_{it}",
                params={"code": code, "intel_type": it},
            )
            try:
                result = self.collect(task)
                records = result.data
                if records:
                    self._save_intel(code, it, records)
                stats[it] = len(records)
            except Exception as exc:
                logger.warning("intel collect failed for %s/%s: %s", code, it, exc)
                stats[it] = 0

        return stats

    def collect_all_watchlist(self, intel_types: list[str] | None = None) -> dict:
        """Collect intel for all active watchlist stocks."""
        sync = WatchlistSync()
        active = sync.get_active()
        total_stats: dict[str, int] = {}

        for stock in active:
            code = stock["code"]
            st = self.collect_and_save(code, intel_types)
            for k, v in st.items():
                total_stats[k] = total_stats.get(k, 0) + v

        logger.info("watchlist intel complete: %d stocks, stats=%s", len(active), total_stats)
        return {"stocks": len(active), "stats": total_stats}

    # ------------------------------------------------------------------
    # 采集方法 (akshare)
    # ------------------------------------------------------------------

    def _collect_news(self, code: str) -> list[dict]:
        """采集个股新闻 via akshare."""
        try:
            import akshare as ak

            symbol = code.split(".")[0] if "." in code else code
            df = ak.stock_news_em(symbol=symbol)
            if df is None or df.empty:
                return []
            records = []
            for _, row in df.iterrows():
                records.append({
                    "title": str(row.get("新闻标题", "")),
                    "content": str(row.get("新闻内容", "")),
                    "source": str(row.get("文章来源", "eastmoney")),
                    "url": str(row.get("新闻链接", "")),
                    "published_at": str(row.get("发布时间", "")),
                })
            return records
        except Exception as exc:
            logger.warning("_collect_news failed for %s: %s", code, exc)
            return []

    def _collect_announcements(self, code: str) -> list[dict]:
        """采集公司公告 via akshare."""
        try:
            import akshare as ak

            symbol = code.split(".")[0] if "." in code else code
            df = ak.stock_notice_report(symbol=symbol)
            if df is None or df.empty:
                return []
            records = []
            for _, row in df.iterrows():
                records.append({
                    "title": str(row.get("公告标题", row.get("title", ""))),
                    "content": "",
                    "source": "eastmoney",
                    "url": str(row.get("公告链接", row.get("url", ""))),
                    "published_at": str(row.get("公告时间", row.get("date", ""))),
                })
            return records
        except Exception as exc:
            logger.warning("_collect_announcements failed for %s: %s", code, exc)
            return []

    def _collect_capital_flow(self, code: str) -> list[dict]:
        """采集资金异动 via akshare."""
        try:
            import akshare as ak

            symbol = code.split(".")[0] if "." in code else code
            if code.endswith(".SH"):
                market = "sh"
            elif code.endswith(".BJ"):
                market = "bj"
            else:
                market = "sz"
            df = ak.stock_individual_fund_flow(stock=symbol, market=market)
            if df is None or df.empty:
                return []
            records = []
            for _, row in df.head(30).iterrows():
                records.append({
                    "title": f"资金流向 {row.get('日期', '')}",
                    "content": json.dumps(
                        {k: str(v) for k, v in row.to_dict().items()},
                        ensure_ascii=False,
                    ),
                    "source": "eastmoney",
                    "url": "",
                    "published_at": str(row.get("日期", "")),
                })
            return records
        except Exception as exc:
            logger.warning("_collect_capital_flow failed for %s: %s", code, exc)
            return []

    # ------------------------------------------------------------------
    # 持久化
    # ------------------------------------------------------------------

    def _save_intel(self, code: str, intel_type: str, records: list[dict]) -> int:
        """Save intel records to DB."""
        from src.data.models import WatchlistIntel

        saved = 0
        with get_session() as session:
            for rec in records:
                intel = WatchlistIntel(
                    code=code,
                    intel_type=intel_type,
                    title=rec.get("title", "")[:500],
                    content=rec.get("content", ""),
                    source=rec.get("source", ""),
                    url=rec.get("url", ""),
                    raw_data=rec,
                    published_at=self._parse_datetime(rec.get("published_at")),
                )
                session.add(intel)
                saved += 1
        logger.info("saved %d %s intel for %s", saved, intel_type, code)
        return saved

    @staticmethod
    def _parse_datetime(val: Any) -> datetime | None:
        if val is None or val == "":
            return None
        if isinstance(val, datetime):
            return val
        try:
            from dateutil.parser import parse as dt_parse

            return dt_parse(str(val))
        except Exception:
            return None
