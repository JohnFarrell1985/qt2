"""通过 akshare 采集 ETF / 财务报表 / 财务指标数据

独立于 QMT 的数据补充通道, 使用 akshare 公开接口采集:
- A12: ETF 列表 + ETF 日线行情
- A12b: 东财基金 F10 ``jbgk_{code}.html`` → ``tracking_index`` / ``management_fee`` / ``establish_date`` / ``latest_scale``
- A13: 财务报表 (利润/资产负债/现金流摘要)
- A14: 财务分析指标 (每股/盈利/偿债/成长)

所有 akshare 调用均受 TokenBucketLimiter 限流保护。

ETF 日线与东财 F10 页面优先走 ``src.datacollect.client.SmartHttpClient`` 与
``kline_bulk_sync``(东财/腾讯); 单请求腾讯约 500 根, ``kline_bulk_sync`` 已分页。
其后 (任一有数据即停): 新浪、**Tushare** ``fund_daily``(场内基金/ETF; 需 ``TUSHARE_TOKEN`` 与接口权限,
无数据时再回退股票 ``daily``)、AkShare 东财页 ``fund_etf_hist_em``、**baostock**、yfinance。
K 线主路在 ``kline_bulk_sync.fetch_etf_daily_cascade`` 内东财+腾讯两路都试.

其他可整合但**未接代码**的商用/独立源 (需自行申请 Key, 防爬与东财/新浪不同):
智兔数服、黑狼数据、聚合数据等 ETF 日 K; 接入方式与 ``TushareCollector.query`` 类似, 可增独立 fetch 与 env 开关。

OKX/CCXT 为加密货币, 不接入 A 股 ETF.
"""
from __future__ import annotations

import re
import sys
import time
from collections import Counter, defaultdict
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta
from io import StringIO
from typing import Any

import pandas as pd
import requests
from sqlalchemy import func, or_, text
from sqlalchemy.dialects.postgresql import insert
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.common.config import settings
from src.common.db import get_session
from src.common.logger import get_logger
from src.data.models import (
    ETFDaily,
    ETFInfo,
    Stock,
    StockFinancialIndicator,
    StockFinancialReport,
)
from src.datacollect.rate_limiter import TokenBucketLimiter

logger = get_logger(__name__)


class EtfDailyStallError(RuntimeError):
    """ETF 日线在 ``stall_no_rows_sec`` 内未写入任何新 K 线, 可切换数据源后重试。"""


class EtfDailyNoDataError(RuntimeError):
    """有待拉标的但本轮未写入任何行 (全部失败), 外层可换源或整轮重试。"""

_CFG = settings.datacollect
# 东财 fundf10 页面限流 (与 DATACOLLECT_EASTMONEY_* 联动, 略快于默认 0.1 以免过慢)
_F10_RATE = max(0.45, float(_CFG.eastmoney_rate) * 4.5)
_F10_BURST = max(2, int(_CFG.eastmoney_burst))


def _safe_float(v: Any) -> float | None:
    """安全转换为 float, 失败返回 None。"""
    try:
        if v is not None and not pd.isna(v):
            return float(v)
    except (TypeError, ValueError):
        pass
    return None


def _safe_date(v: Any) -> Any:
    """安全转换为 date 对象, 失败返回 None。"""
    try:
        if v is not None and not pd.isna(v):
            return pd.Timestamp(v).date()
    except Exception:
        pass
    return None


def _ymd8_to_date(s: str) -> date:
    return datetime.strptime(s[:8], "%Y%m%d").date()


def _parse_cn_yyyymmdd_in_text(s: str) -> Any:
    """从 ``2012年05月04日 / xxx`` 类字符串中取首个日期。"""
    if not s or s == "nan":
        return None
    m = re.search(r"(\d{4})年(\d{2})月(\d{2})日", s)
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3))).date()
    except ValueError:
        return None


def _parse_fee_percent(s: str) -> float | None:
    """从 ``0.15%（每年）`` 解析管理费比例。"""
    if not s or s in ("nan", "---（每年）"):
        return None
    m = re.search(r"([\d.]+)\s*%", s)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def _parse_scale_yi_from_jbgk(s: str) -> float | None:
    """从 ``4,222.58亿元（截止至：...）`` 解析规模(亿)。"""
    if not s or s == "nan":
        return None
    m = re.search(r"([\d,]+\.?\d*)\s*亿元", s)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", ""))
    except ValueError:
        return None


class AkshareFinancialSync:
    """通过 akshare 采集 ETF / 财务报表 / 财务指标数据"""

    def __init__(self, limiter: TokenBucketLimiter | None = None):
        self._limiter = limiter or TokenBucketLimiter.for_domain(
            "akshare",
            rate=_CFG.akshare_rate,
            burst=_CFG.akshare_burst,
        )
        self._f10_limiter = TokenBucketLimiter.for_domain(
            "eastmoney_fundf10",
            rate=_F10_RATE,
            burst=_F10_BURST,
        )

    def _call_ak(self, func_name: str, **kwargs: Any) -> pd.DataFrame:
        """调用 akshare 函数, 带限流与网络重试。"""
        import akshare as ak
        import requests

        fn = getattr(ak, func_name, None)
        if fn is None:
            raise AttributeError(f"akshare 没有函数: {func_name}")

        self._limiter.acquire()

        @retry(
            reraise=True,
            stop=stop_after_attempt(6),
            wait=wait_exponential(multiplier=1, min=2, max=90),
            retry=retry_if_exception_type(
                (
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.ChunkedEncodingError,
                ),
            ),
        )
        def _run():
            return fn(**kwargs)

        return _run()

    @staticmethod
    def _etf_exchange_suffix(raw_code: str) -> str:
        """与 ``akshare.fund.fund_etf_em.get_market_id`` 一致: 5/6 开头为上交所。"""
        c = (raw_code or "").strip()
        if c.startswith(("5", "6")):
            return ".SH"
        return ".SZ"

    @staticmethod
    def _normalize_etf_list_code(raw: str) -> str:
        """新浪列表常为 ``sh510300`` / ``sz159915``; 东财为 ``510300``。统一为 6 位数字。"""
        r = (raw or "").strip()
        low = r.lower()
        if low.startswith("sh") and len(low) >= 8 and low[2:8].isdigit():
            return low[2:8]
        if low.startswith("sz") and len(low) >= 8 and low[2:8].isdigit():
            return low[2:8]
        return r

    @staticmethod
    def _etf_sina_symbol(full_code: str) -> str:
        """新浪 ETF 日 K 接口: ``sh510300`` / ``sz159915``。"""
        num = full_code.split(".")[0]
        if full_code.upper().endswith(".SH"):
            return f"sh{num}"
        return f"sz{num}"

    # ------------------------------------------------------------------
    # A12: ETF 列表 + ETF 日线
    # ------------------------------------------------------------------

    def sync_etf_list(self) -> int:
        """从东财 ``fund_etf_spot_em`` (含总市值) 拉 ETF; 失败则用新浪 ``fund_etf_category_sina`` 兜底。"""
        logger.info("开始同步 ETF 列表 (东财现货优先, 新浪列表兜底)...")
        df = None
        try:
            df = self._call_ak("fund_etf_spot_em")
        except Exception as e:
            logger.warning("东财 ETF 列表失败: %s — 尝试新浪", e)

        if df is None or df.empty:
            try:
                import akshare as ak

                self._limiter.acquire()
                df = ak.fund_etf_category_sina(symbol="ETF基金")
            except Exception as e2:
                logger.error("新浪 ETF 列表也失败: %s", e2)
                return 0

        if df is None or df.empty:
            logger.warning("ETF 列表为空")
            return 0

        records: list[dict] = []
        for _, row in df.iterrows():
            raw_code = self._normalize_etf_list_code(str(row.get("代码", "")).strip())
            if not raw_code or not raw_code.isdigit():
                continue
            suffix = self._etf_exchange_suffix(raw_code)
            full = raw_code + suffix
            nm = str(row.get("名称", "") or "").strip()
            mcap = _safe_float(row.get("总市值"))
            scale_yi = (mcap / 1e8) if mcap is not None else None
            record: dict[str, Any] = {
                "code": full,
                "name": nm or full,
                "latest_scale": scale_yi,
                "updated_at": datetime.now(),
            }
            records.append(record)

        if not records:
            logger.warning("ETF 列表解析后无有效记录")
            return 0

        total = 0
        with get_session() as session:
            for batch_start in range(0, len(records), 500):
                batch = records[batch_start:batch_start + 500]
                stmt = insert(ETFInfo).values(batch)
                ex = stmt.excluded
                stmt = stmt.on_conflict_do_update(
                    index_elements=["code"],
                    set_={
                        "name": func.coalesce(ex.name, ETFInfo.name),
                        "latest_scale": func.coalesce(
                            ex.latest_scale, ETFInfo.latest_scale,
                        ),
                        "updated_at": ex.updated_at,
                    },
                )
                session.execute(stmt)
                total += len(batch)

        logger.info("ETF 列表同步完成, 共 %d 条", total)
        return total

    @staticmethod
    def _etf_f10_jbgk_key_values(num_code: str) -> dict[str, str]:
        """天天基金「基本概况」页 → 键值对.

        使用 :class:`src.datacollect.client.SmartHttpClient` (curl_cffi 指纹 + 代理 +
        反爬哨兵), 与 ``kline_bulk_sync`` 东财通道一致; 可配 ``DATACOLLECT_PROXY_URL``。
        """
        from src.datacollect.client import SmartHttpClient

        url = f"https://fundf10.eastmoney.com/jbgk_{num_code.strip()}.html"
        client = SmartHttpClient()
        resp = client.get(
            url,
            headers={
                "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9",
            },
        )
        html = resp.text
        dfs = pd.read_html(StringIO(html))
        main = None
        for d in dfs:
            if d.shape[1] >= 4 and d.shape[0] >= 6:
                main = d
                break
        if main is None:
            return {}
        kv: dict[str, str] = {}
        for _, row in main.iterrows():
            for j in (0, 2):
                if j + 1 >= len(row):
                    continue
                k = str(row.iloc[j]).strip()
                v = str(row.iloc[j + 1]).strip()
                if k and k != "nan" and not k.startswith("Unnamed"):
                    kv[k] = v
        return kv

    def enrich_etf_info_from_f10_em(
        self,
        only_missing: bool = True,
    ) -> int:
        """东财基金 F10 ``jbgk`` 页补 ``tracking_index`` / ``management_fee`` / ``establish_date`` / ``latest_scale``。"""
        logger.info(
            "东财 F10 补全 etf_info (only_missing=%s)...", only_missing,
        )
        with get_session(readonly=True) as session:
            q = session.query(ETFInfo.code, ETFInfo.name)
            if only_missing:
                q = q.filter(
                    or_(
                        ETFInfo.tracking_index.is_(None),
                        ETFInfo.management_fee.is_(None),
                        ETFInfo.establish_date.is_(None),
                        ETFInfo.latest_scale.is_(None),
                    ),
                )
            pairs = q.all()
        code_to_name: dict[str, str] = {c: n for c, n in pairs}

        if not code_to_name:
            logger.info("etf_info 无需 F10 补全")
            return 0

        @retry(
            reraise=True,
            stop=stop_after_attempt(4),
            wait=wait_exponential(multiplier=1, min=2, max=60),
            retry=retry_if_exception_type(
                (
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.HTTPError,
                ),
            ),
        )
        def _fetch_kv(num: str) -> dict[str, str]:
            return self._etf_f10_jbgk_key_values(num)

        batch: list[dict[str, Any]] = []
        done = 0
        total_codes = len(code_to_name)
        for idx, (full_code, nm) in enumerate(code_to_name.items(), start=1):
            num = full_code.split(".")[0]
            self._f10_limiter.acquire()
            try:
                kv = _fetch_kv(num)
            except Exception as e:
                if idx <= 5:
                    logger.debug("F10 jbgk %s: %s", full_code, e)
                continue
            if not kv:
                continue
            track = (
                kv.get("跟踪标的")
                or kv.get("业绩比较基准")
                or ""
            ).strip()
            if len(track) > 100:
                track = track[:100]
            fee = _parse_fee_percent(kv.get("管理费率", ""))
            est = _parse_cn_yyyymmdd_in_text(kv.get("成立日期/规模", ""))
            if est is None:
                est = _parse_cn_yyyymmdd_in_text(kv.get("发行日期", ""))
            scale = _parse_scale_yi_from_jbgk(kv.get("净资产规模", ""))

            name_val = (nm or full_code) if isinstance(nm, str) else str(full_code)
            batch.append({
                "code": full_code,
                "name": name_val,
                "tracking_index": track or None,
                "management_fee": fee,
                "establish_date": est,
                "latest_scale": scale,
                "updated_at": datetime.now(),
            })
            done += 1

            if len(batch) >= 40:
                self._upsert_etf_info_batch(batch)
                batch.clear()
            if idx % 200 == 0:
                logger.info("F10 进度 %d/%d (成功 %d)", idx, total_codes, done)

        if batch:
            self._upsert_etf_info_batch(batch)

        logger.info("东财 F10 etf_info 补全完成, 成功解析 %d / %d", done, total_codes)
        return done

    def _upsert_etf_info_batch(self, rows: list[dict[str, Any]]) -> None:
        """COALESCE 合并, 避免用 NULL 覆盖已有字段。"""
        if not rows:
            return
        stmt = insert(ETFInfo).values(rows)
        ex = stmt.excluded
        stmt = stmt.on_conflict_do_update(
            index_elements=["code"],
            set_={
                "name": func.coalesce(ex.name, ETFInfo.name),
                "tracking_index": func.coalesce(
                    ex.tracking_index, ETFInfo.tracking_index,
                ),
                "management_fee": func.coalesce(
                    ex.management_fee, ETFInfo.management_fee,
                ),
                "establish_date": func.coalesce(
                    ex.establish_date, ETFInfo.establish_date,
                ),
                "latest_scale": func.coalesce(
                    ex.latest_scale, ETFInfo.latest_scale,
                ),
                "updated_at": ex.updated_at,
            },
        )
        with get_session() as session:
            session.execute(stmt)

    def enrich_etf_establish_date_from_daily(self) -> int:
        """用 ``etf_daily`` 最早交易日近似 **成立/上市首日**, 仅填补 ``establish_date`` 为空。"""
        sql = text("""
            UPDATE etf_info e
            SET establish_date = d.first_dt,
                updated_at = NOW()
            FROM (
                SELECT code, MIN(trade_date) AS first_dt
                FROM etf_daily
                GROUP BY code
            ) d
            WHERE e.code = d.code
              AND e.establish_date IS NULL
              AND d.first_dt IS NOT NULL
        """)
        with get_session() as session:
            res = session.execute(sql)
            n = res.rowcount or 0
        logger.info("从 etf_daily 回填 etf_info.establish_date: %d 行", int(n))
        return int(n)

    def _etf_daily_records_from_sina(
        self,
        full_code: str,
        start_date: str,
        end_date: str,
    ) -> list[dict]:
        """新浪 ETF 日 K 兜底 (plain requests), 返回与 :meth:`sync_etf_daily` 相同的行字典。"""
        try:
            self._limiter.acquire()
            import akshare as ak

            df2 = ak.fund_etf_hist_sina(symbol=self._etf_sina_symbol(full_code))
        except Exception as e2:
            logger.warning("ETF %s 新浪日线失败: %s", full_code, e2)
            return []
        if df2 is None or df2.empty:
            return []
        out = pd.DataFrame()
        out["日期"] = df2["date"]
        out["开盘"] = df2["open"]
        out["收盘"] = df2["close"]
        out["最高"] = df2["high"]
        out["最低"] = df2["low"]
        out["成交量"] = df2["volume"]
        out["成交额"] = None
        start_d = _safe_date(
            f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}",
        )
        end_d = _safe_date(
            f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}",
        )
        if start_d:
            out = out[out["日期"] >= start_d]
        if end_d:
            out = out[out["日期"] <= end_d]
        return self._map_etf_daily(out, full_code)

    # ------------------------------------------------------------------
    # ETF 日线 — 更多兜底 (东财/腾讯/新浪之后). OKX/CCXT 为加密货币, 不适用 A 股 ETF.
    # ------------------------------------------------------------------

    @staticmethod
    def _to_baostock_code(full_code: str) -> str:
        """``510300.SH`` → ``sh.510300`` (baostock)。"""
        n = (full_code or "").split(".")[0]
        u = (full_code or "").upper()
        if u.endswith(".SH") or n.startswith(("5", "6", "9")):
            return f"sh.{n}"
        return f"sz.{n}"

    @staticmethod
    def _tushare_ts_code(full_code: str) -> str:
        """Tushare ``daily`` 与 stock 同型: ``510300.SH`` / ``159920.SZ``。"""
        n = (full_code or "").split(".")[0]
        s = (full_code or "").upper()
        if s.endswith(".SH") or n.startswith(("5", "6", "9")):
            return f"{n}.SH"
        return f"{n}.SZ"

    @staticmethod
    def _yfinance_etf_ticker(full_code: str) -> str:
        """Yahoo: 上证 ``.SS``, 深证 ``.SZ`` (非 OKX)。"""
        n = (full_code or "").split(".")[0]
        s = (full_code or "").upper()
        return f"{n}.SS" if s.endswith(".SH") or n.startswith(("5", "6", "9")) else f"{n}.SZ"

    def _etf_daily_records_from_baostock(
        self, full_code: str, start_date: str, end_date: str, bs: Any,
    ) -> list[dict]:
        s = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
        e = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
        try:
            df = bs.query_history_k_data(
                self._to_baostock_code(full_code), s, e, "d", "3",
            )
        except Exception as ex:  # noqa: BLE001
            logger.debug("ETF %s baostock: %s", full_code, ex)
            return []
        if df is None or df.empty:
            return []
        out = pd.DataFrame(
            {
                "日期": pd.to_datetime(df["date"], errors="coerce"),
                "开盘": pd.to_numeric(df["open"], errors="coerce"),
                "收盘": pd.to_numeric(df["close"], errors="coerce"),
                "最高": pd.to_numeric(df["high"], errors="coerce"),
                "最低": pd.to_numeric(df["low"], errors="coerce"),
                "成交量": pd.to_numeric(df["volume"], errors="coerce"),
                "成交额": pd.to_numeric(df.get("amount"), errors="coerce"),
            },
        )
        return self._map_etf_daily(out, full_code)

    def _etf_daily_records_from_tushare(
        self, full_code: str, start_date: str, end_date: str, ts: Any,
    ) -> list[dict]:
        """Tushare: 优先 ``fund_daily``(场内基金/ETF 专用); 无数据时回退股票 ``daily``。"""
        if not ts or not getattr(ts, "available", True):
            return []
        code = self._tushare_ts_code(full_code)

        def _from_df(df: Any) -> list[dict]:
            if df is None or df.empty:
                return []
            out = pd.DataFrame(
                {
                    "日期": pd.to_datetime(
                        df["trade_date"].astype(str), format="%Y%m%d", errors="coerce",
                    ),
                    "开盘": pd.to_numeric(df["open"], errors="coerce"),
                    "收盘": pd.to_numeric(df["close"], errors="coerce"),
                    "最高": pd.to_numeric(df["high"], errors="coerce"),
                    "最低": pd.to_numeric(df["low"], errors="coerce"),
                    "成交量": pd.to_numeric(df.get("vol"), errors="coerce"),
                    "成交额": pd.to_numeric(df.get("amount"), errors="coerce"),
                },
            )
            return self._map_etf_daily(out, full_code)

        try:
            df = ts.query_fund_daily(
                ts_code=code, start_date=start_date, end_date=end_date,
            )
        except Exception as ex:  # noqa: BLE001
            logger.debug("ETF %s tushare fund_daily: %s", full_code, ex)
            df = None
        rec = _from_df(df)
        if rec:
            return rec
        try:
            df2 = ts.query_daily(
                ts_code=code, start_date=start_date, end_date=end_date,
            )
        except Exception as ex:  # noqa: BLE001
            logger.debug("ETF %s tushare daily(回退): %s", full_code, ex)
            return []
        return _from_df(df2)

    def _etf_daily_records_from_akshare_em(
        self, full_code: str, start_date: str, end_date: str,
    ) -> list[dict]:
        """东财日 K, requests 直拉 (与 kline 指纹通道不同, 作补充)。"""
        n = (full_code or "").split(".")[0]
        sym = f"sh{n}" if (full_code or "").upper().endswith(".SH") else f"sz{n}"
        try:
            df = self._call_ak(
                "fund_etf_hist_em",
                symbol=sym, period="日k", start_date=start_date, end_date=end_date, adjust="",
            )
        except Exception as ex:  # noqa: BLE001
            logger.debug("ETF %s fund_etf_hist_em: %s", full_code, ex)
            return []
        if df is None or df.empty:
            return []
        if "日期" not in df.columns:
            return []
        return self._map_etf_daily(df, full_code)

    @staticmethod
    def _etf_daily_records_from_yfinance(
        full_code: str, start_date: str, end_date: str,
    ) -> list[dict]:
        try:
            import yfinance as yf
        except ImportError:
            return []
        s = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
        e = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
        tkr = AkshareFinancialSync._yfinance_etf_ticker(full_code)
        try:
            h = yf.Ticker(tkr).history(start=s, end=e, auto_adjust=False)
        except Exception as ex:  # noqa: BLE001
            logger.debug("ETF %s yfinance %s: %s", full_code, tkr, ex)
            return []
        if h is None or h.empty:
            return []
        h = h.reset_index()
        date_col = "Date" if "Date" in h.columns else h.columns[0]
        out = pd.DataFrame(
            {
                "日期": h[date_col],
                "开盘": h["Open"],
                "最高": h["High"],
                "最低": h["Low"],
                "收盘": h["Close"],
                "成交量": h.get("Volume"),
                "成交额": None,
            },
        )
        return AkshareFinancialSync._map_etf_daily(out, full_code)

    @staticmethod
    def _etf_date_extrema_map(
        which: str,
    ) -> dict[str, str]:
        """``code -> 最早/晚 交易日 YYYYMMDD`` (``which``= ``min`` / ``max``)。"""
        if which == "min":
            sql = text("SELECT code, MIN(trade_date) AS v FROM etf_daily GROUP BY code")
        else:
            sql = text("SELECT code, MAX(trade_date) AS v FROM etf_daily GROUP BY code")
        with get_session(readonly=True) as session:
            rows = session.execute(sql).fetchall()
        out: dict[str, str] = {}
        for code, v in rows:
            if code is None or v is None:
                continue
            if hasattr(v, "strftime"):
                out[str(code)] = v.strftime("%Y%m%d")
            else:
                s = str(v)[:10].replace("-", "")
                if len(s) >= 8:
                    out[str(code)] = s[:8]
        return out

    @staticmethod
    def _etf_max_trade_date_map() -> dict[str, str]:
        """``code -> 最后交易日 YYYYMMDD`` (仅 ``etf_daily`` 中已有行的标的)。"""
        return AkshareFinancialSync._etf_date_extrema_map("max")

    @staticmethod
    def _etf_min_trade_date_map() -> dict[str, str]:
        """``code -> 最早交易日 YYYYMMDD`` (用于判断是否要向下补历史)。"""
        return AkshareFinancialSync._etf_date_extrema_map("min")

    @staticmethod
    def _per_code_floor(
        global_start: str,
        establish: Any,
        earliest_ymd_in_db: str | None = None,
    ) -> str:
        """单标的有效地板: ``max(用户地板, 成立日)``; 可带 ``etf_daily`` 中最早日纠偏.

        若 **库内已有 K 的最早日** 仍 **早于** ``max(用户, 成立)`` 算出的地板, 则成立日/字段
        与行情矛盾 (常见: ``establish`` 被填成晚于真实上市), **只采用用户 ``global_start``**,
        否则会出现 ``first_d <= floor`` 误判、不再向下补, ``COUNT(*)`` 长期不变.
        """
        if not global_start or len(global_start) < 8:
            return global_start
        try:
            gs = int(global_start[:8])
        except ValueError:
            return global_start
        if establish is None:
            return global_start
        ed: int | None = None
        try:
            if hasattr(establish, "strftime"):
                ed = int(establish.strftime("%Y%m%d"))
            else:
                s = str(establish)[:10].replace("-", "")
                if len(s) >= 8:
                    ed = int(s[:8])
        except (TypeError, ValueError):
            return global_start
        if ed is None:
            return global_start
        raw = int(str(max(gs, ed)))
        if (
            earliest_ymd_in_db
            and len(earliest_ymd_in_db) >= 8
        ):
            try:
                m_ymd = int(earliest_ymd_in_db[:8])
                if m_ymd < raw:
                    return global_start
            except ValueError:
                pass
        return str(raw)

    @staticmethod
    def _etf_work_segments(
        full_code: str,
        floor_start: str,
        end_date: str,
        max_map: dict[str, str],
        min_map: dict[str, str],
        resume: bool,
    ) -> list[tuple[str, str]]:
        """在 ``resume`` 下, 只返回**缺失**日期区间, 避免 ``[地板, 今日]`` 整段与库内重叠 → 全变 UPDATE.

        无库行: ``[(floor, end)]`` 全量. 有库行:

        - 库内最早日 **晚于** 有效地板: 先向下补 ``(地板, 最早交易日-1 自然日)``.
        - 库内末日 **早于** 本次 ``end_date``: 再续 ``(末交易日+1, end)`` (与旧续传一致).

        两区间不重叠, 多落在 ``INSERT``; 已有日不会再被同轮请求. 无缺口则 ``[]``."""
        if not resume:
            return [(floor_start, end_date)]
        last = max_map.get(full_code)
        if not last:
            return [(floor_start, end_date)]
        end_s = (end_date[:8] if len(end_date) >= 8 else end_date).ljust(8, "0")
        fl_s = (floor_start[:8] if len(floor_start) >= 8 else floor_start).ljust(8, "0")
        try:
            floor_d = datetime.strptime(fl_s, "%Y%m%d").date()
            end_d = datetime.strptime(end_s, "%Y%m%d").date()
            last_d = datetime.strptime(last[:8], "%Y%m%d").date()
        except ValueError:
            return [(floor_start, end_date)]
        first = min_map.get(full_code) or last
        segments: list[tuple[str, str]] = []
        try:
            first_d = datetime.strptime(first[:8], "%Y%m%d").date()
        except ValueError:
            first_d = floor_d
        if first_d > floor_d:
            back_end_d = first_d - timedelta(days=1)
            if back_end_d >= floor_d:
                segments.append((fl_s, back_end_d.strftime("%Y%m%d")))
        nxt_d = last_d + timedelta(days=1)
        if nxt_d <= end_d:
            nxt_s = nxt_d.strftime("%Y%m%d")
            eff = nxt_s if nxt_s >= fl_s else fl_s
            if eff <= end_s:
                segments.append((eff, end_s))
        return segments

    def sync_etf_daily(
        self,
        start_date: str = "20160101",
        *,
        resume: bool = True,
        kline_source: str = "eastmoney",
        sina_only: bool = False,
        stall_no_rows_sec: float = 60.0,
        use_download_progress: bool = True,
    ) -> int:
        """为 ``etf_info`` 中的每只 ETF 采集日线, 新行 INSERT 到 ``etf_daily`` (主键已存在则跳过, 不覆盖, 段级 commit).

        多数据源: 对 **队首段** 全链路透传(级联+新浪/东财 page/tushare/baostock/yfinance) 直至首段
        产数并锁定 ``主源``; **后续各段** 只走该主源, 本段无数据时对该段再全链路透传. ``sina_only`` 为 True
        时只新浪.

        Args:
            start_date: 全量/新标的 的起始日期 YYYYMMDD (地板).
            resume: 为 True 时 (默认), 有效地板为
                ``max(start_date, etf_info.establish_date)`` (含与库内 ``MIN`` 纠偏);
                对每只标的**按缺口**拉取: 向下仅 ``(地板..MIN-1)``、向后续 ``(MAX+1..今日)``,
                不整段 ``[地板, 今日]`` 重下 (避免与已有日重叠, 以新增为主非纯 UPDATE).
            kline_source: ``eastmoney`` / ``tencent`` / ``auto`` (东财不可达时腾讯, 由 kline 模块探测),
                在 ``sina_only`` 时忽略.
            sina_only: 仅走新浪日 K, 用于东财+腾讯均不顺时的兜底.
            stall_no_rows_sec: 在仍有待拉标的时, 若此时间内 **无任何新 K 线** 落库, 则抛出
                :class:`EtfDailyStallError` (0 表示关闭).
            use_download_progress: 为 True 时 写入 :class:`~src.data.models.EtfDownloadProgress`,
                并 **每段** 落库后 ``commit`` (断点可续, 他连接可见 ``COUNT``).
        """
        from src.data import kline_bulk_sync as kbs
        from src.data.etf_download_progress import (
            ETF_SYNC_TYPE_DAILY,
            EtfDownloadProgressDAO,
        )

        end_date = datetime.now().strftime("%Y%m%d")
        if sina_only:
            kline_label = "sina"
        else:
            kline_label = kline_source
        logger.info(
            "开始同步 ETF 日线 (地板=%s ~ %s, resume=%s, kline=%s, stall_no_rows=%s)...",
            start_date, end_date, resume, kline_label,
            stall_no_rows_sec,
        )

        if not sina_only:
            kbs.reset_em_cache()
            if kline_source in ("tencent", "auto"):
                kbs.reset_qq_session()
            em_rate = max(1.5, float(_CFG.eastmoney_rate) * 8)
            em_burst = max(4, int(_CFG.eastmoney_burst))
            kbs._get_em_limiter(rate=em_rate, burst=em_burst)
            if kline_source not in ("eastmoney", "tencent", "auto"):
                raise ValueError("kline_source 须为 eastmoney / tencent / auto")
            kbs._active_source = kline_source

        with get_session(readonly=True) as session:
            rows = session.query(ETFInfo.code, ETFInfo.establish_date).all()
        etf_codes = [r[0] for r in rows]
        establish_by: dict[str, Any] = {r[0]: r[1] for r in rows}

        if not etf_codes:
            logger.warning("etf_info 表为空, 请先执行 sync_etf_list")
            return 0

        max_map = self._etf_max_trade_date_map() if resume else {}
        min_map = self._etf_min_trade_date_map() if resume else {}
        n_skip_current = 0
        if resume:
            for c in etf_codes:
                if c not in max_map:
                    continue
                pcf = self._per_code_floor(
                    start_date, establish_by.get(c), min_map.get(c),
                )
                if not self._etf_work_segments(
                    c, pcf, end_date, max_map, min_map, True,
                ):
                    n_skip_current += 1
            logger.info(
                "ETF 日线续传: 库中已有 K 线 %d 只, 其中已追至最新跳过 %d 只",
                len(max_map),
                n_skip_current,
            )

        work: list[tuple[str, str, str]] = []
        for full_code in etf_codes:
            pcf = self._per_code_floor(
                start_date, establish_by.get(full_code), min_map.get(full_code),
            )
            for seg_start, seg_end in self._etf_work_segments(
                full_code, pcf, end_date, max_map, min_map, resume,
            ):
                work.append((full_code, seg_start, seg_end))
        n_work = len(work)
        if n_work == 0 and etf_codes:
            logger.warning(
                "本次待拉 ETF=0 只 (全部判定为已追上日末 / 无需补). "
                "若 ``COUNT(*)`` 仍偏少, 多为 etf_info.establish_date 高于真实上市日导致 "
                "旧逻辑误判; 已按库内最早 K 纠偏. 可再试或 ``--no-resume`` 强拉.",
            )
        t_loop = time.monotonic()
        last_data_mono: float | None = None
        total = 0
        etf_segments_wrote: int = 0
        failed = 0
        skipped = n_skip_current
        seg_needed = Counter(c for c, _, _ in work) if work else Counter()
        seg_done: dict[str, int] = {}
        per_code_nrows: dict[str, int] = defaultdict(int)
        code_abandon: set[str] = set()

        def _stall_check() -> None:
            if not stall_no_rows_sec or n_work == 0:
                return
            now = time.monotonic()
            if last_data_mono is not None and (now - last_data_mono) > stall_no_rows_sec:
                raise EtfDailyStallError(
                    f"{stall_no_rows_sec:.0f}s 内无新 K 线落库, 可切换 kline/新浪",
                )
            if last_data_mono is None and (now - t_loop) > stall_no_rows_sec:
                raise EtfDailyStallError(
                    f"启动 {stall_no_rows_sec:.0f}s 后仍无新 K 线, 可切换 kline/新浪",
                )

        def _bulk_insert_etf_daily(sess, rows: list[dict]) -> int:
            """``ON CONFLICT DO NOTHING``: 已存在的 ``(code, trade_date)`` 跳过, 不覆写. 返回净 INSERT 行数."""
            if not rows:
                return 0
            n_new = 0
            for i in range(0, len(rows), 1500):
                chunk = rows[i: i + 1500]
                stmt = insert(ETFDaily).values(chunk)
                stmt = stmt.on_conflict_do_nothing(
                    index_elements=["code", "trade_date"],
                )
                r = sess.execute(stmt)
                n_new += r.rowcount or 0
            return n_new

        # baostock 延迟到首次兜底再 login, 避免启动即连网/ stderr 里 pytdx 类 “10057” 噪声
        # SDK 的 socket 失败时会对 stdout 直接 print 中文, 用 redirect 吃掉; 登录失败只试一次, 避免每段重复连
        bs_col: Any = None
        baostock_gave_up: bool = False

        def _ensure_baostock() -> Any:
            nonlocal bs_col, baostock_gave_up
            if baostock_gave_up:
                return None
            if bs_col is not None:
                return bs_col
            try:
                from src.datacollect.collectors.baostock_collector import (
                    BaostockCollector,
                )
                c = BaostockCollector()
                with redirect_stdout(StringIO()):
                    c._ensure_login()
                bs_col = c
                return c
            except Exception as e:  # noqa: BLE001
                baostock_gave_up = True
                logger.info(
                    "baostock 不可用 (本进程内不再作 ETF 日线兜底), 原因: %s",
                    e,
                )
                return None

        ts_col: Any = None
        try:
            from src.datacollect.collectors.tushare_collector import TushareCollector

            ts_col = TushareCollector()
            if not getattr(ts_col, "available", False):
                ts_col = None
        except Exception as e:  # noqa: BLE001
            logger.debug("tushare 未启用: %s", e)

        p_start = _ymd8_to_date(start_date)
        p_end = _ymd8_to_date(end_date)
        ucodes = list(dict.fromkeys(c for c, _, _ in work))
        if use_download_progress and ucodes:
            EtfDownloadProgressDAO.init_progress(
                ucodes, ETF_SYNC_TYPE_DAILY, p_start, p_end,
            )

        def _maybe_finalize_etf_row(code: str) -> None:
            if not use_download_progress:
                return
            if seg_done.get(code, 0) < seg_needed.get(code, 0):
                return
            nsum = int(per_code_nrows.get(code, 0))
            if nsum > 0:
                EtfDownloadProgressDAO.mark_completed(
                    code, ETF_SYNC_TYPE_DAILY, nsum,
                )
            else:
                EtfDownloadProgressDAO.mark_failed(
                    code, ETF_SYNC_TYPE_DAILY, "各段均无数据",
                )

        # 首条待拉段全链路试到成功 = 主源, 之后各段主源直拉, 本段无数据再全链路透传
        resolved_source: str | None = None

        def _emit_etf_cli(msg: str) -> None:
            """同步写 stdout+stderr+logger, 避免某些终端只重定向/缓冲其一, 导致看不到数据源。"""
            try:
                print(msg, flush=True)
            except OSError:
                pass
            try:
                print(msg, file=sys.stderr, flush=True)
            except OSError:
                pass
            logger.info("%s", msg)

        def _segment_fetch_full(
            full_code: str, seg_s: str, seg_e: str,
        ) -> tuple[list[dict], str | None]:
            r, src = kbs.fetch_etf_daily_cascade(
                full_code, seg_s, seg_e, kline_prefer=kline_source,
            )
            if r:
                return r, src
            # 无东财/腾讯 K 后: 新浪 → Tushare(fund_daily 场内基金专用) → 东财 page 直拉 → …
            fb: list[tuple[str, Any]] = [
                (
                    "sina",
                    lambda: self._etf_daily_records_from_sina(
                        full_code, seg_s, seg_e,
                    ),
                ),
            ]
            if ts_col is not None:
                fb.append((
                    "tushare",
                    lambda: self._etf_daily_records_from_tushare(
                        full_code, seg_s, seg_e, ts_col,
                    ),
                ))
            fb.append(
                (
                    "akshare_fund_etf_hist_em",
                    lambda: self._etf_daily_records_from_akshare_em(
                        full_code, seg_s, seg_e,
                    ),
                ),
            )

            def _bs1() -> list[dict]:
                bc2 = _ensure_baostock()
                if bc2 is None:
                    return []
                with redirect_stdout(StringIO()):
                    return (
                        self._etf_daily_records_from_baostock(
                            full_code, seg_s, seg_e, bc2,
                        )
                        or []
                    )

            fb.append(("baostock", _bs1))
            fb.append((
                "yfinance",
                lambda: self._etf_daily_records_from_yfinance(
                    full_code, seg_s, seg_e,
                ),
            ))
            for name, fn in fb:
                try:
                    rec = fn() or []
                except Exception as exc:  # noqa: BLE001
                    logger.debug("ETF %s %s: %s", full_code, name, exc)
                    rec = []
                if rec:
                    return rec, name
            return [], None

        def _segment_fetch_sticky(tag: str, full_code: str, seg_s: str, seg_e: str) -> list[dict]:
            try:
                if tag == "kline_tencent":
                    return kbs._qq_fetch_etf(full_code, seg_s, seg_e) or []
                if tag == "kline_eastmoney":
                    return kbs._em_fetch_etf(full_code, seg_s, seg_e) or []
                if tag == "sina":
                    return self._etf_daily_records_from_sina(
                        full_code, seg_s, seg_e,
                    ) or []
                if tag == "akshare_fund_etf_hist_em":
                    return self._etf_daily_records_from_akshare_em(
                        full_code, seg_s, seg_e,
                    ) or []
                if tag == "tushare":
                    if ts_col is None:
                        return []
                    return self._etf_daily_records_from_tushare(
                        full_code, seg_s, seg_e, ts_col,
                    ) or []
                if tag == "baostock":
                    bc2 = _ensure_baostock()
                    if bc2 is None:
                        return []
                    with redirect_stdout(StringIO()):
                        return (
                            self._etf_daily_records_from_baostock(
                                full_code, seg_s, seg_e, bc2,
                            )
                            or []
                        )
                if tag == "yfinance":
                    return self._etf_daily_records_from_yfinance(
                        full_code, seg_s, seg_e,
                    ) or []
            except Exception as exc:  # noqa: BLE001
                logger.debug("ETF 主源 %s %s: %s", full_code, tag, exc)
            return []

        try:
            for wi, (full_code, seg_start, seg_end) in enumerate(work):
                if full_code in code_abandon:
                    continue
                _stall_check()
                logger.info(
                    "ETF 日线: 拉取中 %d/%d %s … (段 %s ~ %s)",
                    wi + 1, n_work, full_code, seg_start, seg_end,
                )
                if sina_only:
                    _phase = "仅新浪"
                elif resolved_source and wi > 0:
                    _phase = f"粘性主源(先试)={resolved_source}"
                else:
                    _phase = "全链路透传(级联+兜底)" + (
                        " · 定主源" if wi == 0 and not resolved_source else ""
                    )
                _emit_etf_cli(
                    f"【etf_daily】进段 {wi + 1}/{n_work} {full_code} 段{seg_start}~{seg_end} | 模式: {_phase}",
                )
                if use_download_progress:
                    EtfDownloadProgressDAO.update_progress(
                        full_code, ETF_SYNC_TYPE_DAILY, "running",
                        actual_start_date=_ymd8_to_date(seg_start),
                        actual_end_date=_ymd8_to_date(seg_end),
                    )
                records: list[dict] = []
                data_src: str | None = None
                if sina_only:
                    try:
                        records = self._etf_daily_records_from_sina(
                            full_code, seg_start, seg_end,
                        )
                    except Exception as exc:  # noqa: BLE001 单标的容错
                        logger.warning("ETF %s 新浪日 K 失败: %s", full_code, exc)
                    if records:
                        data_src = "sina"
                else:
                    if resolved_source and wi > 0:
                        records = _segment_fetch_sticky(
                            resolved_source, full_code, seg_start, seg_end,
                        )
                        data_src = resolved_source
                        if not records:
                            records, data_src = _segment_fetch_full(
                                full_code, seg_start, seg_end,
                            )
                    else:
                        records, data_src = _segment_fetch_full(
                            full_code, seg_start, seg_end,
                        )
                        if (
                            records
                            and data_src
                            and wi == 0
                            and not resolved_source
                        ):
                            resolved_source = data_src
                            logger.info(
                                "首段已打通, 本任务主源=%s, 余下各段将优先此路 (无数据时该段全链路重试)",
                                data_src,
                            )
                            _emit_etf_cli(
                                f"【etf_daily】本任务主源已锁定: {data_src!s} (余下各段优先进此路)",
                            )
                if not records:
                    failed += 1
                    seg_done[full_code] = seg_done.get(full_code, 0) + 1
                    _maybe_finalize_etf_row(full_code)
                    continue
                nrows_fetch = len(records)
                _emit_etf_cli(
                    f"【ETF数据源】本段已拉到数据, 将写入 etf_daily | 源={data_src!s} | "
                    f"{full_code!s} 段{seg_start!s}~{seg_end!s} | 行数(拉取)={nrows_fetch}",
                )
                try:
                    # 单段单事务: K 线落库(冲突跳过) + 进度行, get_session 退出时一次 commit
                    with get_session() as session:
                        n_ins = _bulk_insert_etf_daily(session, records)
                        new_count_code = per_code_nrows.get(full_code, 0) + n_ins
                        if use_download_progress:
                            EtfDownloadProgressDAO.update_progress(
                                full_code, ETF_SYNC_TYPE_DAILY, "running",
                                records_count=new_count_code,
                                actual_start_date=_ymd8_to_date(seg_start),
                                actual_end_date=_ymd8_to_date(seg_end),
                                session=session,
                            )
                except Exception as exc:  # noqa: BLE001
                    logger.error("ETF %s 段 %s~%s 写入 etf_daily 失败: %s", full_code, seg_start, seg_end, exc)
                    failed += 1
                    if use_download_progress:
                        EtfDownloadProgressDAO.mark_failed(
                            full_code, ETF_SYNC_TYPE_DAILY, str(exc)[:500],
                        )
                        code_abandon.add(full_code)
                    continue
                total += n_ins
                per_code_nrows[full_code] = new_count_code
                seg_done[full_code] = seg_done.get(full_code, 0) + 1
                etf_segments_wrote += 1
                last_data_mono = time.monotonic()
                if sina_only:
                    main_src = "sina_only(无多源锁)"
                elif resolved_source:
                    main_src = f"{resolved_source!s}"
                else:
                    main_src = "(主源未锁, 全链路探针至首段成功)"
                _emit_etf_cli(
                    f"【etf_daily】本段已 commit | 本段源={data_src!s} | 主源(锁)={main_src} | "
                    f"{full_code!s} 段{seg_start!s}~{seg_end!s} | "
                    f"拉取={nrows_fetch} 新插={n_ins} 跳过(已存在)={max(0, nrows_fetch - n_ins)}",
                )
                if use_download_progress:
                    _maybe_finalize_etf_row(full_code)
                wall = time.monotonic() - t_loop
                rps = total / wall if wall > 0 else 0.0
                logger.info(
                    "ETF 日线: %d/%d %s, 新插 %d 行(拉取 %d, 去重后), 累计新插 %d, ~%.0f 行/秒, 段已落库, 源=%s, 跳最新 %d",
                    wi + 1, n_work, full_code, n_ins, nrows_fetch, total, rps, data_src or "?", skipped,
                )
        finally:
            if bs_col is not None:
                try:
                    bs_col.close()
                except Exception:  # noqa: BLE001
                    pass

        if n_work > 0 and total == 0 and etf_segments_wrote == 0:
            msg = (
                f"有 {n_work} 段待续拉, 但无任一段拉取到数据 (可换源/检查网络/代理后重试)"
            )
            logger.error("%s", msg)
            raise EtfDailyNoDataError(msg)
        if n_work > 0 and total == 0 and etf_segments_wrote > 0:
            logger.info(
                "ETF 日线: 本轮净插入 0 行(拉取到数据但 (code, trade_date) 均在库, 已 ON CONFLICT 跳过), "
                "不视为错误",
            )
        logger.info(
            "ETF 日线同步完成: 新插入 %d 行 (已存在主键已跳过, 不覆盖), "
            "失败段约 %d, 跳过(已最新) %d; SELECT count(*) 仅随净插入变",
            total, failed, skipped,
        )
        self.enrich_etf_establish_date_from_daily()
        return total

    @staticmethod
    def _map_etf_daily(df: pd.DataFrame, code: str) -> list[dict]:
        """将 akshare fund_etf_hist_em 返回的 DataFrame 映射为 ETFDaily 记录。"""
        col_map = {
            "日期": "trade_date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
        }
        records: list[dict] = []
        for _, row in df.iterrows():
            trade_date = _safe_date(row.get("日期"))
            if trade_date is None:
                continue
            rec: dict[str, Any] = {"code": code, "trade_date": trade_date}
            for cn_col, db_col in col_map.items():
                if db_col == "trade_date":
                    continue
                if db_col == "volume":
                    val = row.get(cn_col)
                    rec[db_col] = int(val) if val is not None and not pd.isna(val) else None
                else:
                    rec[db_col] = _safe_float(row.get(cn_col))
            records.append(rec)
        return records

    # ------------------------------------------------------------------
    # A13: 财务报表
    # ------------------------------------------------------------------

    def sync_financial_report(
        self,
        stock_codes: list[str] | None = None,
        report_types: list[str] | None = None,
    ) -> int:
        """通过 akshare stock_financial_abstract_ths 采集财务摘要, upsert 到 stock_financial_report。

        Args:
            stock_codes: 股票代码列表 (6位纯数字或带后缀)。为 None 时从 stocks 表读取全部。
            report_types: 保留参数, 当前实现使用统一的财务摘要接口。
        """
        codes = self._resolve_stock_codes(stock_codes)
        if not codes:
            logger.warning("无可用股票代码")
            return 0

        logger.info("开始同步财务报表, 共 %d 只股票...", len(codes))
        total = 0
        failed = 0

        for i, code in enumerate(codes):
            symbol = code.split(".")[0]
            try:
                df = self._call_ak(
                    "stock_financial_abstract_ths",
                    symbol=symbol,
                    indicator="按报告期",
                )
            except Exception as e:
                logger.warning("股票 %s 财务摘要获取失败: %s", code, e)
                failed += 1
                continue

            if df is None or df.empty:
                continue

            records = self._map_financial_report(df, symbol)
            if not records:
                continue

            with get_session() as session:
                for rec in records:
                    stmt = insert(StockFinancialReport).values(**rec)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["code", "report_type", "report_period"],
                        set_={
                            k: v for k, v in rec.items()
                            if k not in ("code", "report_type", "report_period", "id")
                        },
                    )
                    session.execute(stmt)
                total += len(records)

            if (i + 1) % 50 == 0:
                logger.info("财务报表进度: %d/%d (累计 %d 条)", i + 1, len(codes), total)

        logger.info("财务报表同步完成: %d 条, 失败 %d 只", total, failed)
        return total

    @staticmethod
    def _map_financial_report(df: pd.DataFrame, code: str) -> list[dict]:
        """将 stock_financial_abstract_ths 返回数据映射到 StockFinancialReport 字段。"""
        col_map = {
            "营业总收入": "total_revenue",
            "营业利润": "operating_profit",
            "净利润": "net_profit",
            "总资产": "total_assets",
            "总负债": "total_liabilities",
            "股东权益": "total_equity",
            "经营活动产生的现金流量净额": "operating_cash_flow",
            "毛利率": "gross_margin",
            "净利率": "net_margin",
            "净资产收益率": "roe",
            "资产负债率": "debt_ratio",
            "流动比率": "current_ratio",
            "速动比率": "quick_ratio",
        }

        records: list[dict] = []
        for _, row in df.iterrows():
            report_date_raw = row.get("报告期") or row.get("日期")
            report_date = _safe_date(report_date_raw)
            if report_date is None:
                continue

            period_str = report_date.strftime("%Y%m%d")
            rec: dict[str, Any] = {
                "code": code,
                "report_type": "combined",
                "report_period": period_str,
                "report_date": report_date,
                "updated_at": datetime.now(),
            }
            for cn_col, db_col in col_map.items():
                if cn_col in df.columns:
                    rec[db_col] = _safe_float(row.get(cn_col))
            records.append(rec)
        return records

    # ------------------------------------------------------------------
    # A14: 财务分析指标
    # ------------------------------------------------------------------

    def sync_financial_indicator(
        self,
        stock_codes: list[str] | None = None,
        start_year: str = "2023",
    ) -> int:
        """通过 akshare stock_financial_analysis_indicator 采集财务指标, upsert 到 stock_financial_indicator。

        Args:
            stock_codes: 股票代码列表。为 None 时从 stocks 表读取全部。
            start_year: 起始年份
        """
        codes = self._resolve_stock_codes(stock_codes)
        if not codes:
            logger.warning("无可用股票代码")
            return 0

        logger.info("开始同步财务指标, 共 %d 只股票...", len(codes))
        total = 0
        failed = 0

        for i, code in enumerate(codes):
            symbol = code.split(".")[0]
            try:
                df = self._call_ak(
                    "stock_financial_analysis_indicator",
                    symbol=symbol,
                    start_year=start_year,
                )
            except Exception as e:
                logger.warning("股票 %s 财务指标获取失败: %s", code, e)
                failed += 1
                continue

            if df is None or df.empty:
                continue

            records = self._map_financial_indicator(df, symbol)
            if not records:
                continue

            with get_session() as session:
                for rec in records:
                    stmt = insert(StockFinancialIndicator).values(**rec)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["code", "report_date"],
                        set_={
                            k: v for k, v in rec.items()
                            if k not in ("code", "report_date", "id")
                        },
                    )
                    session.execute(stmt)
                total += len(records)

            if (i + 1) % 50 == 0:
                logger.info("财务指标进度: %d/%d (累计 %d 条)", i + 1, len(codes), total)

        logger.info("财务指标同步完成: %d 条, 失败 %d 只", total, failed)
        return total

    @staticmethod
    def _map_financial_indicator(df: pd.DataFrame, code: str) -> list[dict]:
        """将 stock_financial_analysis_indicator 返回数据映射到 StockFinancialIndicator 字段。"""
        col_map = {
            "基本每股收益": "eps_basic",
            "每股净资产": "bps",
            "加权净资产收益率": "roe_weighted",
            "摊薄净资产收益率": "roe_diluted",
            "资产负债率": "debt_asset_ratio",
            "流动比率": "current_ratio",
            "速动比率": "quick_ratio",
            "营业总收入同比增长率": "revenue_growth",
            "净利润同比增长率": "profit_growth",
            "每股经营现金流量": "cfps",
            "每股股利": "dps",
            "毛利率": "gross_profit_margin",
            "净利率": "net_profit_margin",
            "总资产周转率": "total_asset_turnover",
            "存货周转率": "inventory_turnover",
            "应收账款周转率": "receivable_turnover",
        }

        records: list[dict] = []
        for _, row in df.iterrows():
            date_raw = row.get("日期") or row.get("报告期")
            report_date = _safe_date(date_raw)
            if report_date is None:
                continue

            rec: dict[str, Any] = {
                "code": code,
                "report_date": report_date,
                "updated_at": datetime.now(),
            }
            for cn_col, db_col in col_map.items():
                if cn_col in df.columns:
                    rec[db_col] = _safe_float(row.get(cn_col))
            records.append(rec)
        return records

    # ==================================================================
    # 批量接口 (按报告期, 一次拉全市场, 比逐股快 ~100x)
    # ==================================================================

    def sync_financial_report_batch(self, periods: list[str] | None = None) -> int:
        """通过东方财富批量接口采集全市场财务报表 (利润表+资产负债表+现金流量表)。

        一次调用返回全部 ~5000+ 股票的某一报告期数据, 比逐股快约 100 倍。

        Args:
            periods: 报告期列表, 如 ["20240331","20240630","20240930","20241231"]。
                     为 None 时默认取最近 4 个季度。
        """
        import akshare as ak

        if periods is None:
            from datetime import date
            y = date.today().year
            periods = [f"{y-1}0331", f"{y-1}0630", f"{y-1}0930", f"{y-1}1231"]

        total = 0
        for period in periods:
            period_date = _safe_date(period)
            if period_date is None:
                logger.warning("无效报告期: %s", period)
                continue

            report_parts: dict[str, dict[str, str]] = {
                "income": {
                    "func": "stock_lrb_em",
                    "map": {
                        "净利润": "net_profit",
                        "营业总收入": "total_revenue",
                        "营业利润": "operating_profit",
                        "营业总支出-营业支出": "operating_cost",
                        "营业总支出-销售费用": "selling_expenses",
                        "营业总支出-管理费用": "admin_expenses",
                        "营业总支出-财务费用": "financial_expenses",
                    },
                },
                "balance": {
                    "func": "stock_zcfz_em",
                    "map": {
                        "资产-货币资金": "cash_and_equivalents",
                        "资产-应收账款": "accounts_receivable",
                        "资产-存货": "inventory",
                        "资产-总资产": "total_assets",
                        "负债-总负债": "total_liabilities",
                    },
                },
                "cashflow": {
                    "func": "stock_xjll_em",
                    "map": {
                        "经营现金流-经营现金流量净额": "operating_cash_flow",
                        "投资现金流-投资现金流量净额": "investing_cash_flow",
                        "融资现金流-融资现金流量净额": "financing_cash_flow",
                        "现金净增加额-现金净增加额": "net_cash_flow",
                    },
                },
            }

            merged: dict[str, dict[str, Any]] = {}  # keyed by stock code

            for part_name, part_cfg in report_parts.items():
                func_name = part_cfg["func"]
                col_map = part_cfg["map"]
                try:
                    self._limiter.acquire()
                    fn = getattr(ak, func_name)
                    df = fn(date=period)
                except Exception as e:
                    logger.warning("%s(%s) 获取失败: %s", func_name, period, e)
                    continue

                if df is None or df.empty:
                    logger.warning("%s(%s) 返回空数据", func_name, period)
                    continue

                logger.info("%s(%s): %d rows", func_name, period, len(df))

                for _, row in df.iterrows():
                    code = str(row.get("股票代码", "")).strip()
                    if not code or len(code) != 6:
                        continue
                    if code not in merged:
                        announce = _safe_date(row.get("公告日期"))
                        merged[code] = {
                            "code": code,
                            "report_type": "combined",
                            "report_period": period,
                            "report_date": announce or period_date,
                            "updated_at": datetime.now(),
                        }
                    rec = merged[code]
                    for cn_col, db_col in col_map.items():
                        if cn_col in df.columns:
                            rec[db_col] = _safe_float(row.get(cn_col))

            if not merged:
                logger.warning("报告期 %s 无数据", period)
                continue

            records = list(merged.values())
            self._batch_upsert_reports(records)
            total += len(records)
            logger.info("报告期 %s 入库 %d 条 (合并三表)", period, len(records))

        logger.info("批量财务报表同步完成, 共 %d 条", total)
        return total

    def sync_financial_indicator_batch(self, periods: list[str] | None = None) -> int:
        """通过东方财富 stock_yjbb_em 批量采集全市场业绩指标。

        Args:
            periods: 报告期列表。为 None 时默认取最近 4 个季度。
        """
        import akshare as ak

        if periods is None:
            from datetime import date
            y = date.today().year
            periods = [f"{y-1}0331", f"{y-1}0630", f"{y-1}0930", f"{y-1}1231"]

        col_map = {
            "每股收益": "eps_basic",
            "每股净资产": "bps",
            "净资产收益率": "roe_weighted",
            "每股经营现金流量净额": "cfps",
            "销售毛利率": "gross_profit_margin",
            "营业收入-同比增长": "revenue_growth",
            "净利润-同比增长": "profit_growth",
        }

        total = 0
        for period in periods:
            period_date = _safe_date(period)
            if period_date is None:
                continue
            try:
                self._limiter.acquire()
                df = ak.stock_yjbb_em(date=period)
            except Exception as e:
                logger.warning("stock_yjbb_em(%s) 获取失败: %s", period, e)
                continue

            if df is None or df.empty:
                logger.warning("stock_yjbb_em(%s) 返回空数据", period)
                continue

            logger.info("stock_yjbb_em(%s): %d rows", period, len(df))

            records: list[dict] = []
            for _, row in df.iterrows():
                code = str(row.get("股票代码", "")).strip()
                if not code or len(code) != 6:
                    continue
                announce = _safe_date(row.get("最新公告日期"))
                rec: dict[str, Any] = {
                    "code": code,
                    "report_date": announce or period_date,
                    "updated_at": datetime.now(),
                }
                for cn_col, db_col in col_map.items():
                    if cn_col in df.columns:
                        rec[db_col] = _safe_float(row.get(cn_col))
                records.append(rec)

            if records:
                self._batch_upsert_indicators(records)
                total += len(records)
                logger.info("报告期 %s 指标入库 %d 条", period, len(records))

        logger.info("批量财务指标同步完成, 共 %d 条", total)
        return total

    @staticmethod
    def _batch_upsert_reports(records: list[dict], batch_size: int = 1000) -> None:
        all_keys: set[str] = set()
        for rec in records:
            all_keys.update(rec.keys())
        all_keys.discard("id")
        for rec in records:
            for k in all_keys:
                rec.setdefault(k, None)

        update_keys = [k for k in all_keys if k not in ("code", "report_type", "report_period", "id")]
        with get_session() as session:
            for i in range(0, len(records), batch_size):
                batch = records[i: i + batch_size]
                stmt = insert(StockFinancialReport).values(batch)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["code", "report_type", "report_period"],
                    set_={k: stmt.excluded[k] for k in update_keys},
                )
                session.execute(stmt)

    @staticmethod
    def _batch_upsert_indicators(records: list[dict], batch_size: int = 1000) -> None:
        all_keys: set[str] = set()
        for rec in records:
            all_keys.update(rec.keys())
        all_keys.discard("id")
        for rec in records:
            for k in all_keys:
                rec.setdefault(k, None)

        update_keys = [k for k in all_keys if k not in ("code", "report_date", "id")]
        with get_session() as session:
            for i in range(0, len(records), batch_size):
                batch = records[i: i + batch_size]
                stmt = insert(StockFinancialIndicator).values(batch)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["code", "report_date"],
                    set_={k: stmt.excluded[k] for k in update_keys},
                )
                session.execute(stmt)

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_stock_codes(stock_codes: list[str] | None) -> list[str]:
        """解析股票代码列表: 传入为 None 时从 stocks 表读取全部。"""
        if stock_codes:
            return [c.split(".")[0] if "." in c else c for c in stock_codes]
        with get_session() as session:
            rows = session.query(Stock.code).all()
        return [row[0] for row in rows]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="akshare 财务/ETF 数据采集")
    parser.add_argument(
        "action",
        choices=[
            "etf_list", "etf_daily", "etf_full", "etf_f10",
            "report", "indicator",
            "report_batch", "indicator_batch",
            "all", "all_batch",
        ],
        help="etf_full=列表+F10+日线; etf_f10=仅东财基本概况; _batch=财务批量",
    )
    parser.add_argument(
        "--start-date",
        default=None,
        help="ETF 日线起始日期; 未指定时使用 env DATACOLLECT_ETF_DAILY_START_DATE (续传时作地板等)",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="ETF 日线不从库中 MAX(trade_date) 续传 (覆盖 env DATACOLLECT_ETF_DAILY_RESUME)",
    )
    parser.add_argument(
        "--kline-source",
        choices=["eastmoney", "tencent", "auto"],
        default=None,
        help="未指定则 env DATACOLLECT_ETF_DAILY_KLINE_SOURCE: "
        "eastmoney|tencent|auto",
    )
    parser.add_argument(
        "--sina-only-etf",
        action="store_true",
        help="与 env DATACOLLECT_ETF_DAILY_SINA_ONLY 或关系: 任一为真则仅新浪日K",
    )
    parser.add_argument(
        "--stall-sec",
        type=float,
        default=None,
        help="无新K线停顿秒数; 未指定则 env DATACOLLECT_ETF_DAILY_STALL_SEC; 0=关闭",
    )
    parser.add_argument(
        "--no-etf-progress",
        action="store_true",
        help="不写入 etf_download_progress (覆盖 env DATACOLLECT_ETF_DAILY_USE_PROGRESS)",
    )
    parser.add_argument("--start-year", default="2023", help="财务指标起始年份")
    parser.add_argument("--codes", nargs="*", help="股票代码列表 (仅 report/indicator)")
    parser.add_argument(
        "--periods", nargs="*",
        help="报告期列表 (仅 batch, 如 20240331 20240630 20240930 20241231)",
    )
    args = parser.parse_args()

    from src.common.config import settings

    _dc = settings.datacollect
    _start = (
        args.start_date
        if args.start_date is not None
        else _dc.etf_daily_start_date
    )
    _kline = (
        args.kline_source
        if args.kline_source is not None
        else _dc.etf_daily_kline_source
    )
    _stall = args.stall_sec if args.stall_sec is not None else _dc.etf_daily_stall_sec
    _stall = float(_stall or 0.0)
    _resume = _dc.etf_daily_resume
    if args.no_resume:
        _resume = False
    _sina = bool(_dc.etf_daily_sina_only or args.sina_only_etf)
    _use_progress = _dc.etf_daily_use_progress
    if args.no_etf_progress:
        _use_progress = False

    syncer = AkshareFinancialSync()

    if args.action in ("etf_list", "etf_full"):
        syncer.sync_etf_list()
    if args.action in ("etf_f10", "etf_full"):
        syncer.enrich_etf_info_from_f10_em()
    if args.action in ("etf_daily", "etf_full"):
        try:
            syncer.sync_etf_daily(
                start_date=_start,
                resume=_resume,
                kline_source=_kline,
                sina_only=_sina,
                stall_no_rows_sec=_stall,
                use_download_progress=_use_progress,
            )
        except EtfDailyStallError as exc:
            logger.warning("%s", exc)
            sys.exit(2)
        except EtfDailyNoDataError as exc:
            logger.warning("%s", exc)
            sys.exit(3)
    if args.action == "report":
        syncer.sync_financial_report(stock_codes=args.codes)
    if args.action == "indicator":
        syncer.sync_financial_indicator(
            stock_codes=args.codes, start_year=args.start_year,
        )
    if args.action in ("report_batch", "all_batch"):
        syncer.sync_financial_report_batch(periods=args.periods)
    if args.action in ("indicator_batch", "all_batch"):
        syncer.sync_financial_indicator_batch(periods=args.periods)
