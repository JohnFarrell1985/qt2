"""采集「续传」公共逻辑 — 与 ``stock/etf`` 日 K 的 ``daily_kline_work_segments`` 同构.

- **向今** / **向史** 两段: 库内已有 ``MIN..MAX`` 时, 只拉 **(MAX, end]** 与 **[floor, MIN)**;
- **中缝** (可选): 在 ``[first, last]`` 与 XSHG 历对比, 用 ``interior_trading_gaps_ymd`` 补零散缺日;
- 日频、**全表一序列** 表(如北向、板块) 用 :func:`global_series_work_segments`
  (``sector_data`` 对东财资金快照行 ``流·%`` 不参与区段/中缝, 见 ``_GLOBAL_SERIES_ROW_FILTER_SQL``);
- 日频、**按日块** 表(龙虎榜/资金流) 用 :func:`missing_trading_session_dates`.

K 线类仍由 ``kline_bulk_sync`` / ``akshare_financial_sync``(ETF) 维护; 本模块供另类/板块等复用.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any

from sqlalchemy import text

from src.common.config import settings
from src.common.db import get_session
from src.data.kline_bulk_sync import (
    daily_kline_work_segments,
    interior_trading_gaps_ymd,
    _xshg_trading_session_dates,
)

ALLOWED_GLOBAL_SERIES: dict[str, str] = {
    "hsgt_market_daily": "trade_date",
    "institution_survey": "survey_date",
    "sector_data": "trade_date",
}

# 全表续传/中缝: 对 ``sector_data`` 排除东财资金快照行(``sector_name`` 以 ``流·`` 开头),
# 仅按 K 线/指数线行计算 MIN/MAX 与已覆盖交易日, 避免资金快照把 MAX 顶到今致向今区段误缩
# 及中缝把「有快照无 K」误判为可大量补缺。
_GLOBAL_SERIES_ROW_FILTER_SQL: dict[str, str] = {
    # LIKE 中 ``%%`` 传入驱动后为字面值 ``%``
    "sector_data": "(COALESCE(sector_name, '') NOT LIKE '流·%%')",
}

ALLOWED_PER_DAY: dict[str, str] = {
    "stock_lhb_daily": "trade_date",
    "stock_moneyflow_daily": "trade_date",
}


def fill_interior_gaps_enabled() -> bool:
    return bool(
        getattr(settings.datacollect, "kline_fill_interior_gaps", True),
    )


def ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def parse_ymd(s: str) -> date:
    s = (s or "").replace("-", "")[:8]
    return datetime.strptime(s, "%Y%m%d").date()


def _cell_to_date(v: Any) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    raise TypeError(f"expected date, got {type(v)}")


def global_series_work_segments(
    table: str,
    date_col: str,
    floor_ymd: str,
    end_ymd: str,
    *,
    resume: bool = True,
    fill_interior: bool | None = None,
) -> list[tuple[str, str]]:
    """全表单日期维度的缺段: ``daily_kline_work_segments`` + 可选中缝(相对 XSHG)."""
    if ALLOWED_GLOBAL_SERIES.get(table) != date_col:
        raise ValueError(f"未白名单: {table}.{date_col}")

    f_s = (floor_ymd[:8]).ljust(8, "0")
    e_s = (end_ymd[:8]).ljust(8, "0")
    if not resume:
        return [(f_s, e_s)]

    extra_where = _GLOBAL_SERIES_ROW_FILTER_SQL.get(table, "")
    wprefix = f" WHERE {extra_where} " if extra_where else " "
    q = text(
        f"SELECT MIN({date_col})::date, MAX({date_col})::date FROM {table} {wprefix} ",  # noqa: S608
    )
    with get_session(readonly=True) as session:
        row = session.execute(q).fetchone()
    if not row or row[0] is None or row[1] is None:
        return [(f_s, e_s)]

    first_d: date = _cell_to_date(row[0])
    last_d: date = _cell_to_date(row[1])
    last_ymd = ymd(last_d)
    first_ymd = ymd(first_d)
    base = daily_kline_work_segments(
        f_s, e_s, last_ymd, first_ymd, True,
    )
    if fill_interior is None:
        fill_interior = fill_interior_gaps_enabled()
    if not fill_interior or not resume:
        return base

    q2 = text(
        f"SELECT DISTINCT {date_col}::date AS td FROM {table} "  # noqa: S608
        f"WHERE {date_col} IS NOT NULL AND {date_col} >= :a AND {date_col} <= :b"
        + (f" AND {extra_where}" if extra_where else ""),
    )
    have: set[date] = set()
    with get_session(readonly=True) as session:
        for (td,) in session.execute(q2, {"a": first_d, "b": last_d}):
            if td is not None:
                have.add(_cell_to_date(td))
    if not have:
        return base
    lo = max(first_d, min(have))
    hi = min(last_d, max(have))
    if lo > hi:
        return base
    all_sess = _xshg_trading_session_dates(lo, hi)
    extra = interior_trading_gaps_ymd(ymd(lo), ymd(hi), have, all_sess)
    return list(base) + extra


def missing_trading_session_dates(
    table: str,
    date_col: str,
    floor: date,
    end: date,
    *,
    resume: bool = True,
) -> list[date]:
    """`[floor,end]` 内 XSHG 交易日中, 该表尚无任何行的日期(用于龙虎榜/资金流按日补全)."""
    if ALLOWED_PER_DAY.get(table) != date_col:
        raise ValueError(f"未白名单: {table}.{date_col}")
    sess = _xshg_trading_session_dates(floor, end)
    if not sess:
        return []
    if not resume:
        return sess
    # date_col 已白名单
    q = text(
        f"SELECT DISTINCT {date_col}::date AS td FROM {table} "  # noqa: S608
        f"WHERE {date_col} >= :a AND {date_col} <= :b",
    )
    have: set[date] = set()
    with get_session(readonly=True) as session:
        for (td,) in session.execute(q, {"a": floor, "b": end}):
            if td is not None:
                have.add(_cell_to_date(td))
    return [d for d in sess if d not in have]


def _quarter_periods_ymd(y0: int, y1: int) -> list[str]:
    out: list[str] = []
    for y in range(y0, y1 + 1):
        for p in (f"{y}0331", f"{y}0630", f"{y}0930", f"{y}1231"):
            out.append(p)
    return out


def missing_financial_report_periods(floor_ymd: str, end_ymd: str) -> list[str]:
    """候选财报季 vs 库中已有 ``report_period``(任一行即视为已拉过该期) — 供 akshare 批量增量."""
    f = (floor_ymd[:8]).ljust(8, "0")
    e = (end_ymd[:8]).ljust(8, "0")
    y0, y1 = int(f[:4]), int(e[:4])
    candidates = [p for p in _quarter_periods_ymd(y0, y1) if f <= p <= e]
    if not candidates:
        return []
    with get_session(readonly=True) as session:
        rows = session.execute(
            text("SELECT DISTINCT report_period::text FROM stock_financial_report WHERE report_period IS NOT NULL"),
        ).fetchall()
    have: set[str] = set()
    for (rp,) in rows:
        if rp is None:
            continue
        s = str(rp).replace("-", "").replace("/", "")[:8]
        if len(s) >= 8 and s.isdigit():
            have.add(s[:8])
    return [p for p in candidates if p not in have]


def missing_financial_indicator_periods(floor_ymd: str, end_ymd: str) -> list[str]:
    """以 ``stock_financial_indicator`` 中已出现过的 `report_date`(YYYYMMDD) 与候选季对比."""
    f = (floor_ymd[:8]).ljust(8, "0")
    e = (end_ymd[:8]).ljust(8, "0")
    y0, y1 = int(f[:4]), int(e[:4])
    candidates = [p for p in _quarter_periods_ymd(y0, y1) if f <= p <= e]
    if not candidates:
        return []
    with get_session(readonly=True) as session:
        rows = session.execute(
            text(
                "SELECT DISTINCT to_char(report_date, 'YYYYMMDD') AS r FROM stock_financial_indicator "
                "WHERE report_date IS NOT NULL",
            ),
        ).fetchall()
    have = {str(r[0]) for r in rows if r[0] and str(r[0]).isdigit() and len(str(r[0])) >= 8}
    return [p for p in candidates if p not in have]
