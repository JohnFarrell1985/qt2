"""模拟盘持久化存储 (独立于业务真实表)

**所有模拟盘数据仅落在下列全新表, 且本模块只对这些表做写操作**, 绝不修改行情等真实业务表:
  - ``paper_users``      用户 (仅用户名 + 口令哈希)
  - ``paper_accounts``   账户状态 (现金/持仓/委托/资金/交易日, 以 JSONB 存储引擎状态)
  - ``paper_trades``     成交流水 (逐条可查询/可删除, 按用户名隔离)

行情/日线读取仍通过 ``quotes.py`` 的只读会话, 与此处写入完全隔离。

提供两种实现:
  - :class:`PaperStore`   PostgreSQL 实现 (生产)
  - :class:`MemoryStore`  纯内存实现 (测试, 无需 DB)
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from src.common.logger import get_logger

logger = get_logger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS paper_users (
    username    VARCHAR(64) PRIMARY KEY,
    pwd_hash    VARCHAR(256) NOT NULL,
    salt        VARCHAR(64)  NOT NULL,
    created_at  TIMESTAMP    DEFAULT now()
);

CREATE TABLE IF NOT EXISTS paper_accounts (
    username    VARCHAR(64) PRIMARY KEY,
    state       JSONB       NOT NULL,
    updated_at  TIMESTAMP   DEFAULT now()
);

CREATE TABLE IF NOT EXISTS paper_trades (
    id          BIGSERIAL   PRIMARY KEY,
    username    VARCHAR(64) NOT NULL,
    trade_id    VARCHAR(32) NOT NULL,
    order_id    VARCHAR(32),
    code        VARCHAR(16),
    name        VARCHAR(64),
    direction   VARCHAR(8),
    price       DOUBLE PRECISION,
    quantity    INTEGER,
    amount      DOUBLE PRECISION,
    fees        DOUBLE PRECISION,
    fee_detail  JSONB,
    trade_date  VARCHAR(16),
    ts          VARCHAR(32),
    created_at  TIMESTAMP   DEFAULT now(),
    UNIQUE (username, trade_id)
);

CREATE INDEX IF NOT EXISTS idx_paper_trades_user ON paper_trades(username, id DESC);
"""


def _session():
    from src.common.db import get_session

    return get_session(readonly=False)


class PaperStore:
    """PostgreSQL 存储 (仅操作 ``paper_*`` 表)。"""

    _initialized = False
    _init_lock = threading.Lock()

    def __init__(self):
        self._ensure_schema()

    @classmethod
    def _ensure_schema(cls) -> None:
        if cls._initialized:
            return
        with cls._init_lock:
            if cls._initialized:
                return
            try:
                with _session() as s:
                    for stmt in filter(None, (x.strip() for x in _DDL.split(";"))):
                        s.execute(text(stmt))
                cls._initialized = True
                logger.info("模拟盘表已就绪 (paper_users / paper_accounts / paper_trades)")
            except Exception as e:  # noqa: BLE001
                logger.error("模拟盘建表失败: %s", e)
                raise

    # ------------------------------------------------------------------
    # 用户
    # ------------------------------------------------------------------
    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        with _session() as s:
            row = s.execute(
                text("SELECT username, pwd_hash, salt FROM paper_users WHERE username = :u"),
                {"u": username},
            ).fetchone()
        if not row:
            return None
        return {"username": row[0], "pwd_hash": row[1], "salt": row[2]}

    def create_user(self, username: str, pwd_hash: str, salt: str) -> None:
        with _session() as s:
            s.execute(
                text(
                    "INSERT INTO paper_users (username, pwd_hash, salt) "
                    "VALUES (:u, :h, :s) ON CONFLICT (username) DO NOTHING"
                ),
                {"u": username, "h": pwd_hash, "s": salt},
            )

    def update_password(self, username: str, pwd_hash: str, salt: str) -> None:
        with _session() as s:
            s.execute(
                text("UPDATE paper_users SET pwd_hash = :h, salt = :s WHERE username = :u"),
                {"u": username, "h": pwd_hash, "s": salt},
            )

    def list_users(self) -> List[str]:
        with _session() as s:
            rows = s.execute(text("SELECT username FROM paper_users ORDER BY username")).fetchall()
        return [r[0] for r in rows]

    # ------------------------------------------------------------------
    # 账户状态
    # ------------------------------------------------------------------
    def load_state(self, username: str) -> Optional[Dict[str, Any]]:
        with _session() as s:
            row = s.execute(
                text("SELECT state FROM paper_accounts WHERE username = :u"),
                {"u": username},
            ).fetchone()
        if not row or row[0] is None:
            return None
        st = row[0]
        return st if isinstance(st, dict) else json.loads(st)

    def save_state(self, username: str, state: Dict[str, Any]) -> None:
        payload = json.dumps(state, ensure_ascii=False)
        with _session() as s:
            s.execute(
                text(
                    "INSERT INTO paper_accounts (username, state, updated_at) "
                    "VALUES (:u, CAST(:st AS JSONB), now()) "
                    "ON CONFLICT (username) DO UPDATE SET state = EXCLUDED.state, updated_at = now()"
                ),
                {"u": username, "st": payload},
            )

    # ------------------------------------------------------------------
    # 成交流水
    # ------------------------------------------------------------------
    def add_trade(self, username: str, trade: Dict[str, Any]) -> None:
        with _session() as s:
            s.execute(
                text(
                    "INSERT INTO paper_trades "
                    "(username, trade_id, order_id, code, name, direction, price, quantity, "
                    " amount, fees, fee_detail, trade_date, ts) VALUES "
                    "(:u, :tid, :oid, :code, :name, :dir, :price, :qty, :amt, :fees, "
                    " CAST(:fd AS JSONB), :td, :ts) "
                    "ON CONFLICT (username, trade_id) DO NOTHING"
                ),
                {
                    "u": username,
                    "tid": trade["trade_id"],
                    "oid": trade.get("order_id"),
                    "code": trade.get("code"),
                    "name": trade.get("name"),
                    "dir": trade.get("direction"),
                    "price": trade.get("price"),
                    "qty": trade.get("quantity"),
                    "amt": trade.get("amount"),
                    "fees": trade.get("fees"),
                    "fd": json.dumps(trade.get("fee_detail") or {}, ensure_ascii=False),
                    "td": trade.get("trade_date"),
                    "ts": trade.get("ts"),
                },
            )

    def list_trades(self, username: str, limit: int = 100) -> List[Dict[str, Any]]:
        with _session() as s:
            rows = s.execute(
                text(
                    "SELECT trade_id, order_id, code, name, direction, price, quantity, "
                    "amount, fees, fee_detail, trade_date, ts FROM paper_trades "
                    "WHERE username = :u ORDER BY id DESC LIMIT :lim"
                ),
                {"u": username, "lim": limit},
            ).fetchall()
        out = []
        for r in rows:
            fd = r[9]
            if isinstance(fd, str):
                try:
                    fd = json.loads(fd)
                except Exception:  # noqa: BLE001
                    fd = {}
            out.append({
                "trade_id": r[0], "order_id": r[1], "code": r[2], "name": r[3],
                "direction": r[4], "price": r[5], "quantity": r[6], "amount": r[7],
                "fees": r[8], "fee_detail": fd or {}, "trade_date": r[10], "ts": r[11],
            })
        return out

    def delete_trade(self, username: str, trade_id: str) -> bool:
        with _session() as s:
            res = s.execute(
                text("DELETE FROM paper_trades WHERE username = :u AND trade_id = :t"),
                {"u": username, "t": trade_id},
            )
        return (res.rowcount or 0) > 0

    def clear_trades(self, username: str) -> None:
        with _session() as s:
            s.execute(text("DELETE FROM paper_trades WHERE username = :u"), {"u": username})


class MemoryStore:
    """纯内存存储 (测试用, 语义与 :class:`PaperStore` 一致)。"""

    def __init__(self):
        self._users: Dict[str, Dict[str, Any]] = {}
        self._states: Dict[str, Dict[str, Any]] = {}
        self._trades: Dict[str, List[Dict[str, Any]]] = {}
        self._lock = threading.RLock()

    def get_user(self, username):
        with self._lock:
            u = self._users.get(username)
            return dict(u) if u else None

    def create_user(self, username, pwd_hash, salt):
        with self._lock:
            self._users.setdefault(username, {"username": username, "pwd_hash": pwd_hash, "salt": salt})

    def update_password(self, username, pwd_hash, salt):
        with self._lock:
            if username in self._users:
                self._users[username].update(pwd_hash=pwd_hash, salt=salt)

    def list_users(self):
        with self._lock:
            return sorted(self._users)

    def load_state(self, username):
        with self._lock:
            st = self._states.get(username)
            return json.loads(json.dumps(st)) if st is not None else None

    def save_state(self, username, state):
        with self._lock:
            self._states[username] = json.loads(json.dumps(state))

    def add_trade(self, username, trade):
        with self._lock:
            lst = self._trades.setdefault(username, [])
            if any(t["trade_id"] == trade["trade_id"] for t in lst):
                return
            rec = dict(trade)
            rec["_ord"] = datetime.now().timestamp() + len(lst) * 1e-6
            lst.append(rec)

    def list_trades(self, username, limit=100):
        with self._lock:
            lst = sorted(self._trades.get(username, []), key=lambda t: t.get("_ord", 0), reverse=True)
            return [{k: v for k, v in t.items() if k != "_ord"} for t in lst[:limit]]

    def delete_trade(self, username, trade_id):
        with self._lock:
            lst = self._trades.get(username, [])
            n = len(lst)
            self._trades[username] = [t for t in lst if t["trade_id"] != trade_id]
            return len(self._trades[username]) < n

    def clear_trades(self, username):
        with self._lock:
            self._trades[username] = []
