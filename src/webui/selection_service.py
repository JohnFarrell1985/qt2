"""选股 / 选基 服务层 (供 Web UI 调用)

**与 QMT 无关** —— 只读 PostgreSQL 日线、在内存中调度已注册策略。

- 策略调度: 按 ``strategy_id`` 从 ``src.selection.strategy`` 注册表取实现类并调用 ``screen``。
- 具体筛选逻辑在各策略模块 (如 ``strategies/bull_launch.py``), 本层不 import ``ma_screener``。
- 全市场初筛耗时较长 → 后台线程 + 按用户/类型隔离的状态查询。
"""
from __future__ import annotations

import threading
import time
from datetime import date
from typing import Any, Dict, List, Optional

from sqlalchemy import text

import src.selection.strategies  # noqa: F401 — 加载并注册策略实现
from src.common.logger import get_logger
from src.selection.strategy import get_strategy, strategy_catalog

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# 结果富化 (通用, 与具体策略解耦)
# ---------------------------------------------------------------------------
def _stock_names(codes: List[str]) -> Dict[str, str]:
    if not codes:
        return {}
    try:
        from src.common.db import get_session

        with get_session(readonly=True) as s:
            rows = s.execute(
                text("SELECT code, name FROM stocks WHERE code = ANY(:codes)"),
                {"codes": list(codes)},
            ).fetchall()
        return {r[0]: r[1] for r in rows}
    except Exception:  # noqa: BLE001
        return {}


def enrich(kind: str, candidates: List[str], snapshots: Dict[str, dict], strategy_id: str) -> List[Dict[str, Any]]:
    strat_cls = get_strategy(strategy_id)
    if kind == "etf":
        from src.selection.etf_screener import load_etf_names
        names = load_etf_names()
    else:
        names = _stock_names(candidates)

    out = []
    for code in candidates:
        snap = snapshots.get(code, {})
        out.append({
            "code": code,
            "name": names.get(code, ""),
            "close": snap.get("close"),
            "score": snap.get("composite_score"),
            "tier": snap.get("tier", ""),
            "ma5_dist_pct": snap.get("ma5_dist_pct"),
            "vol_shrink_ratio": snap.get("vol_shrink_ratio"),
            "gain_10d_pct": snap.get("gain_10d_pct"),
            "reason": strat_cls.format_reason(snap),
        })
    return out


# ---------------------------------------------------------------------------
# 后台任务
# ---------------------------------------------------------------------------
class SelectionService:
    """按 用户名 + 类型(stock/etf) 管理后台初筛任务与结果缓存。"""

    def __init__(self):
        self._status: Dict[str, Dict[str, Any]] = {}
        self._results: Dict[str, List[Dict[str, Any]]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(username: str, kind: str) -> str:
        return f"{username}|{kind}"

    def status(self, username: str, kind: str) -> Dict[str, Any]:
        with self._lock:
            return dict(self._status.get(self._key(username, kind), {"running": False}))

    def result(self, username: str, kind: str) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._results.get(self._key(username, kind), []))

    def start(
        self,
        username: str,
        kind: str,
        strategy_id: str,
        trade_date: date,
        overrides: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        try:
            get_strategy(strategy_id)
        except KeyError as e:
            return {"ok": False, "detail": str(e)}

        key = self._key(username, kind)
        with self._lock:
            if self._status.get(key, {}).get("running"):
                return {"ok": False, "detail": "已有选股任务在运行"}
            self._status[key] = {
                "running": True, "kind": kind, "strategy": strategy_id,
                "trade_date": trade_date.isoformat(), "started": time.time(),
                "elapsed": 0.0, "count": 0, "error": None,
            }
        t = threading.Thread(
            target=self._run, args=(key, kind, strategy_id, trade_date, overrides or {}),
            daemon=True,
        )
        t.start()
        return {"ok": True}

    def _run(self, key, kind, strategy_id, trade_date, overrides):
        t0 = time.time()
        try:
            strat = get_strategy(strategy_id)
            result = strat.screen(kind, trade_date, overrides)
            candidates = result.candidates
            if result.export_top_n:
                candidates = candidates[: result.export_top_n]
            enriched = enrich(kind, candidates, result.snapshots, strategy_id)
            with self._lock:
                self._results[key] = enriched
                self._status[key] = {
                    "running": False, "kind": kind, "strategy": strategy_id,
                    "trade_date": trade_date.isoformat(),
                    "elapsed": round(time.time() - t0, 1), "count": len(enriched),
                    "error": None,
                }
            if kind == "stock" and candidates:
                username = key.split("|", 1)[0]
                try:
                    from src.webui.inst_holders import get_inst_holder_fetch_service
                    get_inst_holder_fetch_service().start(username, kind, candidates)
                except Exception as e:  # noqa: BLE001
                    logger.warning("启动机构家数异步抓取失败: %s", e)
        except Exception as e:  # noqa: BLE001
            logger.exception("选股任务失败: %s", e)
            with self._lock:
                self._status[key] = {
                    "running": False, "kind": kind, "strategy": strategy_id,
                    "trade_date": trade_date.isoformat(),
                    "elapsed": round(time.time() - t0, 1), "count": 0,
                    "error": str(e),
                }
