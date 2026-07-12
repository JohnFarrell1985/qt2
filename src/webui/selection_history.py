"""选股/选基历史记录 — PostgreSQL ``paper_selection_runs``。"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from src.common.db import get_session
from src.common.logger import get_logger

logger = get_logger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS paper_selection_runs (
    id           BIGSERIAL PRIMARY KEY,
    username     VARCHAR(64) NOT NULL,
    kind         VARCHAR(8)  NOT NULL,
    strategy_id  VARCHAR(64) NOT NULL,
    trade_date   DATE        NOT NULL,
    params       JSONB       NOT NULL DEFAULT '{}',
    items        JSONB       NOT NULL DEFAULT '[]',
    count        INTEGER     NOT NULL DEFAULT 0,
    elapsed      DOUBLE PRECISION,
    is_current   BOOLEAN     NOT NULL DEFAULT false,
    created_at   TIMESTAMP   DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_psr_user_kind ON paper_selection_runs(username, kind, id DESC);
"""

_initialized = False


def ensure_schema() -> None:
    global _initialized
    if _initialized:
        return
    try:
        with get_session() as s:
            for stmt in filter(None, (x.strip() for x in _DDL.split(";"))):
                if stmt:
                    s.execute(text(stmt))
        _initialized = True
        logger.debug("paper_selection_runs 表已就绪")
    except Exception as e:  # noqa: BLE001
        logger.error("paper_selection_runs 建表失败: %s", e)
        raise


def _json_load(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, (dict, list)):
        return val
    if isinstance(val, str):
        return json.loads(val)
    return val


def save_run(
    username: str,
    kind: str,
    strategy_id: str,
    trade_date: date,
    params: Dict[str, Any],
    items: List[Dict[str, Any]],
    elapsed: float,
) -> int:
    ensure_schema()
    payload_items = json.dumps(items, ensure_ascii=False)
    payload_params = json.dumps(params or {}, ensure_ascii=False)
    with get_session() as s:
        s.execute(
            text(
                "UPDATE paper_selection_runs SET is_current = false "
                "WHERE username = :u AND kind = :k AND is_current = true"
            ),
            {"u": username, "k": kind},
        )
        row = s.execute(
            text(
                "INSERT INTO paper_selection_runs "
                "(username, kind, strategy_id, trade_date, params, items, count, elapsed, is_current) "
                "VALUES (:u, :k, :sid, :td, CAST(:params AS JSONB), CAST(:items AS JSONB), "
                ":cnt, :elapsed, true) RETURNING id"
            ),
            {
                "u": username,
                "k": kind,
                "sid": strategy_id,
                "td": trade_date,
                "params": payload_params,
                "items": payload_items,
                "cnt": len(items),
                "elapsed": elapsed,
            },
        ).fetchone()
    run_id = int(row[0])
    logger.info("选股记录已保存: user=%s kind=%s id=%d count=%d", username, kind, run_id, len(items))
    return run_id


def get_current(username: str, kind: str) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with get_session(readonly=True) as s:
        row = s.execute(
            text(
                "SELECT id, kind, strategy_id, trade_date, params, items, count, elapsed, is_current, created_at "
                "FROM paper_selection_runs "
                "WHERE username = :u AND kind = :k AND is_current = true "
                "ORDER BY id DESC LIMIT 1"
            ),
            {"u": username, "k": kind},
        ).fetchone()
    return _row_to_run(row) if row else None


def get_run(username: str, run_id: int) -> Optional[Dict[str, Any]]:
    ensure_schema()
    with get_session(readonly=True) as s:
        row = s.execute(
            text(
                "SELECT id, kind, strategy_id, trade_date, params, items, count, elapsed, is_current, created_at "
                "FROM paper_selection_runs WHERE username = :u AND id = :id"
            ),
            {"u": username, "id": run_id},
        ).fetchone()
    return _row_to_run(row) if row else None


def list_runs(username: str, kind: str, limit: int = 40) -> List[Dict[str, Any]]:
    ensure_schema()
    with get_session(readonly=True) as s:
        rows = s.execute(
            text(
                "SELECT id, kind, strategy_id, trade_date, params, items, count, elapsed, is_current, created_at "
                "FROM paper_selection_runs WHERE username = :u AND kind = :k "
                "ORDER BY id DESC LIMIT :lim"
            ),
            {"u": username, "k": kind, "lim": limit},
        ).fetchall()
    return [_row_to_summary(r) for r in rows]


def update_current_items(username: str, kind: str, items: List[Dict[str, Any]]) -> None:
    ensure_schema()
    payload = json.dumps(items, ensure_ascii=False)
    with get_session() as s:
        s.execute(
            text(
                "UPDATE paper_selection_runs SET items = CAST(:items AS JSONB), count = :cnt "
                "WHERE username = :u AND kind = :k AND is_current = true"
            ),
            {"u": username, "k": kind, "items": payload, "cnt": len(items)},
        )


def _row_to_run(row) -> Dict[str, Any]:
    td = row[3]
    if hasattr(td, "isoformat"):
        td = td.isoformat()
    created = row[9]
    if isinstance(created, datetime):
        created = created.isoformat(sep=" ", timespec="seconds")
    return {
        "run_id": int(row[0]),
        "kind": row[1],
        "strategy_id": row[2],
        "trade_date": td,
        "params": _json_load(row[4]) or {},
        "items": _json_load(row[5]) or [],
        "count": int(row[6] or 0),
        "elapsed": row[7],
        "is_current": bool(row[8]),
        "created_at": created,
    }


def _row_to_summary(row) -> Dict[str, Any]:
    td = row[3]
    if hasattr(td, "isoformat"):
        td = td.isoformat()
    created = row[9]
    if isinstance(created, datetime):
        created = created.isoformat(sep=" ", timespec="seconds")
    return {
        "run_id": int(row[0]),
        "kind": row[1],
        "strategy_id": row[2],
        "trade_date": td,
        "count": int(row[6] or 0),
        "elapsed": row[7],
        "is_current": bool(row[8]),
        "created_at": created,
    }
