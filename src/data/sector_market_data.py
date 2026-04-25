"""板块行情数据采集 (A15)

多源: akshare
  东财: ``stock_board_industry_name_em`` + ``stock_board_industry_hist_em`` (行业日 K);
        ``stock_board_concept_name_em`` + ``stock_board_concept_hist_em`` (概念日 K);
        ``stock_sector_fund_flow_rank`` (行业/概念/地域 × 今/5 日/10 日; API 为**实时**快照)
  同花顺: ``stock_board_industry_name_ths`` + ``stock_board_industry_index_ths`` (行业指数线 → 日涨跌幅)

``sector_name`` 前缀(唯一键与 ``trade_date``): 东财行业无前缀; ``概·``/``同·``/``流·{行|念|地}·{今|5日|10日}·{名}``。

续传: ``global_series_work_segments`` 对 K 线行计算区段(资金行 ``流·%`` 在 ``collect_resume`` 中已排除, 不驱动 MIN/MAX/中缝).

进度: ``alt_datacollect_progress`` (``CAT_SECTOR_DATA``) 按区段/日快照键+源 id 去重; 子源若部分失败未标 ok, 下轮可重试整段.
"""
from __future__ import annotations

import re
from datetime import datetime, date

import pandas as pd
from sqlalchemy.dialects.postgresql import insert

from src.common.config import settings
from src.common.db import get_session
from src.common.db_batch import DEFAULT_TABLE_UPSERT_FLUSH, log_upsert_commit
from src.common.logger import get_logger
from src.data.alt_datacollect_progress import (
    AltDatacollectProgressDAO as AltD,
    CAT_SECTOR_DATA,
)
from src.datacollect.rate_limiter import TokenBucketLimiter

logger = get_logger(__name__)

# 单区段内概念/同花顺批次数上限 (避免单段耗时过长; 可扩配置)
_SECTOR_CONCEPT_MAX = 45
_SECTOR_THS_MAX = 45
# 东财 ``stock_sector_fund_flow_rank`` 仅支持 今日/5日/10日(无 3 日).
_FUND_INDICATORS: tuple[str, ...] = ("今日", "5日", "10日")
_FUND_SECTOR_TYPES: tuple[str, ...] = (
    "行业资金流",
    "概念资金流",
    "地域资金流",
)
_ST_SHORT = {
    "行业资金流": "行",
    "概念资金流": "念",
    "地域资金流": "地",
}


def _get_limiter() -> TokenBucketLimiter:
    return TokenBucketLimiter.for_domain(
        "akshare",
        rate=settings.datacollect.akshare_rate,
        burst=settings.datacollect.akshare_burst,
    )


def _sn(s: str, max_len: int = 50) -> str:
    x = (s or "").strip()
    return x[:max_len] if len(x) > max_len else x


class SectorMarketSync:
    """板块行情 — 东财行业/概念 K、同花顺行业指数、多档资金流向, UPSERT ``sector_data``."""

    def sync_sector_data(
        self,
        start_date: str = "20230101",
        end_date: str | None = None,
        *,
        resume: bool = True,
        fill_interior: bool | None = None,
        include_fund_flow: bool = True,
        force_fund_snapshot: bool = False,
    ) -> int:
        import akshare as ak

        from src.data.collect_resume import parse_ymd

        limiter = _get_limiter()
        end_date = end_date or datetime.now().strftime("%Y%m%d")
        today_s = datetime.now().strftime("%Y%m%d")
        d_end = parse_ymd(end_date)
        d_today = date.today()
        total = 0
        # 东财资金 API 为当前市场快照, ``trade_date`` 记为**拉取日**; end<今日时默认不拉资金以免误以历史日语义落库
        want_fund = bool(include_fund_flow) and (
            end_date >= today_s or (bool(force_fund_snapshot) and d_end < d_today)
        )
        if want_fund and force_fund_snapshot and d_end < d_today:
            logger.info(
                "板块资金: force_fund_snapshot=真, 区间 end=%s 已早于今日; 数据仍为**实时**快照, trade_date=今日",
                end_date,
            )

        if not resume:
            total += self._sync_one_date_window(
                ak, limiter, start_date, end_date, use_progress=False,
            )
            if want_fund:
                total += self._sync_fund_flow_all(ak, limiter, use_progress=False)
            logger.info("板块行情同步完成, 共 UPSERT 约 %d 条", total)
            return total

        from src.data.collect_resume import global_series_work_segments

        segs = global_series_work_segments(
            "sector_data", "trade_date", start_date, end_date,
            resume=True, fill_interior=fill_interior,
        )
        for a, b in segs:
            total += self._sync_one_date_window(
                ak, limiter, a, b, use_progress=True,
            )
        if want_fund:
            total += self._sync_fund_flow_all(ak, limiter, use_progress=True)
        logger.info("板块行情同步(续传) %d 区段, 共 UPSERT 约 %d 条", len(segs), total)
        return total

    def _sync_one_date_window(
        self,
        ak,
        limiter: TokenBucketLimiter,
        a: str,
        b: str,
        *,
        use_progress: bool,
    ) -> int:
        sk = f"{a}_{b}"
        n = 0
        if not (use_progress and AltD.is_ok(
            CAT_SECTOR_DATA, sk, "em_industry_board_hist",
        )):
            c = self._sync_em_industry_hist(ak, limiter, a, b)
            n += c
            if use_progress and c > 0:
                AltD.mark_ok(CAT_SECTOR_DATA, sk, "em_industry_board_hist", c)
        if not (use_progress and AltD.is_ok(
            CAT_SECTOR_DATA, sk, "em_concept_board_hist",
        )):
            c = self._sync_em_concept_hist(ak, limiter, a, b)
            n += c
            if use_progress and c > 0:
                AltD.mark_ok(CAT_SECTOR_DATA, sk, "em_concept_board_hist", c)
        if not (use_progress and AltD.is_ok(
            CAT_SECTOR_DATA, sk, "ths_industry_index",
        )):
            c = self._sync_ths_industry_index(ak, limiter, a, b)
            n += c
            if use_progress and c > 0:
                AltD.mark_ok(CAT_SECTOR_DATA, sk, "ths_industry_index", c)
        return n

    def _sync_em_industry_hist(
        self, ak, limiter: TokenBucketLimiter, start_date: str, end_date: str,
    ) -> int:
        sector_names = self._fetch_sector_names_industry(ak, limiter)
        if not sector_names:
            return 0
        count = 0
        for idx, name in enumerate(sector_names):
            sname = _sn(name)
            if not sname:
                continue
            try:
                limiter.acquire()
                df = ak.stock_board_industry_hist_em(
                    symbol=name,
                    start_date=start_date,
                    end_date=end_date,
                    period="日k",
                    adjust="",
                )
                if df is None or df.empty:
                    continue
                rows = self._map_hist_rows(sname, df, prefer_change=True)
                if rows:
                    self._bulk_upsert(rows)
                    count += len(rows)
                if (idx + 1) % 50 == 0:
                    logger.info("东财行业板块K 进度: %d/%d", idx + 1, len(sector_names))
            except Exception as e:
                logger.warning("东财行业板块 %s 历史失败: %s", name, e)
        logger.info("东财行业板块K 入库 %d 行 (共 %d 个板块名)", count, len(sector_names))
        return count

    def _sync_em_concept_hist(
        self, ak, limiter: TokenBucketLimiter, start_date: str, end_date: str,
    ) -> int:
        names = self._fetch_concept_names(ak, limiter, _SECTOR_CONCEPT_MAX)
        if not names:
            return 0
        count = 0
        for idx, name in enumerate(names):
            sname = _sn(f"概·{name}")
            if not sname or len(sname) < 2:
                continue
            try:
                limiter.acquire()
                df = ak.stock_board_concept_hist_em(
                    symbol=name,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust="",
                )
                if df is None or df.empty:
                    continue
                rows = self._map_hist_rows(sname, df, prefer_change=True)
                if rows:
                    self._bulk_upsert(rows)
                    count += len(rows)
                if (idx + 1) % 20 == 0:
                    logger.info("东财概念板K 进度: %d/%d", idx + 1, len(names))
            except Exception as e:
                logger.warning("东财概念 %s 历史失败: %s", name, e)
        logger.info("东财概念板块K 入库 %d 行 (尝试 %d 个概念)", count, len(names))
        return count

    def _sync_ths_industry_index(
        self, ak, limiter: TokenBucketLimiter, start_date: str, end_date: str,
    ) -> int:
        try:
            limiter.acquire()
            meta = ak.stock_board_industry_name_ths()
        except Exception as e:
            logger.warning("同花顺行业名列表失败: %s", e)
            return 0
        if meta is None or meta.empty or "name" not in meta.columns:
            return 0
        raw = meta["name"].dropna().astype(str).tolist()[:_SECTOR_THS_MAX]
        count = 0
        for idx, name in enumerate(raw):
            sname = _sn(f"同·{name}")
            if not sname or len(sname) < 2:
                continue
            try:
                limiter.acquire()
                df = ak.stock_board_industry_index_ths(
                    symbol=name,
                    start_date=start_date,
                    end_date=end_date,
                )
                if df is None or df.empty:
                    continue
                rows = self._map_ths_index_rows(sname, df)
                if rows:
                    self._bulk_upsert(rows)
                    count += len(rows)
                if (idx + 1) % 10 == 0:
                    logger.info("同花顺行业指数K 进度: %d/%d", idx + 1, len(raw))
            except Exception as e:
                logger.warning("同花顺行业 %s 指数线失败: %s", name, e)
        logger.info("同花顺行业指数K 入库 %d 行 (尝试 %d 个)", count, len(raw))
        return count

    def _sync_fund_flow_all(
        self, ak, limiter: TokenBucketLimiter, *, use_progress: bool,
    ) -> int:
        today = date.today()
        ymd = today.strftime("%Y%m%d")
        n = 0
        for st in _FUND_SECTOR_TYPES:
            for ind in _FUND_INDICATORS:
                sk = f"{ymd}_ff_{st}_{ind}"
                if use_progress and AltD.is_ok(
                    CAT_SECTOR_DATA, sk, "em_sector_fund_flow_rank",
                ):
                    continue
                c = self._sync_sector_fund_flow_one(
                    ak, limiter, st, ind, today,
                )
                n += c
                if use_progress and c > 0:
                    AltD.mark_ok(
                        CAT_SECTOR_DATA, sk, "em_sector_fund_flow_rank", c,
                    )
        return n

    @staticmethod
    def _sync_sector_fund_flow_one(
        ak,
        limiter: TokenBucketLimiter,
        sector_type: str,
        indicator: str,
        on_date: date,
    ) -> int:
        try:
            limiter.acquire()
            df = ak.stock_sector_fund_flow_rank(
                indicator=indicator, sector_type=sector_type,
            )
        except Exception as e:
            logger.warning("板块资金排名 %s %s: %s", sector_type, indicator, e)
            return 0
        if df is None or df.empty:
            return 0
        st1 = _ST_SHORT.get(sector_type, "行")
        ip = _fund_ind_short(indicator)
        rows: list[dict] = []
        for _, row in df.iterrows():
            name = row.get("名称") or row.get("行业")
            if not name:
                continue
            sname = _sn(f"流·{st1}·{ip}·{name}")
            rows.append({
                "sector_name": sname,
                "trade_date": on_date,
                "change_pct": _row_change_pct_fund(row, indicator),
                "net_inflow": _row_net_inflow_fund(row, indicator),
                "leading_stock": _leading_fund_row(row),
            })
        if rows:
            SectorMarketSync._bulk_upsert(rows)
        logger.info("板块资金 %s %s 入库 %d 行", sector_type, indicator, len(rows))
        return len(rows)

    @staticmethod
    def _fetch_sector_names_industry(ak, limiter: TokenBucketLimiter) -> list[str]:
        try:
            limiter.acquire()
            df = ak.stock_board_industry_name_em()
            if df is None or df.empty:
                return []
            col = "板块名称" if "板块名称" in df.columns else df.columns[0]
            return df[col].dropna().astype(str).unique().tolist()
        except Exception as e:
            logger.error("东财行业板块列表: %s", e)
            return []

    @staticmethod
    def _fetch_concept_names(
        ak, limiter: TokenBucketLimiter, cap: int,
    ) -> list[str]:
        try:
            limiter.acquire()
            df = ak.stock_board_concept_name_em()
            if df is None or df.empty:
                return []
            col = "板块名称" if "板块名称" in df.columns else df.columns[0]
            out = df[col].dropna().astype(str).unique().tolist()
            return out[: max(1, min(cap, len(out)))]
        except Exception as e:
            logger.warning("东财概念板块列表: %s", e)
            return []

    @staticmethod
    def _map_ths_index_rows(sector_name: str, df: pd.DataFrame) -> list[dict]:
        cols = list(df.columns)
        date_key = cols[0]
        for c in cols:
            cs = str(c)
            if "日期" in cs or cs in ("时间", "date"):
                date_key = c
                break
        close_key = None
        for c in cols:
            cs = str(c)
            if "收盘" in cs or cs in ("close", "收盘价"):
                close_key = c
                break
        if close_key is None and len(cols) >= 5:
            close_key = cols[4]
        elif close_key is None:
            return []
        s_close = pd.to_numeric(df[close_key], errors="coerce")
        pct = s_close.pct_change() * 100.0
        out: list[dict] = []
        for j in range(len(df)):
            r = df.iloc[j]
            raw_d = r[date_key] if date_key in r.index else r.iloc[0]
            td = _parse_trade_date_cell(raw_d)
            if td is None:
                continue
            v = pct.iloc[j]
            out.append({
                "sector_name": sector_name,
                "trade_date": td,
                "change_pct": None
                if v is None or (isinstance(v, float) and pd.isna(v))
                else float(v),
            })
        return out

    @staticmethod
    def _map_hist_rows(
        sector_name: str, df, *, prefer_change: bool,
    ) -> list[dict]:
        rows: list[dict] = []
        for _, row in df.iterrows():
            raw_date = row.get("日期")
            if raw_date is None:
                continue
            td = _parse_trade_date_cell(raw_date)
            if td is None:
                continue
            chg = _safe_float(row, "涨跌幅")
            if chg is None and prefer_change:
                chg = _safe_float(row, "change") or _safe_float(row, "涨跌幅%")
            rows.append({
                "sector_name": sector_name,
                "trade_date": td,
                "change_pct": chg,
            })
        return rows

    @staticmethod
    def _bulk_upsert(
        rows: list[dict], batch_size: int = DEFAULT_TABLE_UPSERT_FLUSH,
    ) -> None:
        from src.data.models import SectorData

        for i in range(0, len(rows), batch_size):
            batch = rows[i: i + batch_size]
            with get_session() as session:
                stmt = insert(SectorData).values(batch)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["sector_name", "trade_date"],
                    set_={
                        "change_pct": stmt.excluded.change_pct,
                        "net_inflow": stmt.excluded.net_inflow,
                        "leading_stock": stmt.excluded.leading_stock,
                    },
                )
                session.execute(stmt)
            log_upsert_commit("akshare.sector_data", len(batch))


def _parse_trade_date_cell(raw) -> date | None:
    if raw is None:
        return None
    try:
        if isinstance(raw, str):
            return datetime.strptime(raw[:10], "%Y-%m-%d").date()
        if isinstance(raw, (date, datetime)):
            return raw if isinstance(raw, date) else raw.date()
        return pd.Timestamp(raw).date()
    except Exception:
        return None


def _fund_ind_short(indicator: str) -> str:
    if indicator == "今日":
        return "今"
    m = re.match(r"^(\d+)日?$", indicator.strip())
    if m:
        return f"{m.group(1)}日"
    return indicator[:3]


def _row_change_pct_fund(row, indicator: str) -> float | None:
    keys = {
        "今日": ("今日涨跌幅",),
        "5日": ("5日涨跌幅",),
        "10日": ("10日涨跌幅",),
    }.get(indicator, ("涨跌幅",))
    for key in keys:
        v = _safe_float(row, key)
        if v is not None:
            return v
    for key in ("涨跌幅", "今日涨跌幅"):
        v = _safe_float(row, key)
        if v is not None:
            return v
    return None


def _row_net_inflow_fund(row, indicator: str) -> float | None:
    keys = {
        "今日": ("今日主力净流入-净额",),
        "5日": ("5日主力净流入-净额",),
        "10日": ("10日主力净流入-净额",),
    }.get(indicator, ("主力净流入-净额", "今日主力净流入-净额"))
    for k in keys:
        v = _safe_float(row, k, scale=1e-8)
        if v is not None:
            return v
    for k in ("今日主力净流入-净额", "主力净流入-净额"):
        v = _safe_float(row, k, scale=1e-8)
        if v is not None:
            return v
    return None


def _leading_fund_row(row) -> str | None:
    for k in row.index:
        ks = str(k)
        if "最大股" in ks and "代码" not in ks:
            v = row.get(k)
            if v is not None and not (isinstance(v, float) and pd.isna(v)):
                s = str(v).strip()
                if s and s not in ("-", "_", "nan"):
                    return s
    return _safe_str(row, "今日主力净流入最大股")


def _safe_float(row, col: str, scale: float = 1.0):
    try:
        v = row.get(col)
        if v is not None:
            if not pd.isna(v):
                return float(v) * scale
    except Exception:
        pass
    return None


def _safe_str(row, col: str) -> str | None:
    try:
        v = row.get(col)
        if v is not None:
            if not pd.isna(v):
                return str(v)
    except Exception:
        pass
    return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="板块行情数据采集 (akshare)")
    parser.add_argument(
        "action",
        choices=["all", "hist", "fund_flow", "industry", "concept", "ths"],
        help="all=行业K+概念K+同花顺+资金; hist=仅东财行业K; fund_flow=仅资金; 其余=单路历史",
    )
    parser.add_argument("--start-date", default="20250401", help="历史起始 YYYYMMDD")
    args = parser.parse_args()
    sync = SectorMarketSync()
    end_s = datetime.now().strftime("%Y%m%d")
    if args.action == "fund_flow":
        import akshare as ak
        n = sync._sync_fund_flow_all(ak, _get_limiter(), use_progress=False)
        print(f"板块资金流向: {n} 条")  # noqa: T201
    elif args.action == "all":
        n = sync.sync_sector_data(start_date=args.start_date)
        print(f"全量: {n} 条")  # noqa: T201
    else:
        import akshare as ak
        limiter = _get_limiter()
        if args.action in ("industry", "hist"):
            n = sync._sync_em_industry_hist(ak, limiter, args.start_date, end_s)
        elif args.action == "concept":
            n = sync._sync_em_concept_hist(ak, limiter, args.start_date, end_s)
        else:
            n = sync._sync_ths_industry_index(ak, limiter, args.start_date, end_s)
        print(f"板块历史: {n} 条")  # noqa: T201
