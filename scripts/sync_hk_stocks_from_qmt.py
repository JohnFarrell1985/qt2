# -*- coding: utf-8 -*-
"""从 Mini QMT 同步港股标的到 ``stocks`` 表 (sector=港股通).

用法:
    uv run python scripts/sync_hk_stocks_from_qmt.py
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.dialects.postgresql import insert

from src.common.db import get_session
from src.common.db_batch import DEFAULT_TABLE_UPSERT_FLUSH
from src.common.logger import get_logger
from src.data.models import Stock
from src.data.qmt_client import QMTClient

logger = get_logger(__name__)


def _parse_open_date(v) -> object | None:
    if not v:
        return None
    try:
        s = str(v).strip()
        if len(s) >= 8:
            return datetime.strptime(s[:8], "%Y%m%d").date()
    except Exception:
        pass
    return None


def _find_hk_sector(client: QMTClient) -> tuple[str, list[str]]:
    """返回首个成分均为 ``*.HK`` 的板块名及代码列表."""
    for sector in client.get_sector_list():
        if "港" not in sector and "HK" not in sector.upper():
            continue
        codes = client.get_stock_list_in_sector(sector)
        if codes and str(codes[0]).upper().endswith(".HK"):
            return sector, codes
    return "", []


def sync_hk_stocks_from_qmt() -> int:
    client = QMTClient()
    sector, codes = _find_hk_sector(client)
    if not codes:
        logger.error("QMT 未找到含 .HK 成分的板块")
        return 0

    logger.info("QMT 港股板块 %r: %d 只", sector, len(codes))
    pending: list[dict] = []
    total = 0
    failed = 0

    for full_code in codes:
        code = full_code.split(".")[0]
        name = code
        list_date = None
        try:
            detail = client.get_instrument_detail(full_code)
            if detail:
                nm = (detail.get("InstrumentName") or "").strip()
                if nm:
                    name = nm[:50]
                list_date = _parse_open_date(detail.get("OpenDate"))
        except Exception as exc:
            failed += 1
            if failed <= 5:
                logger.debug("QMT %s detail 失败: %s", full_code, exc)

        pending.append({
            "code": code,
            "name": name,
            "exchange": "HK",
            "sector": "港股通",
            "list_date": list_date,
            "updated_at": datetime.now(),
        })
        if len(pending) >= DEFAULT_TABLE_UPSERT_FLUSH:
            with get_session() as session:
                for row in pending:
                    stmt = insert(Stock).values(**row)
                    ex = stmt.excluded
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["code"],
                        set_={
                            "name": ex.name,
                            "exchange": ex.exchange,
                            "sector": ex.sector,
                            "list_date": ex.list_date,
                            "updated_at": ex.updated_at,
                        },
                    )
                    session.execute(stmt)
            total += len(pending)
            pending.clear()

    if pending:
        with get_session() as session:
            for row in pending:
                stmt = insert(Stock).values(**row)
                ex = stmt.excluded
                stmt = stmt.on_conflict_do_update(
                    index_elements=["code"],
                    set_={
                        "name": ex.name,
                        "exchange": ex.exchange,
                        "sector": ex.sector,
                        "list_date": ex.list_date,
                        "updated_at": ex.updated_at,
                    },
                )
                session.execute(stmt)
        total += len(pending)

    logger.info("港股标的入库完成: %d 条, detail 异常约 %d 次", total, failed)
    return total


def main() -> int:
    n = sync_hk_stocks_from_qmt()
    print(f"synced {n} hk stocks")
    return 0 if n > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
