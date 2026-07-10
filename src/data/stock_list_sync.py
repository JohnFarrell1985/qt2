"""股票代码-名称列表同步 — 走 datacollect 多源降级 (不依赖 QMT)."""

from __future__ import annotations

from typing import Any

import pandas as pd
from sqlalchemy.dialects.postgresql import insert

from src.common.db import get_session
from src.common.db_batch import DEFAULT_TABLE_UPSERT_FLUSH, log_upsert_commit
from src.common.logger import get_logger
from src.data.akshare_sync import _exchange_from_code
from src.data.models import Stock

logger = get_logger(__name__)


def normalize_stock_code(raw: Any) -> str | None:
    """统一为 6 位数字代码 (与 stock_daily.code 一致)."""
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s.startswith(("sh.", "sz.", "bj.")):
        s = s.split(".", 1)[1]
    if "." in s:
        s = s.split(".", 1)[0]
    if len(s) == 6 and s.isdigit():
        return s
    return None


def _cell_str(row: pd.Series, *keys: str) -> str:
    for key in keys:
        if key not in row.index:
            continue
        val = row.get(key)
        if val is None or (isinstance(val, float) and pd.isna(val)):
            continue
        text = str(val).strip()
        if text:
            return text
    return ""


def records_from_dataframe(df: pd.DataFrame | None, source: str) -> list[dict]:
    """将各数据源股票列表 DataFrame 转为 stocks 表 upsert 记录."""
    if df is None or df.empty:
        return []

    out: list[dict] = []
    seen: set[str] = set()

    for _, row in df.iterrows():
        if source == "baostock":
            typ = _cell_str(row, "type")
            status = _cell_str(row, "status")
            if typ and typ != "1":
                continue
            if status and status != "1":
                continue
            code = normalize_stock_code(_cell_str(row, "code"))
            name = _cell_str(row, "code_name", "name")
        elif source == "tushare":
            code = normalize_stock_code(_cell_str(row, "symbol", "ts_code", "code"))
            name = _cell_str(row, "name")
        else:
            code = normalize_stock_code(
                _cell_str(row, "code", "代码", "A股代码", "证券代码", "symbol", "ts_code"),
            )
            name = _cell_str(row, "name", "名称", "A股简称", "证券简称", "code_name")

        if not code or code in seen:
            continue
        if not name:
            name = code
        seen.add(code)
        out.append({
            "code": code,
            "name": name,
            "exchange": _exchange_from_code(code),
        })

    return out


def upsert_stock_records(records: list[dict]) -> int:
    if not records:
        return 0
    count = 0
    for i in range(0, len(records), DEFAULT_TABLE_UPSERT_FLUSH):
        batch = records[i: i + DEFAULT_TABLE_UPSERT_FLUSH]
        with get_session() as session:
            stmt = insert(Stock).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=["code"],
                set_={
                    "name": stmt.excluded.name,
                    "exchange": stmt.excluded.exchange,
                },
            )
            session.execute(stmt)
        count += len(batch)
        log_upsert_commit("stock_list_sync", len(batch))
    return count


def fetch_stock_list_via_fallback() -> tuple[pd.DataFrame, str]:
    """按 data_sources.json 降级链拉取股票列表 (跳过 QMT)."""
    from src.datacollect.dispatcher import FallbackDispatcher

    dispatcher = FallbackDispatcher()
    chain = dispatcher.registry.get_fallback_chain("stock_list")
    chain = [s for s in chain if s != "xtquant"]
    if not chain:
        raise RuntimeError("stock_list 降级链为空")

    errors: list[tuple[str, str]] = []
    for source_name in chain:
        collector = dispatcher._get_collector(source_name)
        if collector is None:
            continue
        func_name = dispatcher._resolve_func_name("stock_list", source_name)
        if not func_name:
            continue
        from src.datacollect.base import CollectTask

        task = CollectTask(source=source_name, params={"func_name": func_name})
        try:
            result = collector.collect(task)
            df = result.data
            if df is not None and hasattr(df, "empty") and not df.empty:
                if source_name == "akshare" and "代码" in df.columns and "code" not in df.columns:
                    df = df.rename(columns={"代码": "code", "名称": "name"})
                logger.info("stock_list 降级成功: source=%s rows=%d", source_name, len(df))
                return df, source_name
        except Exception as e:
            logger.warning("stock_list 源 %s 失败: %s", source_name, e)
            errors.append((source_name, str(e)))

    detail = ", ".join(f"{n}: {e}" for n, e in errors) or "无可用采集器"
    raise RuntimeError(f"stock_list 所有非 QMT 数据源均失败: {detail}")


def sync_stock_list_via_fallback() -> int:
    """多源降级同步 stocks 代码+名称."""
    df, source = fetch_stock_list_via_fallback()
    records = records_from_dataframe(df, source)
    if not records:
        logger.warning("stock_list 降级链返回数据但无法解析 code/name (source=%s)", source)
        return 0
    count = upsert_stock_records(records)
    logger.info("stock_list 降级同步完成: source=%s, %d 只", source, count)
    return count
