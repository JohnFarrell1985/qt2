"""机构持有家数 — DB 优先 + 多源降级 (供选股 UI 异步抓取)

数据源 (各尝试一次):
  1. PostgreSQL ``stock_inst_holder`` (同步模块落库)
  2. 东财 ``RPT_F10_MAIN_ORGHOLD`` live
  3. 新浪 ``stock_institute_hold_detail`` (当年季报)

ETF 不查询; 无当年完整数据 → N/A。
"""
from __future__ import annotations

import threading
import time
from datetime import date
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.common.logger import get_logger
from src.data.inst_holder_em import (
    bare_code,
    current_year_report_dates,
    em_total_for_date,
    fetch_all_for_report_date,
    fetch_one,
)
from src.data.inst_holder_store import lookup_latest_batch

logger = get_logger(__name__)

_MIN_BULK_ROWS = 2000


def _current_year_sina_quarters(today: Optional[date] = None) -> List[str]:
    today = today or date.today()
    y, cq = today.year, (today.month - 1) // 3 + 1
    return [f"{y}{q}" for q in range(cq, 0, -1)]


def _na() -> Dict[str, Any]:
    return {
        "inst_holder_count": None,
        "inst_holder_report_date": None,
        "inst_holder_source": None,
    }


def _fetch_source_database(codes: List[str]) -> Dict[str, Dict[str, Any]]:
    return lookup_latest_batch(codes, min_year=date.today().year)


def _fetch_source_eastmoney_live(codes: List[str]) -> Dict[str, Dict[str, Any]]:
    return InstHolderLiveProvider().get_batch(codes)


def _fetch_source_sina(codes: List[str]) -> Dict[str, Dict[str, Any]]:
    import akshare as ak

    out: Dict[str, Dict[str, Any]] = {}
    quarters = _current_year_sina_quarters()
    for code in codes:
        bare = bare_code(code)
        hit: Optional[Dict[str, Any]] = None
        for q in quarters:
            try:
                df = ak.stock_institute_hold_detail(stock=bare, quarter=q)
            except Exception as e:  # noqa: BLE001
                logger.debug("新浪机构持股 %s@%s: %s", bare, q, e)
                continue
            if df is not None and not df.empty:
                y, qq = q[:4], q[4]
                hit = {
                    "inst_holder_count": len(df),
                    "inst_holder_report_date": f"{y}-Q{qq}",
                    "inst_holder_source": "sina",
                }
                break
        out[code] = hit if hit else _na()
    return out


SOURCE_STACK: List[Tuple[str, Callable[[List[str]], Dict[str, Dict[str, Any]]]]] = [
    ("database", _fetch_source_database),
    ("eastmoney", _fetch_source_eastmoney_live),
    ("sina", _fetch_source_sina),
]


def fetch_inst_holders_multi_source(codes: List[str]) -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    out: Dict[str, Dict[str, Any]] = {c: _na() for c in codes}
    sources_done: List[str] = []
    for name, fn in SOURCE_STACK:
        try:
            partial = fn(codes)
            sources_done.append(name)
        except Exception as e:  # noqa: BLE001
            logger.warning("机构家数源 %s 失败: %s", name, e)
            sources_done.append(f"{name}:error")
            continue
        for code in codes:
            if out[code].get("inst_holder_count") is not None:
                continue
            hit = partial.get(code, _na())
            if hit.get("inst_holder_count") is not None:
                out[code] = hit
    return out, sources_done


class InstHolderLiveProvider:
    """东财 live 批量 + 单股降级 (内存缓存)。"""

    def __init__(self, cache_ttl: float = 3600.0):
        self._cache_ttl = cache_ttl
        self._bulk: Dict[str, int] = {}
        self._report_date: Optional[str] = None
        self._bulk_ts: float = 0.0
        self._lock = threading.Lock()

    def _pick_bulk_date(self) -> Optional[str]:
        min_year = date.today().year
        for rd in current_year_report_dates():
            if int(rd[:4]) < min_year:
                continue
            try:
                total = em_total_for_date(rd)
            except Exception as e:  # noqa: BLE001
                logger.debug("东财机构持股统计 %s 失败: %s", rd, e)
                continue
            if total >= _MIN_BULK_ROWS:
                return rd
        return None

    def _load_bulk(self) -> None:
        with self._lock:
            if self._bulk_ts and (time.time() - self._bulk_ts) < self._cache_ttl:
                return
            rd = self._pick_bulk_date()
            merged: Dict[str, int] = {}
            if rd:
                try:
                    rows = fetch_all_for_report_date(rd)
                    merged = {
                        r["code"]: r["holder_count"]
                        for r in rows
                        if r.get("is_complete")
                    }
                except Exception as e:  # noqa: BLE001
                    logger.warning("东财机构持股 live bulk 失败: %s", e)
            self._bulk = merged
            self._report_date = rd
            self._bulk_ts = time.time()

    def get_batch(self, codes: List[str]) -> Dict[str, Dict[str, Any]]:
        if not codes or not current_year_report_dates():
            return {c: _na() for c in codes}
        out: Dict[str, Dict[str, Any]] = {}
        self._load_bulk()
        missing: List[str] = []
        for code in codes:
            bare = bare_code(code)
            if bare in self._bulk and self._report_date:
                out[code] = {
                    "inst_holder_count": self._bulk[bare],
                    "inst_holder_report_date": self._report_date,
                    "inst_holder_source": "eastmoney",
                }
            else:
                missing.append(code)
        for code in missing:
            hit = fetch_one(code, current_year_report_dates())
            out[code] = hit if hit else _na()
        return out


class InstHolderFetchService:
    """选股完成后后台异步抓取机构家数。"""

    def __init__(self):
        self._status: Dict[str, Dict[str, Any]] = {}
        self._results: Dict[str, Dict[str, Dict[str, Any]]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(username: str, kind: str) -> str:
        return f"{username}|{kind}"

    def status(self, username: str, kind: str) -> Dict[str, Any]:
        with self._lock:
            st = self._status.get(self._key(username, kind))
            if not st:
                return {"running": False, "ready": bool(self._results.get(self._key(username, kind)))}
            return dict(st)

    def result(self, username: str, kind: str) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return dict(self._results.get(self._key(username, kind), {}))

    def start(self, username: str, kind: str, codes: List[str]) -> None:
        if kind != "stock" or not codes:
            return
        key = self._key(username, kind)
        with self._lock:
            self._status[key] = {
                "running": True,
                "started": time.time(),
                "elapsed": 0.0,
                "count": len(codes),
                "sources_done": [],
                "ready": False,
                "error": None,
            }
            self._results[key] = {}
        threading.Thread(target=self._run, args=(key, codes), daemon=True).start()

    def _run(self, key: str, codes: List[str]) -> None:
        t0 = time.time()
        try:
            merged, sources_done = fetch_inst_holders_multi_source(codes)
            with self._lock:
                self._results[key] = merged
                self._status[key] = {
                    "running": False,
                    "elapsed": round(time.time() - t0, 1),
                    "count": len(codes),
                    "sources_done": sources_done,
                    "ready": True,
                    "error": None,
                }
            logger.info("机构家数异步完成: %d 只, 源=%s", len(codes), sources_done)
        except Exception as e:  # noqa: BLE001
            logger.exception("机构家数异步失败: %s", e)
            with self._lock:
                self._status[key] = {
                    "running": False,
                    "elapsed": round(time.time() - t0, 1),
                    "count": len(codes),
                    "sources_done": [],
                    "ready": False,
                    "error": str(e),
                }


_fetch_service: Optional[InstHolderFetchService] = None
_fetch_lock = threading.Lock()


def get_inst_holder_fetch_service() -> InstHolderFetchService:
    global _fetch_service
    with _fetch_lock:
        if _fetch_service is None:
            _fetch_service = InstHolderFetchService()
        return _fetch_service
