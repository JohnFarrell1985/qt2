"""北向/龙虎榜/机构调研/个股资金流向 — 多源级联落库 (``run_source_stack``: 每源单段约 120s 墙钟、同源异常可重试, 0 行则换源; 全源失败则 ERROR 并结束该段级联).

- ``TokenBucketLimiter`` 全接口限流
- 按交易日/区间拉取, PostgreSQL ``INSERT ... ON CONFLICT`` 幂等
- **龙虎榜 (≥5 路)**: tushare top_list → 东财 ``stock_lhb_detail_em`` → 东财机构买卖每日 ``stock_lhb_jgmmtj_em`` → 新浪 ``stock_lhb_detail_daily_sina`` (每源+日 YYYYMMDD 去重)
- **资金 (≥5 路, 近端日)**: tushare moneyflow; 在 ``DATACOLLECT_MF_SNAPSHOT_FALLBACK_DAYS`` 内再叠东财 ``stock_individual_fund_flow_rank``(今/3/5/10 日) 与同花顺 ``stock_fund_flow_individual``(即时/3/5/10/20 日排行). **远历史**仅有 Tushare 等有**按日全市场**分级口径(东财/同花顺排名多为**当前页快照**). 每源+日 去重.
- **北向 hsgt (≥5 路)**: tushare ``moneyflow_hsgt`` → 东财 ``stock_hsgt_fund_flow_summary_em`` → ``stock_hsgt_hist_em``(北向资金/沪股通/深股通); 每源/日 ``alt_datacollect_progress`` 去重
- **调研 (≥5 路)**: tushare stk_surv → 东财 ``stock_jgdy_tj_em`` 在区间内 **多锚点日** (见 ``DATACOLLECT_SURVEY_TJ_ANCHORS``) 各拉一次再合并筛区间; 区间+源键同上进度表
- **指数权重 (≥7 路)**: **QMT** ``get_index_weight``(本机 MiniQMT, **优先**) → tushare ``index_weight``(可选, 无 Token 则跳过) → 中证 → 新浪 → 申万 ``index_component_sw``(``80xxxx``)
- **行业/概念→股票 (≥5 路)**: tushare ``stock_basic`` → 东财行业/概念成份 → 同花顺行业/概念名 + 东财 cons; 日键 ``ind_map_YYYYMMDD``
- 落盘: 本模块内诸表每 ``DEFAULT_TABLE_UPSERT_FLUSH``(200) 行一批 ``INSERT..ON CONFLICT`` 后 ``commit`` 一次; 全库另类+板块日频种类见 ``alt_datacollect_progress.ALT_DATACOLLECT_CATEGORY_COUNT``(7) (含 ``sector_data`` 进度在 ``sector_market_data`` 写入).

用法:
  uv run python -m src.data.alt_data_sync hsgt --start-date 20240101 --end-date 20260422
  uv run python -m src.data.alt_data_sync lhb --start-date 20240401 --end-date 20260422
  uv run python -m src.data.alt_data_sync moneyflow --start-date 20240401 --end-date 20260422
  uv run python -m src.data.alt_data_sync survey --start-date 20240101 --end-date 20260422
  uv run python -m src.data.alt_data_sync index-weight --index-code 000300.SH --end-date 20260422
  uv run python -m src.data.alt_data_sync industry-map

``TUSHARE_ENABLED``(默认 false) + ``TUSHARE_TOKEN`` 同时满足才走 Tushare; 关闭时北向/龙虎/资金/调研等仅级联至东财/新浪等同档. 指数权重以 QMT 优先.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date, datetime, timedelta
from functools import partial
from typing import Any

import pandas as pd
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from src.common.config import settings
from src.common.db import get_session
from src.common.db_batch import buffer_push_flush, log_upsert_commit
from src.common.logger import get_logger
from src.data.models import (
    HsgtMarketDaily,
    IndexWeight,
    InstitutionSurvey,
    SectorStock,
    StockLhbDaily,
    StockMoneyflowDaily,
)
from src.data.alt_datacollect_progress import (
    AltDatacollectProgressDAO as AltD,
    CAT_HSGT,
    CAT_INDEX_WEIGHT,
    CAT_LHB,
    CAT_MF,
    CAT_SECTOR_STOCK,
    CAT_SURVEY,
)
from src.data.alt_source_cascade import CascadeStrikeState, run_source_stack
from src.datacollect.collectors.tushare_collector import TushareCollector
from src.datacollect.rate_limiter import TokenBucketLimiter

logger = get_logger(__name__)
_CFG = settings.datacollect


def _cascade_strike_state() -> CascadeStrikeState:
    t = int(getattr(_CFG, "cascade_strike_disable_after", 5) or 5)
    return CascadeStrikeState(threshold=max(0, t))


def _filter_cascade_layers(
    layers: list[tuple[str, Callable[[], int]]],
    strike: CascadeStrikeState | None,
) -> list[tuple[str, Callable[[], int]]]:
    if not strike or not strike.disabled:
        return list(layers)
    return [x for x in layers if x[0] not in strike.disabled]


def _ts_code_to_code6(ts_code: str) -> str:
    s = (ts_code or "").strip()
    if "." in s:
        return s.split(".")[0]
    return s[:6] if s else s


def _index_ak_symbol(index_code: str) -> str:
    return (index_code or "").split(".")[0].strip().zfill(6)[:6]


def _index_sw_6digit(index_code: str) -> str | None:
    """申万指数代码 ``801xxx`` (如 ``801300.SI`` / ``801300``) → 用于 ``ak.index_component_sw``."""
    s = (index_code or "").split(".")[0].strip()
    if re.fullmatch(r"80\d{4}", s):
        return s
    return None


def _code6_to_ts_a(code: str) -> str:
    """A 股 6 位代码 -> ``600519.SH`` 形式 (东财/新浪 代码列)."""
    s = (code or "").strip().zfill(6)[:6]
    if len(s) != 6 or not s.isdigit():
        return ""
    if s[0] in "59" or s[0] == "6" or s.startswith("688") or s.startswith("689"):
        return f"{s}.SH"
    if s[0] in "0123":
        return f"{s}.SZ"
    if s[0] in "48" or s[:2] in ("43", "83", "87", "88", "82"):
        return f"{s}.BJ"
    return f"{s}.SH"


def _em_or_sina_code_to_ts(row: pd.Series) -> str:
    """东财 cons 行 ``代码`` / 新浪 ``code`` / ``symbol`` -> 带交易所后缀."""
    for k in ("代码", "code", "symbol", "con_code"):
        if k not in row.index:
            continue
        v = row.get(k)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        s = str(v).strip()
        if "." in s and len(s) > 8:
            return s
        if k == "symbol" and s.startswith(("sh", "sz", "bj")):
            body = s[2:8] if len(s) >= 8 else s[2:]
            return _code6_to_ts_a(body)
        return _code6_to_ts_a(s[:6])
    return ""


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


def _mf_snapshot_eligible(d: date) -> bool:
    """东财/同花顺全市场资金排名为**快照**, 仅适用于距今日 ``DATACOLLECT_MF_SNAPSHOT_FALLBACK_DAYS`` 内的 trade_date 近似。"""
    days = int(getattr(_CFG, "mf_snapshot_fallback_days", 30) or 30)
    return (date.today() - d).days <= max(1, days)


def _survey_tj_anchor_dates(start: date, end: date) -> list[date]:
    """区间内均匀取若干锚点, 每锚点调 ``stock_jgdy_tj_em`` 作独立级联源."""
    nmax = int(getattr(_CFG, "survey_tj_anchors", 5) or 5)
    nmax = max(1, min(nmax, 12))
    if end < start:
        return []
    span = (end - start).days
    if span == 0:
        return [start]
    k = min(nmax, span + 1)
    out: list[date] = []
    seen: set[date] = set()
    for i in range(k):
        off = int(round(i * span / max(k - 1, 1)))
        d0 = start + timedelta(days=off)
        if d0 < start:
            d0 = start
        if d0 > end:
            d0 = end
        if d0 not in seen:
            seen.add(d0)
            out.append(d0)
    return out


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


def _flush_hsgt_market(buf: list[dict]) -> None:
    if not buf:
        return
    with get_session() as session:
        stmt = insert(HsgtMarketDaily).values(buf)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_hsgt_date_source",
            set_={
                "hgt": stmt.excluded.hgt,
                "sgt": stmt.excluded.sgt,
                "north_net": stmt.excluded.north_net,
                "raw_data": stmt.excluded.raw_data,
            },
        )
        session.execute(stmt)
    log_upsert_commit("alt.hsgt_market", len(buf))


def _flush_stock_lhb(buf: list[dict]) -> None:
    if not buf:
        return
    with get_session() as session:
        stmt = insert(StockLhbDaily).values(buf)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_lhb_code_date_reason_side",
            set_={
                "name": stmt.excluded.name,
                "buy": stmt.excluded.buy,
                "sell": stmt.excluded.sell,
                "net": stmt.excluded.net,
                "amount_rate": stmt.excluded.amount_rate,
                "turnover": stmt.excluded.turnover,
                "float_ratio": stmt.excluded.float_ratio,
                "raw_data": stmt.excluded.raw_data,
            },
        )
        session.execute(stmt)
    log_upsert_commit("alt.stock_lhb", len(buf))


def _flush_stock_mf(buf: list[dict]) -> None:
    if not buf:
        return
    with get_session() as session:
        stmt = insert(StockMoneyflowDaily).values(buf)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_smd_code_date",
            set_={
                "buy_sm": stmt.excluded.buy_sm,
                "buy_md": stmt.excluded.buy_md,
                "buy_lg": stmt.excluded.buy_lg,
                "buy_elg": stmt.excluded.buy_elg,
                "sell_sm": stmt.excluded.sell_sm,
                "sell_md": stmt.excluded.sell_md,
                "sell_lg": stmt.excluded.sell_lg,
                "sell_elg": stmt.excluded.sell_elg,
                "net_mf": stmt.excluded.net_mf,
                "net_mf_rate": stmt.excluded.net_mf_rate,
                "raw_data": stmt.excluded.raw_data,
                "source": stmt.excluded.source,
            },
        )
        session.execute(stmt)
    log_upsert_commit("alt.stock_moneyflow", len(buf))


def _flush_institution_survey(buf: list[dict]) -> None:
    if not buf:
        return
    with get_session() as session:
        stmt = insert(InstitutionSurvey).values(buf)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_isvy_code_date_org",
            set_={
                "name": stmt.excluded.name,
                "org_type": stmt.excluded.org_type,
                "raw_data": stmt.excluded.raw_data,
            },
        )
        session.execute(stmt)
    log_upsert_commit("alt.institution_survey", len(buf))


def _flush_index_weight(buf: list[dict]) -> None:
    if not buf:
        return
    with get_session() as session:
        stmt = insert(IndexWeight).values(buf)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_index_weight",
            set_={"weight": stmt.excluded.weight},
        )
        session.execute(stmt)
    log_upsert_commit("alt.index_weight", len(buf))


def _flush_sector_stock(buf: list[dict]) -> None:
    if not buf:
        return
    with get_session() as session:
        stmt = insert(SectorStock).values(buf)
        stmt = stmt.on_conflict_do_nothing(constraint="uq_sector_stock")
        session.execute(stmt)
    log_upsert_commit("alt.sector_stock", len(buf))


class AltDataSync:
    """多源补充数据 — 与 ETF 日线同类的限流 + 重试外思想."""

    def __init__(self) -> None:
        self._tushare = (
            TushareCollector()
            if _CFG.tushare_enabled and _CFG.tushare_token
            else None
        )
        self._ak = TokenBucketLimiter.for_domain(
            "akshare_alt", rate=_CFG.akshare_rate, burst=_CFG.akshare_burst,
        )
        self._hsgt_em_summary_df: pd.DataFrame | None = None
        self._hsgt_hist_cache: dict[str, pd.DataFrame] = {}

    @property
    def tushare_ok(self) -> bool:
        return self._tushare is not None and self._tushare.available

    def _hsgt_reset_caches(self) -> None:
        self._hsgt_em_summary_df = None
        self._hsgt_hist_cache = {}

    def _hsgt_ensure_em_summary(self) -> pd.DataFrame | None:
        if self._hsgt_em_summary_df is not None:
            return self._hsgt_em_summary_df
        import akshare as ak

        self._ak.acquire()
        try:
            self._hsgt_em_summary_df = ak.stock_hsgt_fund_flow_summary_em()
        except Exception as e:  # noqa: BLE001
            logger.error("em stock_hsgt_fund_flow_summary_em 失败: %s", e)
            return None
        return self._hsgt_em_summary_df

    def _hsgt_ensure_hist(self, em_symbol: str) -> pd.DataFrame | None:
        if em_symbol in self._hsgt_hist_cache:
            return self._hsgt_hist_cache[em_symbol]
        import akshare as ak

        self._ak.acquire()
        try:
            df = ak.stock_hsgt_hist_em(symbol=em_symbol)
        except Exception as e:  # noqa: BLE001
            logger.warning("em stock_hsgt_hist_em(%r): %s", em_symbol, e)
            return None
        if df is None or df.empty:
            self._hsgt_hist_cache[em_symbol] = pd.DataFrame()
        else:
            self._hsgt_hist_cache[em_symbol] = df
        return self._hsgt_hist_cache[em_symbol]

    def _hsgt_layer_tushare_day(self, d: date) -> int:
        if not self.tushare_ok or self._tushare is None:
            return 0
        sk = d.strftime("%Y%m%d")
        df = self._tushare.query("moneyflow_hsgt", start_date=sk, end_date=sk)
        if df is None or df.empty:
            return 0
        n = 0
        buf: list[dict] = []
        for _, row in df.iterrows():
            td = _to_date(
                row.get("trade_date")
                or row.get("cal_date")
                or row.get("date"),
            )
            if td != d:
                continue
            rec = {
                "trade_date": td,
                "hgt": _float(_pick_col(row, "hgt", "gg_net", "f62", "f51")),
                "sgt": _float(_pick_col(row, "sgt", "sz_net")),
                "north_net": _float(
                    _pick_col(
                        row,
                        "north_money", "n_net_amount", "net_amount",
                    ),
                ),
                "raw_data": row.to_dict() if hasattr(row, "to_dict") else dict(row),
                "source": "tushare",
            }
            n += 1
            buffer_push_flush(buf, rec, _flush_hsgt_market)
        if buf:
            _flush_hsgt_market(buf)
        if n > 0:
            AltD.mark_ok(CAT_HSGT, sk, "tushare_hsgt", n)
        return n

    def _hsgt_layer_em_summary_day(self, d: date) -> int:
        """东财 RPT_MUTUAL_QUOTA: 同交易日多行(沪/深股通+北向), 合并为一条市场级记录."""
        sk = d.strftime("%Y%m%d")
        df = self._hsgt_ensure_em_summary()
        if df is None or df.empty:
            return 0
        tcol = pd.to_datetime(df["交易日"], errors="coerce").dt.date
        sub = df[tcol == d]
        if sub is None or sub.empty:
            return 0
        hgt: float | None = None
        sgt: float | None = None
        for _, row in sub.iterrows():
            ban = str(row.get("板块", "") or "")
            dire = str(row.get("资金方向", "") or "")
            j = _float(row.get("成交净买额"))
            if "沪股通" in ban and "北向" in dire:
                hgt = j
            if "深股通" in ban and "北向" in dire:
                sgt = j
        if hgt is None and sgt is None:
            return 0
        north = (hgt or 0) + (sgt or 0)
        rec = {
            "trade_date": d,
            "hgt": hgt,
            "sgt": sgt,
            "north_net": north,
            "raw_data": sub.to_dict(orient="records"),
            "source": "em_hsgt_summary",
        }
        _flush_hsgt_market([rec])
        AltD.mark_ok(CAT_HSGT, sk, "em_hsgt_summary", 1)
        return 1

    def _hsgt_layer_em_hist_day(self, d: date, em_symbol: str, source_id: str) -> int:
        """东财 RPT_MUTUAL_DEAL_HISTORY, symbol 为 北向资金/沪股通/深股通 — 与 ``source_id`` 一致落库 source."""
        sk = d.strftime("%Y%m%d")
        df = self._hsgt_ensure_hist(em_symbol)
        if df is None or df.empty:
            return 0
        dcol = pd.to_datetime(df["日期"], errors="coerce").dt.date
        sub = df[dcol == d]
        if sub is None or sub.empty:
            return 0
        row = sub.iloc[0]
        j = _float(row.get("当日成交净买额"))
        hgt: float | None = None
        sgt: float | None = None
        north: float | None = None
        if source_id == "em_hist_north":
            north = j
        elif source_id == "em_hist_hgt":
            hgt = j
        elif source_id == "em_hist_sgt":
            sgt = j
        else:
            north = j
        rec = {
            "trade_date": d,
            "hgt": hgt,
            "sgt": sgt,
            "north_net": north,
            "raw_data": row.to_dict() if hasattr(row, "to_dict") else dict(row),
            "source": source_id,
        }
        _flush_hsgt_market([rec])
        AltD.mark_ok(CAT_HSGT, sk, source_id, 1)
        return 1

    def sync_hsgt_market(
        self,
        start: date,
        end: date,
        *,
        strike_state: CascadeStrikeState | None = None,
        stall_check: Callable[[], bool] | None = None,
    ) -> int:
        """沪深港通市场级日度资金 — 多源级联 (≥5 路) + 每源/日 ``AltD`` 去重."""
        self._hsgt_reset_caches()
        days = _trade_date_range(start, end)
        if not days:
            return 0
        ntot = 0
        h_hist = [
            ("北向资金", "em_hist_north"),
            ("沪股通", "em_hist_hgt"),
            ("深股通", "em_hist_sgt"),
        ]
        for d in days:
            if stall_check and stall_check():
                logger.warning("hsgt: 本类滞停(编排器约 120s 无本类落盘), 在 %s 前结束", d)
                break
            sk = d.strftime("%Y%m%d")
            built: list[tuple[str, Callable[[], int]]] = []
            if self.tushare_ok and not AltD.is_ok(CAT_HSGT, sk, "tushare_hsgt"):
                built.append((
                    "tushare_hsgt", partial(self._hsgt_layer_tushare_day, d),
                ))
            if not AltD.is_ok(CAT_HSGT, sk, "em_hsgt_summary"):
                built.append((
                    "em_hsgt_summary", partial(self._hsgt_layer_em_summary_day, d),
                ))
            for em_sym, lid in h_hist:
                if not AltD.is_ok(CAT_HSGT, sk, lid):
                    built.append((
                        lid, partial(
                            self._hsgt_layer_em_hist_day, d, em_sym, lid,
                        ),
                    ))
            layers = _filter_cascade_layers(built, strike_state)
            if not layers:
                if built and strike_state is not None:
                    if not strike_state.warned_all_disabled_logged:
                        logger.error(
                            "hsgt %s: 级联源均已停用或本日无可用源, 跳过",
                            d,
                        )
                        strike_state.warned_all_disabled_logged = True
                    strike_state.request_stop = True
                # 全部 is_ok 时 built 可为空, 不触发 strike
                continue
            _src, n, att = run_source_stack(
                f"hsgt {d:%Y-%m-%d}", layers, retries=5,
            )
            ntot += n
            if strike_state is not None:
                strike_state.record_attempts(att)
            if stall_check and stall_check():
                logger.warning("hsgt: 本类滞停, 在 %s 后结束 (不再处理后续日)", d)
                break
        logger.info("hsgt_market_daily 级联(按日) 累计回写约 %d 行 (区段 %s~%s)", ntot, start, end)
        return ntot

    def sync_top_list(
        self,
        d: date,
        *,
        strike_state: CascadeStrikeState | None = None,
        stall_check: Callable[[], bool] | None = None,
    ) -> int:
        if stall_check and stall_check():
            return 0
        sk = d.strftime("%Y%m%d")
        built: list[tuple[str, Callable[[], int]]] = []
        if self.tushare_ok and not AltD.is_ok(CAT_LHB, sk, "tushare_top_list"):
            built.append(("tushare_top_list", lambda: self._sync_top_list_tushare(d)))
        if not AltD.is_ok(CAT_LHB, sk, "eastmoney_lhb"):
            built.append(("eastmoney_lhb", lambda: self._sync_top_list_em(d)))
        if not AltD.is_ok(CAT_LHB, sk, "eastmoney_jgmmtj"):
            built.append(("eastmoney_jgmmtj", lambda: self._sync_top_list_jgmmtj(d)))
        if not AltD.is_ok(CAT_LHB, sk, "sina_lhb"):
            built.append(("sina_lhb", lambda: self._sync_top_list_sina(d)))
        layers = _filter_cascade_layers(built, strike_state)
        if not layers:
            if built and strike_state is not None:
                if not strike_state.warned_all_disabled_logged:
                    logger.error("lhb %s: 级联源已全部被连续失败停用, 本日跳过", d)
                    strike_state.warned_all_disabled_logged = True
                strike_state.request_stop = True
            return 0
        _src, n, att = run_source_stack(f"lhb {d:%Y-%m-%d}", layers, retries=5)
        if strike_state is not None:
            strike_state.record_attempts(att)
        if stall_check and stall_check():
            logger.warning("lhb: 本类滞停, 在 %s 后不再继续 (若仍有后续日由上层断)", d)
        return n

    def _sync_top_list_tushare(self, d: date) -> int:
        sk = d.strftime("%Y%m%d")
        if not self.tushare_ok or self._tushare is None:
            return 0
        df = self._tushare.query("top_list", trade_date=sk)
        if df is None or df.empty:
            return 0
        n = 0
        buf: list[dict] = []
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
            n += 1
            buffer_push_flush(buf, rec, _flush_stock_lhb)
        if buf:
            _flush_stock_lhb(buf)
        if n > 0:
            AltD.mark_ok(CAT_LHB, sk, "tushare_top_list", n)
        return n

    def _sync_top_list_em(self, d: date) -> int:
        sk = d.strftime("%Y%m%d")
        import akshare as ak

        self._ak.acquire()
        try:
            ds = d.strftime("%Y%m%d")
            df = ak.stock_lhb_detail_em(start_date=ds, end_date=ds)
        except Exception:  # noqa: BLE001
            raise
        if df is None or df.empty:
            return 0
        n = 0
        buf: list[dict] = []
        for _, row in df.iterrows():
            code = _ts_code_to_code6(str(row.get("代码", "") or ""))
            if not code:
                continue
            tlist = _to_date(row.get("上榜日")) or d
            if tlist != d:
                continue
            rdp = str(row.get("解读", "") or "")
            rup = str(row.get("上榜原因", "") or "")
            rsn = f"{rdp}|{rup}"[:200]
            b_in = _float(row.get("龙虎榜买入额"))
            b_out = _float(row.get("龙虎榜卖出额"))
            j = _float(row.get("龙虎榜净买额"))
            rec = {
                "code": code,
                "name": str(row.get("名称", "") or "")[:50],
                "trade_date": d,
                "reason": rsn,
                "side": "",
                "buy": b_in / 10000.0 if b_in is not None else None,
                "sell": b_out / 10000.0 if b_out is not None else None,
                "net": j / 10000.0 if j is not None else None,
                "amount_rate": _float(row.get("净买额占总成交比")),
                "turnover": _float(row.get("市场总成交额")),
                "float_ratio": _float(row.get("换手率")),
                "raw_data": row.to_dict() if hasattr(row, "to_dict") else dict(row),
                "source": "eastmoney",
            }
            n += 1
            buffer_push_flush(buf, rec, _flush_stock_lhb)
        if buf:
            _flush_stock_lhb(buf)
        if n > 0:
            AltD.mark_ok(CAT_LHB, sk, "eastmoney_lhb", n)
        return n

    def _sync_top_list_sina(self, d: date) -> int:
        sk = d.strftime("%Y%m%d")
        import akshare as ak

        self._ak.acquire()
        try:
            df = ak.stock_lhb_detail_daily_sina(date=d.strftime("%Y%m%d"))
        except Exception:  # noqa: BLE001
            raise
        if df is None or df.empty:
            return 0
        n = 0
        buf: list[dict] = []
        for _, row in df.iterrows():
            code = _ts_code_to_code6(str(row.get("股票代码", "") or ""))
            if not code:
                continue
            ind = str(row.get("指标", "") or "")
            rec = {
                "code": code,
                "name": str(row.get("股票名称", "") or "")[:50],
                "trade_date": d,
                "reason": ind[:200],
                "side": "",
                "buy": None,
                "sell": None,
                "net": None,
                "amount_rate": _float(row.get("对应值")),
                "turnover": _float(row.get("成交额")),
                "float_ratio": None,
                "raw_data": row.to_dict() if hasattr(row, "to_dict") else dict(row),
                "source": "sina",
            }
            n += 1
            buffer_push_flush(buf, rec, _flush_stock_lhb)
        if buf:
            _flush_stock_lhb(buf)
        if n > 0:
            AltD.mark_ok(CAT_LHB, sk, "sina_lhb", n)
        return n

    def _sync_top_list_jgmmtj(self, d: date) -> int:
        """东财-数据中心-龙虎榜-机构买卖每日统计(与 ``stock_lhb_detail_em`` 列口径同系, 作独立源)."""
        sk = d.strftime("%Y%m%d")
        import akshare as ak

        self._ak.acquire()
        try:
            ds = d.strftime("%Y%m%d")
            df = ak.stock_lhb_jgmmtj_em(start_date=ds, end_date=ds)
        except Exception:  # noqa: BLE001
            raise
        if df is None or df.empty:
            return 0
        n = 0
        buf: list[dict] = []
        for _, row in df.iterrows():
            code = _ts_code_to_code6(str(row.get("代码", "") or ""))
            if not code:
                continue
            tlist = _to_date(row.get("上榜日")) or d
            if tlist != d:
                continue
            rup = str(row.get("上榜原因", "") or "")
            b_in = _float(row.get("龙虎榜买入额"))
            b_out = _float(row.get("龙虎榜卖出额"))
            j = _float(row.get("龙虎榜净买额"))
            rec = {
                "code": code,
                "name": str(row.get("名称", "") or "")[:50],
                "trade_date": d,
                "reason": rup[:200],
                "side": "",
                "buy": b_in / 10000.0 if b_in is not None else None,
                "sell": b_out / 10000.0 if b_out is not None else None,
                "net": j / 10000.0 if j is not None else None,
                "amount_rate": _float(
                    _pick_col(
                        row,
                        "净买额占总成交比",
                        "龙虎榜净买额占总成交比",
                    ),
                ),
                "turnover": _float(_pick_col(row, "市场总成交额", "成交额")),
                "float_ratio": _float(row.get("换手率")),
                "raw_data": row.to_dict() if hasattr(row, "to_dict") else dict(row),
                "source": "em_jgmmtj",
            }
            n += 1
            buffer_push_flush(buf, rec, _flush_stock_lhb)
        if buf:
            _flush_stock_lhb(buf)
        if n > 0:
            AltD.mark_ok(CAT_LHB, sk, "eastmoney_jgmmtj", n)
        return n

    def sync_moneyflow_day(
        self,
        d: date,
        *,
        strike_state: CascadeStrikeState | None = None,
        stall_check: Callable[[], bool] | None = None,
    ) -> int:
        if stall_check and stall_check():
            return 0
        sk = d.strftime("%Y%m%d")
        built: list[tuple[str, Callable[[], int]]] = []
        if self.tushare_ok and not AltD.is_ok(CAT_MF, sk, "tushare_moneyflow"):
            built.append(
                ("tushare_moneyflow", lambda: self._sync_moneyflow_tushare(d)),
            )
        if _mf_snapshot_eligible(d):
            for ind in ("今日", "3日", "5日", "10日"):
                lid = f"em_mf_{ind}"
                if not AltD.is_ok(CAT_MF, sk, lid):
                    built.append(
                        (
                            lid,
                            (lambda j=ind: (lambda: self._sync_moneyflow_em_today_rank(d, j)))(),
                        ),
                    )
            for sym in ("即时", "3日排行", "5日排行", "10日排行", "20日排行"):
                st = "rt" if sym == "即时" else sym.replace("日排行", "d")
                lid = f"ths_mf_{st}"
                if not AltD.is_ok(CAT_MF, sk, lid):
                    built.append(
                        (
                            lid,
                            (lambda s=sym: (lambda: self._sync_moneyflow_ths_instant(d, s)))(),
                        ),
                    )
        if not built:
            return 0
        layers = _filter_cascade_layers(built, strike_state)
        if not layers:
            if strike_state is not None:
                if not strike_state.warned_all_disabled_logged:
                    logger.error(
                        "moneyflow %s: 级联源已全部被连续失败停用, 本日跳过",
                        d,
                    )
                    strike_state.warned_all_disabled_logged = True
                strike_state.request_stop = True
            return 0
        _src, n, att = run_source_stack(f"moneyflow {d:%Y-%m-%d}", layers, retries=5)
        if strike_state is not None:
            strike_state.record_attempts(att)
        if stall_check and stall_check():
            logger.warning("moneyflow: 本类滞停, 在 %s 后由上层断后续日", d)
        return n

    def _sync_moneyflow_tushare(self, d: date) -> int:
        sk = d.strftime("%Y%m%d")
        if not self.tushare_ok or self._tushare is None:
            return 0
        df = self._tushare.query("moneyflow", trade_date=sk)
        if df is None or df.empty:
            return 0
        n = 0
        buf: list[dict] = []
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
            n += 1
            buffer_push_flush(buf, rec, _flush_stock_mf)
        if buf:
            _flush_stock_mf(buf)
        if n > 0:
            AltD.mark_ok(CAT_MF, sk, "tushare_moneyflow", n)
        return n

    def _sync_moneyflow_ths_instant(self, d: date, ths_sym: str) -> int:
        """同花顺个股资金流(即时/3日/…): 行级无 trade_date, 仅用于近端日近似; 全市场分页。"""
        sk = d.strftime("%Y%m%d")
        st = "rt" if ths_sym == "即时" else ths_sym.replace("日排行", "d")
        ths_lid = f"ths_mf_{st}"
        import akshare as ak

        self._ak.acquire()
        try:
            df = ak.stock_fund_flow_individual(symbol=ths_sym)
        except Exception:  # noqa: BLE001
            raise
        if df is None or df.empty:
            return 0
        n = 0
        buf: list[dict] = []
        for _, row in df.iterrows():
            code = _ts_code_to_code6(str(row.get("股票代码", "") or row.get("代码", "")))
            if not code:
                continue
            if ths_sym == "即时":
                j = _float(row.get("净额"))
            else:
                j = _float(row.get("资金流入净额") or row.get("净额"))
            rec = {
                "code": code,
                "trade_date": d,
                "buy_sm": None,
                "buy_md": None,
                "buy_lg": None,
                "buy_elg": None,
                "sell_sm": None,
                "sell_md": None,
                "sell_lg": None,
                "sell_elg": None,
                "net_mf": j,
                "net_mf_rate": None,
                "raw_data": {
                    "ths_symbol": ths_sym,
                    **(row.to_dict() if hasattr(row, "to_dict") else {}),
                },
                "source": {
                    "即时": "ths_rt",
                    "3日排行": "ths_3d",
                    "5日排行": "ths_5d",
                    "10日排行": "ths_10d",
                    "20日排行": "ths_20d",
                }.get(ths_sym, "ths_other"),
            }
            n += 1
            buffer_push_flush(buf, rec, _flush_stock_mf)
        if buf:
            _flush_stock_mf(buf)
        if n > 0:
            AltD.mark_ok(CAT_MF, sk, ths_lid, n)
        return n

    def _sync_moneyflow_em_today_rank(self, d: date, indicator: str) -> int:
        sk = d.strftime("%Y%m%d")
        em_lid = f"em_mf_{indicator}"
        import akshare as ak

        self._ak.acquire()
        try:
            df = ak.stock_individual_fund_flow_rank(indicator=indicator)
        except Exception:  # noqa: BLE001
            raise
        if df is None or df.empty:
            return 0
        n = 0
        buf: list[dict] = []
        for _, row in df.iterrows():
            code = _ts_code_to_code6(str(row.get("代码", "") or ""))
            if not code:
                continue
            j = _float(
                _pick_col(
                    row,
                    "今日主力净流入-净额",
                    "3日主力净流入-净额",
                    "5日主力净流入-净额",
                    "10日主力净流入-净额",
                ),
            )
            r = _float(
                _pick_col(
                    row,
                    "今日主力净流入-净占比",
                    "3日主力净流入-净占比",
                    "5日主力净流入-净占比",
                    "10日主力净流入-净占比",
                ),
            )
            rec = {
                "code": code,
                "trade_date": d,
                "buy_sm": None,
                "buy_md": None,
                "buy_lg": None,
                "buy_elg": None,
                "sell_sm": None,
                "sell_md": None,
                "sell_lg": None,
                "sell_elg": None,
                "net_mf": j,
                "net_mf_rate": r,
                "raw_data": {
                    "em_indicator": indicator,
                    **(row.to_dict() if hasattr(row, "to_dict") else {}),
                },
                "source": f"em_rank_{indicator}",
            }
            n += 1
            buffer_push_flush(buf, rec, _flush_stock_mf)
        if buf:
            _flush_stock_mf(buf)
        if n > 0:
            AltD.mark_ok(CAT_MF, sk, em_lid, n)
        return n

    def sync_stk_surv(
        self,
        start: date,
        end: date,
        *,
        strike_state: CascadeStrikeState | None = None,
        stall_check: Callable[[], bool] | None = None,
    ) -> int:
        if stall_check and stall_check():
            return 0
        scope = f"{start:%Y%m%d}_{end:%Y%m%d}"
        built: list[tuple[str, Callable[[], int]]] = []
        if self.tushare_ok and not AltD.is_ok(CAT_SURVEY, scope, "tushare_stk_surv"):
            built.append(
                ("tushare_stk_surv", lambda: self._sync_stk_surv_tushare(start, end)),
            )
        for ad in _survey_tj_anchor_dates(start, end):
            aid = f"ak_jgdy_tj_{ad:%Y%m%d}"
            if not AltD.is_ok(CAT_SURVEY, scope, aid):
                built.append(
                    (
                        aid,
                        (lambda a=ad: (lambda: self._sync_stk_surv_ak_tj_one(a, start, end)))(),
                    ),
                )
        if not built:
            return 0
        layers = _filter_cascade_layers(built, strike_state)
        if not layers:
            if strike_state is not None:
                if not strike_state.warned_all_disabled_logged:
                    logger.error(
                        "survey %s..%s: 级联源已全部被连续失败停用, 本段跳过",
                        start, end,
                    )
                    strike_state.warned_all_disabled_logged = True
                strike_state.request_stop = True
            return 0
        _src, n, att = run_source_stack(f"survey {start}..{end}", layers, retries=5)
        if strike_state is not None:
            strike_state.record_attempts(att)
        if stall_check and stall_check():
            logger.warning("survey: 本类滞停, 区段 %s..%s 后提前结束", start, end)
        return n

    def _sync_stk_surv_tushare(self, start: date, end: date) -> int:
        scope = f"{start:%Y%m%d}_{end:%Y%m%d}"
        if not self.tushare_ok or self._tushare is None:
            return 0
        df = self._tushare.query(
            "stk_surv",
            start_date=start.strftime("%Y%m%d"),
            end_date=end.strftime("%Y%m%d"),
        )
        if df is None or df.empty:
            return 0
        n = 0
        buf: list[dict] = []
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
            n += 1
            buffer_push_flush(buf, rec, _flush_institution_survey)
        if buf:
            _flush_institution_survey(buf)
        if n > 0:
            AltD.mark_ok(CAT_SURVEY, scope, "tushare_stk_surv", n)
        return n

    def _sync_stk_surv_ak_tj(self, start: date, end: date) -> int:
        """兼容直调: 用区间起止两锚点 (旧行为). 级联用 ``_sync_stk_surv_ak_tj_one`` 多锚点。"""
        n = 0
        for ad in dict.fromkeys((start, end)):
            if start <= ad <= end:
                n += self._sync_stk_surv_ak_tj_one(ad, start, end)
        return n

    def _sync_stk_surv_ak_tj_one(self, anchor: date, start: date, end: date) -> int:
        import akshare as ak

        scope = f"{start:%Y%m%d}_{end:%Y%m%d}"
        src_id = f"ak_jgdy_tj_{anchor:%Y%m%d}"
        self._ak.acquire()
        try:
            df = ak.stock_jgdy_tj_em(date=anchor.strftime("%Y%m%d"))
        except Exception:  # noqa: BLE001
            raise
        if df is None or df.empty:
            return 0
        if "接待人员" in df.columns:
            df = df.copy()
            df["接待人员"] = df["接待人员"].fillna("")
        n = 0
        buf: list[dict] = []
        keys: set[tuple[str, str, str]] = set()
        for _, row in df.iterrows():
            code = _ts_code_to_code6(str(row.get("代码", "") or ""))
            if not code:
                continue
            ad = _to_date(row.get("公告日期"))
            jd = _to_date(row.get("接待日期"))
            sd: date | None = None
            if ad and start <= ad <= end:
                sd = ad
            elif jd and start <= jd <= end:
                sd = jd
            if not sd:
                continue
            org = (str(row.get("接待人员") or row.get("接待方式") or "") or "未知")[:200]
            uid = (code, str(sd), org)
            if uid in keys:
                continue
            keys.add(uid)
            rec = {
                "code": code,
                "name": str(row.get("名称", "") or "")[:100],
                "survey_date": sd,
                "org_name": org,
                "org_type": str(row.get("接待方式", "") or "")[:100],
                "content": None,
                "raw_data": row.to_dict() if hasattr(row, "to_dict") else dict(row),
                "source": f"ak_tj_{anchor:%Y%m%d}",
            }
            n += 1
            buffer_push_flush(buf, rec, _flush_institution_survey)
        if buf:
            _flush_institution_survey(buf)
        if n > 0:
            AltD.mark_ok(CAT_SURVEY, scope, src_id, n)
        return n

    def sync_hsgt_market_resuming(
        self,
        floor_ymd: str,
        end: date,
        *,
        resume: bool = True,
        fill_interior: bool | None = None,
        stall_check: Callable[[], bool] | None = None,
    ) -> int:
        """同 ``sync_hsgt_market`` 的区间拉取, 但区段与 ``hsgt_market_daily``/日K 续传同构(向今/向史/中缝)。"""
        from src.data.collect_resume import global_series_work_segments, parse_ymd

        end_ymd = end.strftime("%Y%m%d")
        segs = global_series_work_segments(
            "hsgt_market_daily", "trade_date", floor_ymd, end_ymd,
            resume=resume, fill_interior=fill_interior,
        )
        strike = _cascade_strike_state()
        n = 0
        for a, b in segs:
            if stall_check and stall_check():
                logger.warning("hsgt 续传: 本类滞停(编排器), 提前结束区段循环")
                break
            ea = min(parse_ymd(b), end)
            sa = parse_ymd(a)
            if sa > ea:
                continue
            n += self.sync_hsgt_market(sa, ea, strike_state=strike, stall_check=stall_check)
            if stall_check and stall_check():
                logger.warning("hsgt 续传: 本类滞停(编排器), 提前结束区段 (至 %s~%s)", sa, ea)
                break
            if strike.request_stop:
                logger.warning(
                    "hsgt 续传: 因级联源全部停用, 提前结束区段 (至 %s~%s)",
                    sa, ea,
                )
                break
        logger.info("hsgt 续传: %d 个区段, 累计行约 %d", len(segs), n)
        return n

    def sync_stk_surv_resuming(
        self,
        floor_ymd: str,
        end: date,
        *,
        resume: bool = True,
        fill_interior: bool | None = None,
        stall_check: Callable[[], bool] | None = None,
    ) -> int:
        """机构调研, 以 ``institution_survey.survey_date`` 为序列做续传区段。"""
        from src.data.collect_resume import global_series_work_segments, parse_ymd

        end_ymd = end.strftime("%Y%m%d")
        segs = global_series_work_segments(
            "institution_survey", "survey_date", floor_ymd, end_ymd,
            resume=resume, fill_interior=fill_interior,
        )
        strike = _cascade_strike_state()
        n = 0
        for a, b in segs:
            if stall_check and stall_check():
                logger.warning("stk_surv 续传: 本类滞停(编排器), 提前结束区段循环")
                break
            ea = min(parse_ymd(b), end)
            sa = parse_ymd(a)
            if sa > ea:
                continue
            n += self.sync_stk_surv(sa, ea, strike_state=strike, stall_check=stall_check)
            if stall_check and stall_check():
                logger.warning("stk_surv 续传: 本类滞停(编排器), 提前结束区段循环")
                break
            if strike.request_stop:
                logger.warning("stk_surv 续传: 因级联源全部停用, 提前结束区段循环")
                break
        logger.info("stk_surv 续传: %d 个区段, 累计行约 %d", len(segs), n)
        return n

    def sync_lhb_resuming(
        self,
        floor: date,
        end: date,
        *,
        resume: bool = True,
        progress_every: int = 10,
        stall_check: Callable[[], bool] | None = None,
    ) -> int:
        """龙虎榜: 只拉 **缺失交易日** 的日频(相对 ``stock_lhb_daily``)。"""
        from src.data.collect_resume import missing_trading_session_dates

        days = missing_trading_session_dates(
            "stock_lhb_daily", "trade_date", floor, end, resume=resume,
        )
        if not days:
            return 0
        strike = _cascade_strike_state()
        n = 0
        tot = len(days)
        for i, d in enumerate(days, 1):
            if stall_check and stall_check():
                logger.warning(
                    "lhb 续传: 本类滞停(编排器), 在 %d/%d 日提前结束 (至 %s)", i, tot, d,
                )
                break
            n += self.sync_top_list(d, strike_state=strike, stall_check=stall_check)
            if stall_check and stall_check():
                logger.warning(
                    "lhb 续传: 本类滞停(编排器), 在 %d/%d 日提前结束 (至 %s)", i, tot, d,
                )
                break
            if i % max(1, progress_every) == 0 or i == tot:
                logger.info("lhb 续传: %d/%d (至 %s)", i, tot, d)
            if strike.request_stop:
                logger.warning(
                    "lhb 续传: 因级联源全部停用, 在 %d/%d 日提前结束 (至 %s)",
                    i, tot, d,
                )
                break
        return n

    def sync_moneyflow_resuming(
        self,
        floor: date,
        end: date,
        *,
        resume: bool = True,
        progress_every: int = 10,
        stall_check: Callable[[], bool] | None = None,
    ) -> int:
        """个股资金流: 只拉 **缺失交易日**。"""
        from src.data.collect_resume import missing_trading_session_dates

        days = missing_trading_session_dates(
            "stock_moneyflow_daily", "trade_date", floor, end, resume=resume,
        )
        if not days:
            return 0
        strike = _cascade_strike_state()
        n = 0
        tot = len(days)
        for i, d in enumerate(days, 1):
            if stall_check and stall_check():
                logger.warning(
                    "moneyflow 续传: 本类滞停(编排器), 在 %d/%d 日提前结束 (至 %s)", i, tot, d,
                )
                break
            n += self.sync_moneyflow_day(d, strike_state=strike, stall_check=stall_check)
            if stall_check and stall_check():
                logger.warning(
                    "moneyflow 续传: 本类滞停(编排器), 在 %d/%d 日提前结束 (至 %s)", i, tot, d,
                )
                break
            if i % max(1, progress_every) == 0 or i == tot:
                logger.info("moneyflow 续传: %d/%d (至 %s)", i, tot, d)
            if strike.request_stop:
                logger.warning(
                    "moneyflow 续传: 因级联源全部停用, 在 %d/%d 日提前结束 (至 %s)",
                    i, tot, d,
                )
                break
        return n

    def _iw_scope(self, index_code: str, end: date, lookback: int) -> str:
        return f"{index_code}_{end:%Y%m%d}_lb{lookback}"

    def _iw_layer_tushare(
        self, index_code: str, end: date, lookback: int, scope: str,
    ) -> int:
        if not self.tushare_ok or self._tushare is None:
            return 0
        start = end - timedelta(days=lookback * 2)
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
        buf: list[dict] = []
        for _, row in sub.iterrows():
            con = str(row.get("con_code", "") or "")
            if not con:
                continue
            rec = {
                "index_code": index_code,
                "stock_code": con,
                "weight": _float(row.get("weight")),
            }
            n += 1
            buffer_push_flush(buf, rec, _flush_index_weight)
        if buf:
            _flush_index_weight(buf)
        if n > 0:
            AltD.mark_ok(CAT_INDEX_WEIGHT, scope, "tushare_index_weight", n)
        return n

    def _iw_layer_qmt(self, index_code: str, scope: str) -> int:
        """QMT 本地指数权重 (需已 ``download_index_weight``). 经 ``QMT_ORCHESTRATOR_LOCK`` 串行。"""
        from src.data.parallel_qmt_orchestrator import QMT_ORCHESTRATOR_LOCK

        n = 0
        buf: list[dict] = []
        with QMT_ORCHESTRATOR_LOCK:
            try:
                from src.data.qmt_client import QMTClient
                client = QMTClient()
                _ = client.xtdata
            except Exception as e:  # noqa: BLE001
                logger.debug("qmt index_weight 连接: %s", e)
                return 0
            try:
                client.download_index_weight()
            except Exception:  # noqa: BLE001
                pass
            try:
                raw = client.get_index_weight(index_code)
            except Exception as e:  # noqa: BLE001
                logger.debug("qmt get_index_weight %s: %s", index_code, e)
                return 0
            if not raw:
                return 0
            for stock_code, w in raw.items():
                sc = str(stock_code).strip()
                if "." in sc and len(sc) > 6:
                    ts = sc
                else:
                    ts = _code6_to_ts_a(sc[:6])
                if not ts or "." not in ts:
                    continue
                rec = {
                    "index_code": index_code,
                    "stock_code": ts,
                    "weight": _float(w),
                }
                n += 1
                buffer_push_flush(buf, rec, _flush_index_weight)
        if buf:
            _flush_index_weight(buf)
        if n > 0:
            AltD.mark_ok(CAT_INDEX_WEIGHT, scope, "qmt_index_weight", n)
        return n

    def _iw_layer_ak_cs_w(self, index_code: str, sym: str, scope: str) -> int:
        import akshare as ak

        self._ak.acquire()
        try:
            df = ak.index_stock_cons_weight_csindex(symbol=sym)
        except Exception as e:  # noqa: BLE001
            logger.debug("ak csindex 权重 %s: %s", sym, e)
            return 0
        if df is None or df.empty:
            return 0
        n = 0
        buf: list[dict] = []
        for _, row in df.iterrows():
            c6 = str(row.get("成分券代码", "") or "").strip().zfill(6)[:6]
            if not c6 or len(c6) < 6:
                continue
            ts = _code6_to_ts_a(c6)
            if not ts:
                continue
            w = _float(row.get("权重"))
            rec = {"index_code": index_code, "stock_code": ts, "weight": w}
            n += 1
            buffer_push_flush(buf, rec, _flush_index_weight)
        if buf:
            _flush_index_weight(buf)
        if n > 0:
            AltD.mark_ok(CAT_INDEX_WEIGHT, scope, "ak_csindex_weight", n)
        return n

    def _iw_layer_ak_cs_cons(self, index_code: str, sym: str, scope: str) -> int:
        import akshare as ak

        self._ak.acquire()
        try:
            df = ak.index_stock_cons_csindex(symbol=sym)
        except Exception as e:  # noqa: BLE001
            logger.debug("ak csindex 成份 %s: %s", sym, e)
            return 0
        if df is None or df.empty:
            return 0
        n = 0
        buf: list[dict] = []
        for _, row in df.iterrows():
            c6 = str(row.get("成分券代码", "") or "").strip().zfill(6)[:6]
            if not c6 or len(c6) < 6:
                continue
            ts = _code6_to_ts_a(c6)
            if not ts:
                continue
            rec = {"index_code": index_code, "stock_code": ts, "weight": None}
            n += 1
            buffer_push_flush(buf, rec, _flush_index_weight)
        if buf:
            _flush_index_weight(buf)
        if n > 0:
            AltD.mark_ok(CAT_INDEX_WEIGHT, scope, "ak_csindex_cons", n)
        return n

    def _iw_layer_ak_sina(self, index_code: str, sym: str, scope: str) -> int:
        import akshare as ak

        self._ak.acquire()
        try:
            df = ak.index_stock_cons_sina(symbol=sym)
        except Exception as e:  # noqa: BLE001
            logger.debug("ak sina 指数成份 %s: %s", sym, e)
            return 0
        if df is None or df.empty:
            return 0
        n = 0
        buf: list[dict] = []
        for _, row in df.iterrows():
            ts = _em_or_sina_code_to_ts(row)
            if not ts or "." not in ts:
                continue
            rec = {
                "index_code": index_code, "stock_code": ts, "weight": None,
            }
            n += 1
            buffer_push_flush(buf, rec, _flush_index_weight)
        if buf:
            _flush_index_weight(buf)
        if n > 0:
            AltD.mark_ok(CAT_INDEX_WEIGHT, scope, "ak_sina_index_cons", n)
        return n

    def _iw_layer_ak_sina_corp(
        self, index_code: str, sym: str, scope: str,
    ) -> int:
        import akshare as ak

        self._ak.acquire()
        try:
            df = ak.index_stock_cons(symbol=sym)
        except Exception as e:  # noqa: BLE001
            logger.debug("ak sina 成份(旧) %s: %s", sym, e)
            return 0
        if df is None or df.empty:
            return 0
        n = 0
        buf: list[dict] = []
        ccol = "品种代码" if "品种代码" in df.columns else None
        if ccol is None:
            for c in df.columns:
                if "代码" in str(c):
                    ccol = c
                    break
        if not ccol:
            return 0
        for _, row in df.iterrows():
            c6 = str(row.get(ccol, "") or "").strip().zfill(6)[:6]
            if not c6 or len(c6) < 6:
                continue
            ts = _code6_to_ts_a(c6)
            if not ts:
                continue
            rec = {
                "index_code": index_code, "stock_code": ts, "weight": None,
            }
            n += 1
            buffer_push_flush(buf, rec, _flush_index_weight)
        if buf:
            _flush_index_weight(buf)
        if n > 0:
            AltD.mark_ok(CAT_INDEX_WEIGHT, scope, "ak_sina_corp_index_cons", n)
        return n

    def _iw_layer_ak_sw(
        self, index_code: str, sw6: str, scope: str,
    ) -> int:
        """申万行业/主题指数成分 (ak ``index_component_sw``), 无权重时写 weight=NULL."""
        import akshare as ak

        self._ak.acquire()
        try:
            df = ak.index_component_sw(symbol=sw6)
        except Exception as e:  # noqa: BLE001
            logger.debug("ak index_component_sw %s: %s", sw6, e)
            return 0
        if df is None or df.empty:
            return 0
        cols = [str(c) for c in df.columns]
        code_c = next(
            (c for c in cols if "代码" in c and "指数" not in c),
            None,
        ) or (cols[1] if len(cols) > 1 else None)
        w_c = next((c for c in cols if "权" in c), None)
        n = 0
        buf: list[dict] = []
        for _, row in df.iterrows():
            if code_c and code_c in row.index:
                c6 = str(row.get(code_c, "") or "").strip().zfill(6)[:6]
            else:
                c6 = str(row.iloc[1]).strip().zfill(6)[:6] if len(row) > 1 else ""
            if not c6 or len(c6) < 6:
                continue
            ts = _code6_to_ts_a(c6)
            if not ts:
                continue
            wv = _float(row[w_c]) if w_c and w_c in row.index else None
            rec = {"index_code": index_code, "stock_code": ts, "weight": wv}
            n += 1
            buffer_push_flush(buf, rec, _flush_index_weight)
        if buf:
            _flush_index_weight(buf)
        if n > 0:
            AltD.mark_ok(CAT_INDEX_WEIGHT, scope, "ak_sw_index_component", n)
        return n

    def sync_index_weight(
        self,
        index_code: str,
        end: date,
        *,
        lookback_days: int = 5,
        strike_state: CascadeStrikeState | None = None,
    ) -> int:
        """指数成分权 — 多源级联 (**QMT 优先**, 再 Tushare, 再中证/新浪/申万) + 进度去重.

        表无 trade_date, 以 ``(index, end, lookback)`` 作快照键; 同键同源不重复拉取; 先成功者优先.
        """
        scope = self._iw_scope(index_code, end, lookback_days)
        sym = _index_ak_symbol(index_code)
        sw6 = _index_sw_6digit(index_code)
        built: list[tuple[str, Callable[[], int]]] = []
        if not AltD.is_ok(CAT_INDEX_WEIGHT, scope, "qmt_index_weight"):
            built.append((
                "qmt_index_weight",
                partial(self._iw_layer_qmt, index_code, scope),
            ))
        if self.tushare_ok and not AltD.is_ok(
            CAT_INDEX_WEIGHT, scope, "tushare_index_weight",
        ):
            built.append((
                "tushare_index_weight",
                partial(
                    self._iw_layer_tushare, index_code, end, lookback_days, scope,
                ),
            ))
        for lid, fn in (
            ("ak_csindex_weight", partial(self._iw_layer_ak_cs_w, index_code, sym, scope)),
            ("ak_csindex_cons", partial(self._iw_layer_ak_cs_cons, index_code, sym, scope)),
            ("ak_sina_index_cons", partial(self._iw_layer_ak_sina, index_code, sym, scope)),
            (
                "ak_sina_corp_index_cons",
                partial(self._iw_layer_ak_sina_corp, index_code, sym, scope),
            ),
        ):
            if not AltD.is_ok(CAT_INDEX_WEIGHT, scope, lid):
                built.append((lid, fn))
        if sw6 and not AltD.is_ok(CAT_INDEX_WEIGHT, scope, "ak_sw_index_component"):
            built.append((
                "ak_sw_index_component",
                partial(self._iw_layer_ak_sw, index_code, sw6, scope),
            ))
        layers = _filter_cascade_layers(built, strike_state)
        if not layers:
            if built and strike_state is not None:
                if not strike_state.warned_all_disabled_logged:
                    logger.error("index_weight %s: 级联源均已停用, 本快照跳过", scope)
                    strike_state.warned_all_disabled_logged = True
                strike_state.request_stop = True
            return 0
        _src, n, att = run_source_stack(f"index_weight {scope}", layers, retries=3)
        if strike_state is not None:
            strike_state.record_attempts(att)
        return n

    def _sector_layer_tushare(self, scope: str) -> int:
        if not self.tushare_ok or self._tushare is None:
            return 0
        df = self._tushare.query_stock_basic(
            fields="ts_code,symbol,name,industry",
        )
        if df is None or df.empty:
            return 0
        n = 0
        buf: list[dict] = []
        for _, row in df.iterrows():
            ts = str(row.get("ts_code", "") or "")
            ind = (str(row.get("industry", "") or "").strip())[:100]
            if not ts or not ind or ind in ("0", "nan", "无"):
                continue
            n += 1
            buffer_push_flush(
                buf, {"sector_name": ind, "stock_code": ts}, _flush_sector_stock,
            )
        if buf:
            _flush_sector_stock(buf)
        if n > 0:
            AltD.mark_ok(CAT_SECTOR_STOCK, scope, "tushare_industry", n)
        return n

    def _sector_layer_em_industry(
        self, scope: str, *, max_boards: int = 50,
    ) -> int:
        import akshare as ak

        self._ak.acquire()
        try:
            names = ak.stock_board_industry_name_em()
        except Exception as e:  # noqa: BLE001
            logger.warning("em 行业板列表: %s", e)
            return 0
        if names is None or names.empty or "板块名称" not in names.columns:
            return 0
        n = 0
        buf: list[dict] = []
        for bn in names["板块名称"].head(max_boards).tolist():
            bname = str(bn or "").strip()
            if not bname:
                continue
            self._ak.acquire()
            try:
                df = ak.stock_board_industry_cons_em(symbol=bname)
            except Exception:  # noqa: BLE001
                continue
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                ts = _em_or_sina_code_to_ts(row)
                if not ts or "." not in ts:
                    continue
                n += 1
                buffer_push_flush(
                    buf, {"sector_name": bname[:100], "stock_code": ts},
                    _flush_sector_stock,
                )
        if buf:
            _flush_sector_stock(buf)
        if n > 0:
            AltD.mark_ok(CAT_SECTOR_STOCK, scope, "em_industry_cons", n)
        return n

    def _sector_layer_ths_industry(
        self, scope: str, *, max_boards: int = 20,
    ) -> int:
        import akshare as ak

        self._ak.acquire()
        try:
            names = ak.stock_board_industry_name_ths()
        except Exception as e:  # noqa: BLE001
            logger.debug("ths 行业: %s", e)
            return 0
        if names is None or names.empty or "name" not in names.columns:
            return 0
        n = 0
        buf: list[dict] = []
        for bn in names["name"].head(max_boards).tolist():
            bname = str(bn or "").strip()
            if not bname:
                continue
            self._ak.acquire()
            try:
                df = ak.stock_board_industry_cons_em(symbol=bname)
            except Exception:  # noqa: BLE001
                continue
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                ts = _em_or_sina_code_to_ts(row)
                if not ts or "." not in ts:
                    continue
                n += 1
                buffer_push_flush(
                    buf, {"sector_name": f"THS|{bname[:90]}", "stock_code": ts},
                    _flush_sector_stock,
                )
        if buf:
            _flush_sector_stock(buf)
        if n > 0:
            AltD.mark_ok(CAT_SECTOR_STOCK, scope, "ths_industry_cons", n)
        return n

    def _sector_layer_em_concept(
        self, scope: str, *, max_c: int = 12,
    ) -> int:
        import akshare as ak

        self._ak.acquire()
        try:
            cnames = ak.stock_board_concept_name_em()
        except Exception as e:  # noqa: BLE001
            logger.debug("em 概念: %s", e)
            return 0
        if cnames is None or cnames.empty:
            return 0
        ccol = "板块名称" if "板块名称" in cnames.columns else cnames.columns[0]
        n = 0
        buf: list[dict] = []
        for bn in cnames[ccol].head(max_c).tolist():
            bname = str(bn or "").strip()
            if not bname:
                continue
            self._ak.acquire()
            try:
                df = ak.stock_board_concept_cons_em(symbol=bname)
            except Exception:  # noqa: BLE001
                continue
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                ts = _em_or_sina_code_to_ts(row)
                if not ts or "." not in ts:
                    continue
                n += 1
                buffer_push_flush(
                    buf, {"sector_name": f"概念|{bname[:90]}", "stock_code": ts},
                    _flush_sector_stock,
                )
        if buf:
            _flush_sector_stock(buf)
        if n > 0:
            AltD.mark_ok(CAT_SECTOR_STOCK, scope, "em_concept_cons", n)
        return n

    def _sector_layer_ths_concept(
        self, scope: str, *, max_c: int = 10,
    ) -> int:
        import akshare as ak

        self._ak.acquire()
        try:
            cnames = ak.stock_board_concept_name_ths()
        except Exception as e:  # noqa: BLE001
            logger.debug("ths 概念: %s", e)
            return 0
        if cnames is None or cnames.empty:
            return 0
        ccol = "name" if "name" in cnames.columns else cnames.columns[0]
        n = 0
        buf: list[dict] = []
        for bn in cnames[ccol].head(max_c).tolist():
            bname = str(bn or "").strip()
            if not bname:
                continue
            self._ak.acquire()
            try:
                df = ak.stock_board_concept_cons_em(symbol=bname)
            except Exception:  # noqa: BLE001
                continue
            if df is None or df.empty:
                continue
            for _, row in df.iterrows():
                ts = _em_or_sina_code_to_ts(row)
                if not ts or "." not in ts:
                    continue
                n += 1
                buffer_push_flush(
                    buf, {"sector_name": f"THS概念|{bname[:80]}", "stock_code": ts},
                    _flush_sector_stock,
                )
        if buf:
            _flush_sector_stock(buf)
        if n > 0:
            AltD.mark_ok(CAT_SECTOR_STOCK, scope, "ths_concept_cons", n)
        return n

    def sync_industry_to_sector_stock(
        self, *, strike_state: CascadeStrikeState | None = None,
    ) -> int:
        """行业/概念-股票: ``stock_basic`` + 东财/同花顺行业/概念成分, 5+ 路级联 + 进度去重.

        同键 ``ind_map_YYYYMMDD`` 内各源不重复; 无 Token 时仍可走 Ak 链.
        """
        scope = f"ind_map_{date.today():%Y%m%d}"
        built: list[tuple[str, Callable[[], int]]] = []
        if not AltD.is_ok(CAT_SECTOR_STOCK, scope, "tushare_industry"):
            built.append((
                "tushare_industry", partial(self._sector_layer_tushare, scope),
            ))
        for lid, p in (
            ("em_industry_cons", partial(self._sector_layer_em_industry, scope)),
            ("ths_industry_cons", partial(self._sector_layer_ths_industry, scope)),
            ("em_concept_cons", partial(self._sector_layer_em_concept, scope)),
            ("ths_concept_cons", partial(self._sector_layer_ths_concept, scope)),
        ):
            if not AltD.is_ok(CAT_SECTOR_STOCK, scope, lid):
                built.append((lid, p))
        layers = _filter_cascade_layers(built, strike_state)
        if not layers:
            if built and strike_state is not None:
                if not strike_state.warned_all_disabled_logged:
                    logger.error("sector_stock %s: 无可用级联源", scope)
                    strike_state.warned_all_disabled_logged = True
                strike_state.request_stop = True
            return 0
        _src, n, att = run_source_stack(
            f"sector_stock {scope}", layers, retries=3,
        )
        if strike_state is not None:
            strike_state.record_attempts(att)
        logger.info("sector_stock 级联 写入约 %d 行 (scope=%s)", n, scope)
        return n


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
        s.sync_hsgt_market(start, end, strike_state=_cascade_strike_state())
        return 0
    if args.action == "survey":
        n = s.sync_stk_surv(start, end)
        logger.info("institution_survey => %d", n)
        return 0
    if args.action == "industry-map":
        s.sync_industry_to_sector_stock(strike_state=_cascade_strike_state())
        return 0
    if args.action == "index-weight":
        n = s.sync_index_weight(
            args.index_code,
            end,
            lookback_days=args.lookback,
            strike_state=_cascade_strike_state(),
        )
        logger.info("index_weight => %d", n)
        return 0

    dates = _trade_date_range(start, end)
    total = 0
    strike = _cascade_strike_state()
    for d in dates:
        if args.action == "lhb":
            total += s.sync_top_list(d, strike_state=strike)
        else:
            total += s.sync_moneyflow_day(d, strike_state=strike)
        if strike.request_stop:
            break
    logger.info(
        "action=%s 完成, 累计写入约 %d 行 (lhb=条数, moneyflow=行数之近似)",
        args.action, total,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
