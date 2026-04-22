"""北向/龙虎榜/机构调研/个股资金流向 — 多源落库 (Tushare 主路径 + AkShare 降级)

设计对齐 ``kline_bulk_sync`` / ``akshare_financial_sync``:
- ``TokenBucketLimiter`` 全接口限流
- 按交易日批量拉取, PostgreSQL ``INSERT ... ON CONFLICT`` 幂等

用法:
  uv run python -m src.data.alt_data_sync hsgt --start-date 20240101 --end-date 20260422
  uv run python -m src.data.alt_data_sync lhb --start-date 20240401 --end-date 20260422
  uv run python -m src.data.alt_data_sync moneyflow --start-date 20240401 --end-date 20260422
  uv run python -m src.data.alt_data_sync survey --start-date 20240101 --end-date 20260422
  uv run python -m src.data.alt_data_sync index-weight --index-code 000300.SH --end-date 20260422
  uv run python -m src.data.alt_data_sync industry-map

需要 ``TUSHARE_TOKEN``; 无 Token 时仅 ``industry_map``(AkShare) 等少数命令可用部分功能。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from src.common.config import settings
from src.common.db import get_session
from src.common.logger import get_logger
from src.data.models import (
    HsgtMarketDaily,
    IndexWeight,
    InstitutionSurvey,
    SectorStock,
    StockLhbDaily,
    StockMoneyflowDaily,
)
from src.datacollect.collectors.tushare_collector import TushareCollector
from src.datacollect.rate_limiter import TokenBucketLimiter

logger = get_logger(__name__)
_CFG = settings.datacollect


def _ts_code_to_code6(ts_code: str) -> str:
    s = (ts_code or "").strip()
    if "." in s:
        return s.split(".")[0]
    return s[:6] if s else s


def _to_date(x: Any) -> date | None:
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    if isinstance(x, date) and not isinstance(x, datetime):
        return x
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, (int,)) and 19000101 <= x <= 21001231:
        s = f"{x:08d}"
        if len(s) == 8:
            return datetime.strptime(s, "%Y%m%d").date()
    s = str(x).replace("-", "")[:8]
    if len(s) >= 8 and s.isdigit():
        return datetime.strptime(s[:8], "%Y%m%d").date()
    return None


def _float(x: Any) -> float | None:
    if x is None or (isinstance(x, (float, int)) and pd.isna(x)):
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _trade_date_range(
    start: date, end: date,
) -> list[date]:
    """优先使用库内交易日历, 否则退化为自然日(弱)."""
    with get_session() as session:
        rows = session.execute(
            text(
                "SELECT DISTINCT trade_date FROM trading_date "
                "WHERE trade_date >= :a AND trade_date <= :b ORDER BY 1"
            ),
            {"a": start, "b": end},
        ).fetchall()
    if rows:
        return [r[0] for r in rows]
    d: list[date] = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            d.append(cur)
        cur += timedelta(days=1)
    return d


class AltDataSync:
    """多源补充数据 — 与 ETF 日线同类的限流 + 重试外思想."""

    def __init__(self) -> None:
        self._tushare = TushareCollector() if _CFG.tushare_token else None
        self._ak = TokenBucketLimiter.for_domain(
            "akshare_alt", rate=_CFG.akshare_rate, burst=_CFG.akshare_burst,
        )

    @property
    def tushare_ok(self) -> bool:
        return self._tushare is not None and self._tushare.available

    def sync_hsgt_market(
        self, start: date, end: date, *, source: str = "tushare",
    ) -> int:
        """沪深港通市场级日度资金."""
        if not self.tushare_ok and source == "tushare":
            return self._sync_hsgt_akshare_fallback(start, end)

        assert self._tushare is not None
        df = self._tushare.query(
            "moneyflow_hsgt",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
        if df is None or df.empty:
            logger.warning("tushare moneyflow_hsgt 无数据, 尝试 akshare 降级")
            return self._sync_hsgt_akshare_fallback(start, end)

        n = 0
        for _, row in df.iterrows():
            td = _to_date(
                row.get("trade_date")
                or row.get("cal_date")
                or row.get("date"),
            )
            if not td:
                continue
            rec = {
                "trade_date": td,
                "hgt": _float(
                    _pick_col(row, "hgt", "gg_net", "f62", "f51")
                ),
                "sgt": _float(_pick_col(row, "sgt", "sz_net")),
                "north_net": _float(
                    _pick_col(
                        row,
                        "north_money", "n_net_amount", "net_amount",
                    )
                ),
                "raw_data": row.to_dict() if hasattr(row, "to_dict") else dict(row),
                "source": "tushare",
            }
            with get_session() as session:
                stmt = insert(HsgtMarketDaily).values(**rec)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_hsgt_date_source",
                    set_={
                        "hgt": rec["hgt"],
                        "sgt": rec["sgt"],
                        "north_net": rec["north_net"],
                        "raw_data": rec["raw_data"],
                    },
                )
                session.execute(stmt)
            n += 1
        logger.info("hsgt_market_daily 写入 %d 行 (tushare)", n)
        return n

    def _sync_hsgt_akshare_fallback(self, start: date, end: date) -> int:
        import akshare as ak

        self._ak.acquire()
        try:
            df = ak.stock_hsgt_fund_flow_summary_em()
        except Exception as e:  # noqa: BLE001
            logger.error("akshare stock_hsgt_fund_flow_summary_em 失败: %s", e)
            return 0
        if df is None or df.empty:
            return 0
        n = 0
        for _, row in df.iterrows():
            td = None
            for c in df.columns:
                cl = str(c)
                if "日期" in cl or cl.lower() in ("date", "trade_date"):
                    td = _to_date(row.get(c))
                    break
            if not td:
                try:
                    td = _to_date(row.iloc[0])
                except Exception:  # noqa: BLE001
                    td = None
            if not td or td < start or td > end:
                continue
            hgt = None
            sgt = None
            north = None
            for c in row.index:
                cs = str(c)
                v = row.get(c)
                if "沪" in cs and "股通" in cs:
                    hgt = _float(v)
                elif "深" in cs and "股通" in cs:
                    sgt = _float(v)
                elif "北向" in cs or "净流入" in cs:
                    north = _float(v)
            rec = {
                "trade_date": td,
                "hgt": hgt,
                "sgt": sgt,
                "north_net": north,
                "raw_data": row.to_dict(),
                "source": "akshare",
            }
            with get_session() as session:
                stmt = insert(HsgtMarketDaily).values(**rec)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_hsgt_date_source",
                    set_={
                        "hgt": rec["hgt"],
                        "sgt": rec["sgt"],
                        "north_net": rec["north_net"],
                        "raw_data": rec["raw_data"],
                    },
                )
                session.execute(stmt)
            n += 1
        logger.info("hsgt_market_daily 写入 %d 行 (akshare 降级)", n)
        return n

    def sync_top_list(self, d: date) -> int:
        if not self.tushare_ok:
            logger.warning("无 Tushare, 跳过 top_list")
            return 0
        df = self._tushare.query(
            "top_list",
            trade_date=d.strftime("%Y%m%d"),
        )
        if df is None or df.empty:
            return 0
        n = 0
        for _, row in df.iterrows():
            code = _code6_from_row(row)
            if not code:
                continue
            rsn = (str(row.get("reason", "") or ""))[:200]
            side = str(row.get("side", "") or row.get("side_name", "") or "")[:10]
            rec = {
                "code": code,
                "name": str(row.get("name", "") or "")[:50],
                "trade_date": d,
                "reason": rsn,
                "side": side,
                "buy": _float(row.get("buy")) or _float(row.get("buy_sm_amount")),
                "sell": _float(row.get("sell")) or _float(row.get("sell_sm_amount")),
                "net": _float(row.get("net_amount") or row.get("netbuy")),
                "amount_rate": _float(row.get("amount_rate") or row.get("reason_rate")),
                "turnover": _float(row.get("turnover") or row.get("market")),
                "float_ratio": _float(row.get("float_values") or row.get("float_ratio")),
                "raw_data": row.to_dict() if hasattr(row, "to_dict") else dict(row),
                "source": "tushare",
            }
            with get_session() as session:
                stmt = insert(StockLhbDaily).values(**rec)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_lhb_code_date_reason_side",
                    set_={
                        "buy": rec["buy"],
                        "sell": rec["sell"],
                        "net": rec["net"],
                        "raw_data": rec["raw_data"],
                    },
                )
                session.execute(stmt)
            n += 1
        return n

    def sync_moneyflow_day(self, d: date) -> int:
        if not self.tushare_ok:
            return 0
        df = self._tushare.query(
            "moneyflow",
            trade_date=d.strftime("%Y%m%d"),
        )
        if df is None or df.empty:
            return 0
        n = 0
        for _, row in df.iterrows():
            code = _code6_from_row(row)
            if not code:
                continue
            rec = {
                "code": code,
                "trade_date": d,
                "buy_sm": _float(_pick_col(row, "buy_sm_amount", "sm_b")),
                "buy_md": _float(_pick_col(row, "buy_md_amount", "md_b")),
                "buy_lg": _float(_pick_col(row, "buy_lg_amount", "lg_b")),
                "buy_elg": _float(_pick_col(row, "buy_elg_amount", "elg_b")),
                "sell_sm": _float(_pick_col(row, "sell_sm_amount", "sm_s")),
                "sell_md": _float(_pick_col(row, "sell_md_amount", "md_s")),
                "sell_lg": _float(_pick_col(row, "sell_lg_amount", "lg_s")),
                "sell_elg": _float(_pick_col(row, "sell_elg_amount", "elg_s")),
                "net_mf": _float(_pick_col(row, "net_mf_amount", "net_mf", "net_amount")),
                "net_mf_rate": _float(_pick_col(row, "net_mf_rate")),
                "raw_data": row.to_dict() if hasattr(row, "to_dict") else dict(row),
                "source": "tushare",
            }
            with get_session() as session:
                stmt = insert(StockMoneyflowDaily).values(**rec)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_smd_code_date",
                    set_={k: rec[k] for k in rec if k not in ("code", "trade_date")},
                )
                session.execute(stmt)
            n += 1
        return n

    def sync_stk_surv(self, start: date, end: date) -> int:
        if not self.tushare_ok:
            logger.warning("无 Tushare, 跳过 stk_surv")
            return 0
        df = self._tushare.query(
            "stk_surv",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
        if df is None or df.empty:
            return 0
        n = 0
        for _, row in df.iterrows():
            code = _code6_from_row(row)
            if not code:
                continue
            sd = _to_date(
                row.get("surv_date")
                or row.get("ann_date")
                or row.get("receivestartdate")
                or row.get("end_date")
            ) or _to_date(row.get("end_date"))
            if not sd:
                continue
            org = (str(row.get("org_name") or row.get("receptionist") or "") or "")[:200]
            rec = {
                "code": code,
                "name": str(row.get("name", "") or "")[:100],
                "survey_date": sd,
                "org_name": org,
                "org_type": str(row.get("org_type", "") or "")[:100],
                "content": None,
                "raw_data": row.to_dict() if hasattr(row, "to_dict") else dict(row),
                "source": "tushare",
            }
            with get_session() as session:
                stmt = insert(InstitutionSurvey).values(**rec)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_isvy_code_date_org",
                    set_={
                        "name": rec["name"],
                        "org_type": rec["org_type"],
                        "raw_data": rec["raw_data"],
                    },
                )
                session.execute(stmt)
            n += 1
        return n

    def sync_index_weight(
        self, index_code: str, end: date, *, lookback_days: int = 5,
    ) -> int:
        """拉最近 ``lookback_days`` 个交易日的指数权重."""
        if not self.tushare_ok:
            return 0
        start = end - timedelta(days=lookback_days * 2)
        df = self._tushare.query(
            "index_weight",
            index_code=index_code,
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
        if df is None or df.empty:
            return 0
        tds = pd.to_datetime(df["trade_date"], errors="coerce")
        latest = tds.max()
        if pd.isna(latest):
            return 0
        sub = df.loc[tds == latest]
        n = 0
        for _, row in sub.iterrows():
            con = str(row.get("con_code", "") or "")
            if not con:
                continue
            rec = {
                "index_code": index_code,
                "stock_code": con,
                "weight": _float(row.get("weight")),
            }
            with get_session() as session:
                stmt = insert(IndexWeight).values(**rec)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_index_weight",
                    set_={"weight": rec["weight"]},
                )
                session.execute(stmt)
            n += 1
        return n

    def sync_industry_to_sector_stock(self) -> int:
        """用 ``stock_basic`` 的 industry 填充 ``sector_stock`` (申万/证监会行业名, 以 Tushare 为准)."""
        if not self.tushare_ok:
            return self._sync_industry_ak()

        df = self._tushare.query_stock_basic(
            fields="ts_code,symbol,name,industry",
        )
        if df is None or df.empty:
            return 0
        n = 0
        for _, row in df.iterrows():
            ts = str(row.get("ts_code", "") or "")
            ind = (str(row.get("industry", "") or "").strip())[:100]
            if not ts or not ind or ind in ("0", "nan", "无"):
                continue
            with get_session() as session:
                stmt = insert(SectorStock).values(
                    sector_name=ind, stock_code=ts,
                )
                stmt = stmt.on_conflict_do_nothing(constraint="uq_sector_stock")
                session.execute(stmt)
            n += 1
        logger.info("sector_stock 写入尝试 %d 行 (tushare industry)", n)
        return n

    def _sync_industry_ak(self) -> int:
        logger.warning(
            "industry-map 需要 Tushare stock_basic.industry; 未配置 Token 时跳过",
        )
        return 0


def _code6_from_row(row: pd.Series) -> str:
    s = (
        row.get("ts_code")
        or row.get("symbol")
        or row.get("code")
        or row.get("股票代码")
    )
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return ""
    return _ts_code_to_code6(str(s))


def _pick_col(row: pd.Series, *cands: str) -> Any:
    for c in cands:
        if c in row.index and row[c] is not None and not (
            isinstance(row[c], float) and pd.isna(row[c])
        ):
            return row[c]
    for c in row.index:
        cl = c.lower()
        for cand in cands:
            if cand and cand.lower() in cl:
                return row[c]
    return None


def _parse_args():
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "action",
        choices=[
            "hsgt", "lhb", "moneyflow", "survey", "index-weight", "industry-map",
        ],
    )
    p.add_argument("--start-date", default="20240101", help="YYYYMMDD")
    p.add_argument("--end-date", default=None, help="默认今天")
    p.add_argument("--index-code", default="000300.SH", help="index_weight, 如 000300.SH")
    p.add_argument("--lookback", type=int, default=5, help="index-weight 回退天数试拉")
    return p.parse_args()


def main() -> int:
    args = _parse_args()
    end = _to_date(args.end_date) or date.today()
    start = _to_date(args.start_date) or (end - timedelta(days=30))
    if not start or not end or start > end:
        logger.error("日期非法")
        return 1
    s = AltDataSync()

    if args.action == "hsgt":
        s.sync_hsgt_market(start, end)
        return 0
    if args.action == "survey":
        n = s.sync_stk_surv(start, end)
        logger.info("institution_survey => %d", n)
        return 0
    if args.action == "industry-map":
        s.sync_industry_to_sector_stock()
        return 0
    if args.action == "index-weight":
        n = s.sync_index_weight(
            args.index_code, end, lookback_days=args.lookback,
        )
        logger.info("index_weight => %d", n)
        return 0

    dates = _trade_date_range(start, end)
    total = 0
    for d in dates:
        if args.action == "lhb":
            total += s.sync_top_list(d)
        else:
            total += s.sync_moneyflow_day(d)
    logger.info(
        "action=%s 完成, 累计写入约 %d 行 (lhb=条数, moneyflow=行数之近似)",
        args.action, total,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
