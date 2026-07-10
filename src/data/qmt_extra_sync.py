# -*- coding: utf-8 -*-
"""QMT 可下载但尚未纳入 unified_collect 的数据同步.

覆盖:
- 板块成分 (``sector_stock``)
- 除权因子 (``stock_divid_factor``)
- 可转债日线 (``cb_daily``)
- 指数权重直写 (``index_weight``)
- 基础元数据下载 (板块/指数权重/转债/退市合约)
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from datetime import date, datetime
from typing import Any, Callable

import pandas as pd
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from src.common.db import get_session
from src.common.db_batch import DEFAULT_TABLE_UPSERT_FLUSH, log_upsert_commit
from src.common.logger import get_logger
from src.data.cb_data import CBDataSync
from src.data.download_engine import get_default_start
from src.data.models import IndexWeight, SectorStock, Stock, StockDividFactor
from src.data.qmt_client import QMTClient
from src.data.sync_heartbeat import QMT_STALL_NO_DATA_SEC, query_table_counts

logger = get_logger(__name__)

DEFAULT_INDEX_CODES = (
    "000300.SH", "000905.SH", "000852.SH", "000016.SH",
    "399006.SZ", "000688.SH",
)

# MiniQMT 常见不支持项 (探测结论); 调用前跳过并记日志
_MINI_QMT_SKIP = frozenset({
    "download_holiday_data",
    "download_etf_info",
    "get_etf_info",
    "get_ipo_info",
    "get_period_list",
})


def _qmt_symbol(code: str) -> str:
    c = (code or "").strip()
    if "." in c:
        return c
    clean = c.upper().replace("HK", "").strip()
    if clean.isdigit() and len(clean) <= 5:
        return f"{clean.zfill(5)}.HK"
    pure = c[:6]
    if pure.startswith(("6", "5", "9")):
        return f"{pure}.SH"
    return f"{pure}.SZ"


def _parse_ex_date(ts: Any) -> date | None:
    if isinstance(ts, pd.Timestamp):
        return ts.date()
    s = str(ts).strip()
    digits = "".join(ch for ch in s if ch.isdigit())[:8]
    if len(digits) == 8:
        try:
            return datetime.strptime(digits, "%Y%m%d").date()
        except ValueError:
            return None
    return None


def _safe_float(v: Any) -> float | None:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class QmtExtraSync:
    def __init__(
        self,
        client: QMTClient | None = None,
        on_progress: Callable[[str], None] | None = None,
    ):
        self.client = client or QMTClient()
        self._on_progress = on_progress

    def _phase(self, name: str) -> None:
        if self._on_progress:
            self._on_progress(name)

    def download_base_metadata(self) -> dict[str, str]:
        """下载 QMT 本地缓存类元数据; 单项失败不中断."""
        self._phase("base_metadata")
        results: dict[str, str] = {}

        # 板块列表已可用则跳过可能长时间阻塞的 download_sector_data
        try:
            sectors = self.client.get_sector_list()
            if sectors:
                results["sector_data"] = f"skip:cached({len(sectors)})"
                logger.info("板块列表已有 %d 个, 跳过 download_sector_data", len(sectors))
            else:
                self.client.download_sector_data()
                results["sector_data"] = "ok"
                logger.info("QMT 元数据下载完成: sector_data")
        except Exception as exc:
            results["sector_data"] = f"err:{exc}"
            logger.warning("QMT 元数据 sector_data 失败(可忽略): %s", exc)

        for name, fn in [
            ("index_weight", self.client.download_index_weight),
            ("cb_data", self.client.download_cb_data),
            ("history_contracts", self.client.download_history_contracts),
        ]:
            if name in _MINI_QMT_SKIP:
                results[name] = "skip:mini_qmt"
                continue
            try:
                logger.info("QMT 元数据下载开始: %s", name)
                fn()
                results[name] = "ok"
                logger.info("QMT 元数据下载完成: %s", name)
            except Exception as exc:
                results[name] = f"err:{exc}"
                logger.warning("QMT 元数据 %s 失败(可忽略): %s", name, exc)
        return results

    def sync_sector_members(self) -> int:
        """将全部 QMT 板块成分写入 ``sector_stock``."""
        self._phase("sector_members")
        sectors = self.client.get_sector_list()
        if not sectors:
            logger.warning("QMT 板块列表为空")
            return 0

        pending: list[dict] = []
        total = 0
        nonempty = 0
        for i, sector in enumerate(sectors, 1):
            try:
                codes = self.client.get_stock_list_in_sector(sector)
            except Exception as exc:
                logger.debug("板块 %r 成分获取失败: %s", sector, exc)
                continue
            if not codes:
                continue
            nonempty += 1
            now = datetime.now()
            for full_code in codes:
                pending.append({
                    "sector_name": sector[:100],
                    "stock_code": str(full_code)[:20],
                    "updated_at": now,
                })
                if len(pending) >= DEFAULT_TABLE_UPSERT_FLUSH:
                    total += self._flush_sector_rows(pending)
                    pending.clear()
            if i % 200 == 0:
                logger.info(
                    "板块成分进度 %d/%d, 非空 %d, 已写入 %d 行",
                    i, len(sectors), nonempty, total,
                )

        if pending:
            total += self._flush_sector_rows(pending)

        logger.info(
            "QMT 板块成分同步: %d 行, 非空板块 %d/%d",
            total, nonempty, len(sectors),
        )
        return total

    def _flush_sector_rows(self, rows: list[dict]) -> int:
        with get_session() as session:
            for row in rows:
                stmt = insert(SectorStock).values(**row)
                ex = stmt.excluded
                stmt = stmt.on_conflict_do_update(
                    index_elements=["sector_name", "stock_code"],
                    set_={"updated_at": ex.updated_at},
                )
                session.execute(stmt)
        log_upsert_commit("qmt.sector_stock", len(rows))
        return len(rows)

    def sync_divid_factors(
        self,
        start_time: str = "20000101",
        end_time: str = "",
    ) -> int:
        """同步全部 ``stocks`` 标的除权因子."""
        self._phase("divid_factors")
        if not end_time:
            end_time = datetime.now().strftime("%Y%m%d")

        with get_session() as session:
            codes = [r[0] for r in session.query(Stock.code).all()]

        pending: list[dict] = []
        total = 0
        failed = 0
        for i, code in enumerate(codes, 1):
            sym = _qmt_symbol(code)
            try:
                df = self.client.get_divid_factors(sym, start_time, end_time)
            except Exception as exc:
                failed += 1
                if failed <= 5:
                    logger.debug("除权因子 %s 失败: %s", code, exc)
                continue
            if df is None or not hasattr(df, "iterrows") or df.empty:
                continue
            now = datetime.now()
            for ts, row in df.iterrows():
                ex_d = _parse_ex_date(ts)
                if not ex_d:
                    continue
                pending.append({
                    "code": code,
                    "ex_date": ex_d,
                    "interest": _safe_float(row.get("interest")),
                    "stock_bonus": _safe_float(row.get("stockBonus")),
                    "stock_gift": _safe_float(row.get("stockGift")),
                    "allot_num": _safe_float(row.get("allotNum")),
                    "allot_price": _safe_float(row.get("allotPrice")),
                    "gugai": _safe_float(row.get("gugai")),
                    "dr": _safe_float(row.get("dr")),
                    "updated_at": now,
                })
                if len(pending) >= DEFAULT_TABLE_UPSERT_FLUSH:
                    total += self._flush_divid_rows(pending)
                    pending.clear()
            if i % 500 == 0:
                logger.info("除权因子进度 %d/%d, 已写入 %d", i, len(codes), total)

        if pending:
            total += self._flush_divid_rows(pending)

        logger.info("除权因子同步完成: %d 行, 失败约 %d", total, failed)
        return total

    def _flush_divid_rows(self, rows: list[dict]) -> int:
        with get_session() as session:
            for row in rows:
                stmt = insert(StockDividFactor).values(**row)
                ex = stmt.excluded
                stmt = stmt.on_conflict_do_update(
                    index_elements=["code", "ex_date"],
                    set_={
                        "interest": ex.interest,
                        "stock_bonus": ex.stock_bonus,
                        "stock_gift": ex.stock_gift,
                        "allot_num": ex.allot_num,
                        "allot_price": ex.allot_price,
                        "gugai": ex.gugai,
                        "dr": ex.dr,
                        "updated_at": ex.updated_at,
                    },
                )
                session.execute(stmt)
        log_upsert_commit("qmt.stock_divid_factor", len(rows))
        return len(rows)

    def sync_index_weights_qmt(
        self,
        index_codes: tuple[str, ...] = DEFAULT_INDEX_CODES,
    ) -> int:
        """从 QMT 直写指数成分权重."""
        self._phase("index_weights")
        try:
            self.client.download_index_weight()
        except Exception as exc:
            logger.warning("download_index_weight: %s", exc)

        total = 0
        now = datetime.now()
        for ic in index_codes:
            try:
                weights = self.client.get_index_weight(ic) or {}
            except Exception as exc:
                logger.warning("get_index_weight %s: %s", ic, exc)
                continue
            if not weights:
                continue
            pending: list[dict] = []
            for stock_code, w in weights.items():
                pending.append({
                    "index_code": ic,
                    "stock_code": str(stock_code),
                    "weight": float(w) if w is not None else None,
                    "updated_at": now,
                })
            with get_session() as session:
                for row in pending:
                    stmt = insert(IndexWeight).values(**row)
                    ex = stmt.excluded
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["index_code", "stock_code"],
                        set_={"weight": ex.weight, "updated_at": ex.updated_at},
                    )
                    session.execute(stmt)
            total += len(pending)
            logger.info("指数权重 %s: %d 只", ic, len(pending))
        return total

    def sync_cb_all(self, start_time: str = "") -> dict[str, int]:
        self._phase("cb_sync")
        cb = CBDataSync(self.client)
        if not start_time:
            start_time = get_default_start("1d")
        end_time = datetime.now().strftime("%Y%m%d")
        out: dict[str, int] = {"cb_info": 0, "cb_daily": 0}
        out["cb_info"] = cb.sync_cb_info()
        before_cb = query_table_counts(("cb_daily",)).get("cb_daily", 0)

        def _dl_daily() -> int:
            return cb.sync_cb_daily(start_time=start_time, end_time=end_time)

        try:
            with ThreadPoolExecutor(max_workers=1) as ex:
                fut = ex.submit(_dl_daily)
                out["cb_daily"] = fut.result(timeout=QMT_STALL_NO_DATA_SEC)
        except FuturesTimeout:
            logger.warning(
                "转债日线: %.0fs 无落盘/未完成 → 判定 QMT 无法下载, 跳过",
                QMT_STALL_NO_DATA_SEC,
            )
            out["cb_daily"] = query_table_counts(("cb_daily",)).get("cb_daily", 0) - before_cb
        return out

    def run_all(
        self,
        *,
        sync_sectors: bool = True,
        sync_divid: bool = True,
        sync_cb: bool = True,
        sync_index_weights: bool = True,
        divid_start: str = "20000101",
    ) -> dict[str, Any]:
        out: dict[str, Any] = {}
        out["base_metadata"] = self.download_base_metadata()
        # 先同步有明确落盘反馈的项, 大块板块成分放最后
        if sync_divid:
            out["divid_factors"] = self.sync_divid_factors(start_time=divid_start)
        if sync_index_weights:
            out["index_weights"] = self.sync_index_weights_qmt()
        if sync_cb:
            out.update(self.sync_cb_all())
        if sync_sectors:
            out["sector_members"] = self.sync_sector_members()
        return out


def main() -> int:
    from src.common.db import init_database

    init_database()
    results = QmtExtraSync().run_all()
    print(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
