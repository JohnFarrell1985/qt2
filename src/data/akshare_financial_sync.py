"""通过 akshare 采集 ETF / 财务报表 / 财务指标数据

独立于 QMT 的数据补充通道, 使用 akshare 公开接口采集:
- A12: ETF 列表 + ETF 日线行情
- A12b: 东财基金 F10 ``jbgk_{code}.html`` → ``tracking_index`` / ``management_fee`` / ``establish_date`` / ``latest_scale``
- A13: 财务报表 (利润/资产负债/现金流摘要)
- A14: 财务分析指标 (每股/盈利/偿债/成长)

所有 akshare 调用均受 TokenBucketLimiter 限流保护。
"""
from __future__ import annotations

import re
import time
from datetime import datetime
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

_CFG = settings.datacollect


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
        """天天基金「基本概况」页 4 列表格 → 键值对 (东财 F10, 非 akshare 分页接口)。"""
        url = f"https://fundf10.eastmoney.com/jbgk_{num_code.strip()}.html"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        r = requests.get(url, timeout=25, headers=headers)
        r.raise_for_status()
        r.encoding = r.apparent_encoding or "utf-8"
        dfs = pd.read_html(StringIO(r.text))
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
            time.sleep(0.18)
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

    def _fetch_etf_hist_df(
        self, full_code: str, symbol: str, start_date: str, end_date: str,
    ) -> pd.DataFrame | None:
        """东财 ``fund_etf_hist_em`` 失败时尝试新浪 ``fund_etf_hist_sina``。"""
        try:
            df = self._call_ak(
                "fund_etf_hist_em",
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust="qfq",
            )
            if df is not None and not df.empty:
                return df
        except Exception as e:
            logger.debug("ETF %s 东财日线失败, 尝试新浪: %s", full_code, e)

        try:
            self._limiter.acquire()
            import akshare as ak

            df2 = ak.fund_etf_hist_sina(symbol=self._etf_sina_symbol(full_code))
        except Exception as e2:
            logger.warning("ETF %s 新浪日线失败: %s", full_code, e2)
            return None
        if df2 is None or df2.empty:
            return None
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
        return out

    def sync_etf_daily(self, start_date: str = "20210101") -> int:
        """为 ``etf_info`` 中的每只 ETF 采集日线, upsert 到 ``etf_daily`` (批量提交).

        Args:
            start_date: 起始日期 YYYYMMDD (默认约 5 年回溯).
        """
        end_date = datetime.now().strftime("%Y%m%d")
        logger.info("开始同步 ETF 日线 (%s ~ %s)...", start_date, end_date)

        with get_session(readonly=True) as session:
            etf_codes = [row[0] for row in session.query(ETFInfo.code).all()]

        if not etf_codes:
            logger.warning("etf_info 表为空, 请先执行 sync_etf_list")
            return 0

        total = 0
        failed = 0
        buffer: list[dict] = []
        flush_every = 8000

        def _bulk_upsert_daily(sess, rows: list[dict]) -> None:
            if not rows:
                return
            for i in range(0, len(rows), 1500):
                chunk = rows[i: i + 1500]
                stmt = insert(ETFDaily).values(chunk)
                ex = stmt.excluded
                stmt = stmt.on_conflict_do_update(
                    index_elements=["code", "trade_date"],
                    set_={
                        "open": ex.open,
                        "high": ex.high,
                        "low": ex.low,
                        "close": ex.close,
                        "volume": ex.volume,
                        "amount": ex.amount,
                    },
                )
                sess.execute(stmt)

        with get_session() as session:
            for i, full_code in enumerate(etf_codes):
                symbol = full_code.split(".")[0]
                df = self._fetch_etf_hist_df(
                    full_code, symbol, start_date, end_date,
                )
                if df is None or df.empty:
                    failed += 1
                    continue

                records = self._map_etf_daily(df, full_code)
                if not records:
                    failed += 1
                    continue
                buffer.extend(records)
                total += len(records)

                if len(buffer) >= flush_every:
                    _bulk_upsert_daily(session, buffer)
                    buffer.clear()
                    logger.info(
                        "ETF 日线进度: %d/%d (累计 %d 条)",
                        i + 1, len(etf_codes), total,
                    )

            if buffer:
                _bulk_upsert_daily(session, buffer)

        logger.info("ETF 日线同步完成: %d 条, 无数据/失败约 %d 只", total, failed)
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
        default="20210101",
        help="ETF 日线起始日期 (默认约 5 年: 20210101)",
    )
    parser.add_argument("--start-year", default="2023", help="财务指标起始年份")
    parser.add_argument("--codes", nargs="*", help="股票代码列表 (仅 report/indicator)")
    parser.add_argument(
        "--periods", nargs="*",
        help="报告期列表 (仅 batch, 如 20240331 20240630 20240930 20241231)",
    )
    args = parser.parse_args()

    syncer = AkshareFinancialSync()

    if args.action in ("etf_list", "etf_full"):
        syncer.sync_etf_list()
    if args.action in ("etf_f10", "etf_full"):
        syncer.enrich_etf_info_from_f10_em()
    if args.action in ("etf_daily", "etf_full"):
        syncer.sync_etf_daily(start_date=args.start_date)
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
