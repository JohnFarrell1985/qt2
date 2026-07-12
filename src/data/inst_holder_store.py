"""机构持有家数 — PostgreSQL 读写。"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from src.common.db import get_session
from src.common.logger import get_logger
from src.data.inst_holder_em import bare_code
from src.data.models import StockInstHolder

logger = get_logger(__name__)

_FLUSH_SIZE = 200


def upsert_rows(rows: List[dict]) -> int:
    if not rows:
        return 0
    n = 0
    for i in range(0, len(rows), _FLUSH_SIZE):
        batch = rows[i : i + _FLUSH_SIZE]
        with get_session() as session:
            stmt = insert(StockInstHolder).values(batch)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_sih_code_date_src",
                set_={
                    "holder_count": stmt.excluded.holder_count,
                    "is_complete": stmt.excluded.is_complete,
                    "updated_at": datetime.now(),
                },
            )
            session.execute(stmt)
        n += len(batch)
    return n


def lookup_latest_batch(codes: List[str], min_year: Optional[int] = None) -> Dict[str, Dict[str, Any]]:
    """每只股票取当年最新完整披露的机构家数。"""
    if not codes:
        return {}
    min_year = min_year if min_year is not None else date.today().year
    bare_list = list({bare_code(c) for c in codes})
    bare_to_qmt: Dict[str, str] = {}
    for c in codes:
        bare_to_qmt[bare_code(c)] = c

    sql = text("""
        SELECT DISTINCT ON (code)
            code, report_date, holder_count, source, is_complete
        FROM stock_inst_holder
        WHERE code = ANY(:codes)
          AND is_complete = true
          AND EXTRACT(YEAR FROM report_date) >= :min_year
        ORDER BY code, report_date DESC
    """)
    try:
        with get_session(readonly=True) as session:
            rows = session.execute(sql, {"codes": bare_list, "min_year": min_year}).fetchall()
    except Exception as e:  # noqa: BLE001
        logger.debug("机构家数 DB 查询失败: %s", e)
        return {}

    out: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        qmt = bare_to_qmt.get(r[0], r[0])
        out[qmt] = {
            "inst_holder_count": int(r[2]),
            "inst_holder_report_date": r[1].isoformat() if r[1] else None,
            "inst_holder_source": "database",
        }
    return out


def count_for_report_date(report_date: date, complete_only: bool = False) -> int:
    sql = "SELECT COUNT(*) FROM stock_inst_holder WHERE report_date = :rd"
    params: dict = {"rd": report_date}
    if complete_only:
        sql += " AND is_complete = true"
    try:
        with get_session(readonly=True) as session:
            return int(session.execute(text(sql), params).scalar() or 0)
    except Exception:  # noqa: BLE001
        return 0
