"""通过 akshare 采集 A 股数据并入库 PostgreSQL

作为多数据源采集入口 (akshare + 沪深北交易所表 + 东财 + **新浪 hs_a** + **QMT 兜底**), 支持:
- A09: 股票列表同步 (akshare)
- A09b: 沪深北交易所基础表 → list_date / 行业
- A09c: 东财全市场快照 → pe/pb/总市值 等
- A09c2: **新浪** ``hs_a`` 分页 JSON (per/pb/mktcap) → 与东财 **互补** (东财断连或列为空时兜底; mktcap 按 **万元→亿** 换算)
- A09e: **QMT** ``get_instrument_detail`` → 与已有行 **COALESCE 合并**, 补 list_date、名称、交易所
- A09f: ``stock_financial_indicator`` 最新 ROE → 仅填补 ``stocks.roe`` 仍为空的行
- A09g: 板块推断 (科创/创业板/北证/沪深主板) + 修正 ``920xxx`` 交易所
- A09h: **巨潮** ``stock_profile_cninfo`` → 补 ``industry`` / ``list_date`` / ``sector`` (所属市场)
- A09d: ``sync_stocks_full`` = A09→A09b→A09c→A09c2→A09e→A09f→A09g→A09h
- A10: 日线增量同步
- A11: 指数数据同步

akshare 始终延迟导入, CI 环境无需安装。
"""
from __future__ import annotations

import math
import time
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import and_, func, not_, or_, text
from sqlalchemy.dialects.postgresql import insert

from src.common.config import settings
from src.common.db import get_session
from src.common.db_batch import DEFAULT_TABLE_UPSERT_FLUSH, log_upsert_commit
from src.common.logger import get_logger
from src.data.models import Stock, StockDaily, MarketIndex

logger = get_logger(__name__)

INDEX_NAME_MAP: dict[str, str] = {
    "000001": "上证综指",
    "399001": "深证成指",
    "000300": "沪深300",
    "000905": "中证500",
    "000852": "中证1000",
    "399006": "创业板指",
    "000688": "科创50",
}

_DAILY_COLUMN_MAP: dict[str, str] = {
    "日期": "trade_date",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "成交额": "amount",
    "振幅": "amplitude",
    "涨跌幅": "change_pct",
    "涨跌额": "change",
    "换手率": "turnover_rate",
}

_INDEX_COLUMN_MAP: dict[str, str] = {
    "日期": "trade_date",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "成交额": "amount",
}


def _exchange_from_code(code: str) -> str:
    """根据股票代码前缀判断交易所 (含北证 920xxx、沪 B 900xxx)。"""
    c = (code or "").strip()
    if not c:
        return ""
    if c.startswith("6"):
        return "SH"
    if c.startswith("900"):
        return "SH"
    if c.startswith("9"):
        return "BJ"
    if c.startswith(("0", "2", "3")):
        return "SZ"
    if c.startswith(("4", "8")):
        return "BJ"
    return ""


def _pick_df_column(df, *candidates: str) -> str | None:
    for col in candidates:
        if col in df.columns:
            return col
    return None


def _pick_df_column_fuzzy(df, *substrings: str) -> str | None:
    """列名在 akshare/东财改版时可能微调, 用子串匹配兜底。"""
    for col in df.columns:
        if not isinstance(col, str):
            continue
        for sub in substrings:
            if sub in col:
                return col
    return None


def _to_date_only(v):
    """解析上市日期等, 返回 datetime.date 或 None。"""
    import pandas as pd
    from datetime import date as dt_date

    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, dt_date):
        return v
    try:
        return pd.Timestamp(v).date()
    except Exception:
        return None


def _to_float_spot(v) -> float | None:
    import pandas as pd

    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    if isinstance(v, str):
        s = v.strip()
        if s in ("", "-", "—", "nan"):
            return None
        try:
            return float(s.replace(",", ""))
        except ValueError:
            return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


class AkshareDataSync:
    """通过 akshare 采集 A 股数据并入库 PostgreSQL"""

    def __init__(self):
        from src.datacollect.rate_limiter import TokenBucketLimiter

        self.limiter = TokenBucketLimiter.for_domain(
            "akshare",
            rate=settings.datacollect.akshare_rate,
            burst=settings.datacollect.akshare_burst,
        )

    def _call_ak(
        self, func_name: str, *, use_limiter: bool = True, **kwargs,
    ):
        """调用 akshare 函数, 带限流控制 (巨潮等独立源可 ``use_limiter=False``)。"""
        import akshare as ak

        fn = getattr(ak, func_name, None)
        if fn is None:
            raise AttributeError(f"akshare 没有函数: {func_name}")

        if use_limiter:
            self.limiter.acquire()
        return fn(**kwargs)

    # ----------------------------------------------------------------
    # A09: 股票列表同步
    # ----------------------------------------------------------------
    def sync_stock_list(self) -> int:
        """同步全部 A 股股票列表到 stocks 表

        Returns:
            入库股票数量
        """
        import akshare as ak

        logger.info("开始同步 A 股股票列表 (akshare)...")

        df = None
        try:
            self.limiter.acquire()
            df = ak.stock_info_a_code_name()
        except Exception as e:
            logger.warning("stock_info_a_code_name 失败 (%s), 尝试 stock_zh_a_spot_em 备用源...", e)

        if df is None or df.empty:
            try:
                df = ak.stock_zh_a_spot_em()
                if df is not None and not df.empty:
                    df = df.rename(columns={"代码": "code", "名称": "name"})
            except Exception as e2:
                logger.error("备用源 stock_zh_a_spot_em 也失败: %s", e2)
                return 0

        if df is None or df.empty:
            logger.warning("akshare 所有股票列表源均返回空数据")
            return 0

        records: list[dict] = []
        for _, row in df.iterrows():
            code = str(row.get("code", "")).strip()
            name = str(row.get("name", "")).strip()
            if not code or len(code) != 6:
                continue
            records.append({
                "code": code,
                "name": name,
                "exchange": _exchange_from_code(code),
            })

        if not records:
            logger.warning("未解析到有效的股票记录")
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
            log_upsert_commit("akshare.stock_list", len(batch))

        logger.info("A 股股票列表同步完成, 共 %d 只", count)
        return count

    # ----------------------------------------------------------------
    # A09b: 沪深北交易所基础信息 (上市日期 + 部分行业)
    # ----------------------------------------------------------------

    def enrich_stocks_from_exchange_info(self) -> int:
        """从上交所/深交所/北交所基础代码表补全 ``list_date`` 等.

        - 上证: ``stock_info_sh_name_code`` (主板A股 + 科创板)
        - 深证: ``stock_info_sz_name_code`` (A股列表, 含 ``所属行业``)
        - 北证: ``stock_info_bj_name_code``

        主键/唯一键为 ``stocks.code``; 写入用 ``ON CONFLICT (code) DO UPDATE`` 做幂等合并 (与「是否全量重拉」无关).

        **短路 (默认开)**: ``DATACOLLECT_EXCHANGE_INFO_SKIP_IF_NO_GAP`` 为真(默认)时, 若库中已有 6 位代码且
        其 ``list_date`` 均已非空, **不访问**上交所/深所/北交所接口, 直接 ``return 0``。
        ``sync_stocks_full`` 中 ``stock_list`` 在前, 新股入库后通常仍缺 ``list_date`` 会继续全量拉。
        若需**强制**与交易所全量对账(仅 industry 等变更、list_date 已齐也会跳过), 设
        ``DATACOLLECT_EXCHANGE_INFO_SKIP_IF_NO_GAP=false``.
        """
        import pandas as pd

        if settings.datacollect.exchange_info_skip_if_no_list_date_gap:
            with get_session(readonly=True) as session:
                code6 = func.length(func.trim(Stock.code)) == 6
                n_total = int(
                    session.query(func.count(Stock.code)).filter(code6).scalar() or 0,
                )
                n_gaps = int(
                    session.query(func.count(Stock.code))
                    .filter(code6, Stock.list_date.is_(None))
                    .scalar()
                    or 0,
                )
            if n_total > 0 and n_gaps == 0:
                logger.info(
                    "交易所基础表: 6 位代码 %d 只均已含 list_date, 跳过全量拉取与 upsert "
                    "(设 DATACOLLECT_EXCHANGE_INFO_SKIP_IF_NO_GAP=false 可强制重跑)",
                    n_total,
                )
                return 0

        logger.info("从沪深北交易所基础表补全 stocks 上市日期/行业...")

        # list of (ak_fn, kwargs, colmap)
        jobs: list[tuple[str, dict, dict[str, str]]] = [
            (
                "stock_info_sh_name_code",
                {"symbol": "主板A股"},
                {"code": "证券代码", "name": "证券简称", "date": "上市日期"},
            ),
            (
                "stock_info_sh_name_code",
                {"symbol": "科创板"},
                {"code": "证券代码", "name": "证券简称", "date": "上市日期"},
            ),
            (
                "stock_info_sz_name_code",
                {"symbol": "A股列表"},
                {
                    "code": "A股代码",
                    "name": "A股简称",
                    "date": "A股上市日期",
                    "industry": "所属行业",
                },
            ),
            (
                "stock_info_bj_name_code",
                {},
                {
                    "code": "证券代码",
                    "name": "证券简称",
                    "date": "上市日期",
                    "industry": "所属行业",
                },
            ),
        ]

        rows_out: dict[str, dict] = {}

        for fn_name, kwargs, cmap in jobs:
            try:
                df = self._call_ak(fn_name, **kwargs)
            except Exception as e:
                logger.warning("%s%s 失败: %s", fn_name, kwargs, e)
                continue
            if df is None or df.empty:
                logger.warning("%s%s 返回空表", fn_name, kwargs)
                continue

            code_key = cmap["code"]
            name_key = cmap["name"]
            date_key = cmap.get("date")
            ind_key = cmap.get("industry")

            if code_key not in df.columns or name_key not in df.columns:
                logger.warning("%s 缺少代码/名称列: %s", fn_name, list(df.columns))
                continue
            if ind_key and ind_key not in df.columns:
                ind_key = None
            if date_key and date_key not in df.columns:
                date_key = None

            for _, row in df.iterrows():
                raw = row.get(code_key)
                if raw is None or (isinstance(raw, float) and pd.isna(raw)):
                    continue
                code = str(raw).strip()
                if not code or len(code) != 6:
                    continue
                nv = row.get(name_key)
                name = str(nv).strip() if nv is not None and not (
                    isinstance(nv, float) and pd.isna(nv)
                ) else ""
                if not name:
                    name = code
                if len(name) > 50:
                    name = name[:50]

                ld = _to_date_only(row.get(date_key)) if date_key else None
                inds = None
                if ind_key:
                    iv = row.get(ind_key)
                    if iv is not None and not (isinstance(iv, float) and pd.isna(iv)):
                        s = str(iv).strip()
                        inds = s[:50] if s else None

                if code not in rows_out:
                    rows_out[code] = {
                        "code": code,
                        "name": name,
                        "exchange": _exchange_from_code(code) or None,
                        "list_date": ld,
                        "industry": inds,
                        "updated_at": datetime.now(),
                    }
                else:
                    prev = rows_out[code]
                    if ld is not None:
                        prev["list_date"] = ld
                    if inds is not None:
                        prev["industry"] = inds
                    if name and name != code:
                        prev["name"] = name
                    prev["exchange"] = _exchange_from_code(code) or prev.get("exchange")
                    prev["updated_at"] = datetime.now()

        if not rows_out:
            logger.warning("交易所基础表未解析到任何股票")
            return 0

        records = list(rows_out.values())
        count = 0
        for i in range(0, len(records), DEFAULT_TABLE_UPSERT_FLUSH):
            batch = records[i: i + DEFAULT_TABLE_UPSERT_FLUSH]
            with get_session() as session:
                stmt = insert(Stock).values(batch)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["code"],
                    set_={
                        "name": func.coalesce(stmt.excluded.name, Stock.name),
                        "exchange": func.coalesce(
                            stmt.excluded.exchange, Stock.exchange,
                        ),
                        "list_date": func.coalesce(
                            stmt.excluded.list_date, Stock.list_date,
                        ),
                        "industry": func.coalesce(
                            stmt.excluded.industry, Stock.industry,
                        ),
                        "updated_at": stmt.excluded.updated_at,
                    },
                )
                session.execute(stmt)
            count += len(batch)
            log_upsert_commit("akshare.exchange_info", len(batch))

        logger.info("交易所基础信息补全完成, 共 %d 只", count)
        return count

    # ----------------------------------------------------------------
    # A09c: 补全 stocks 估值/地域 (东财全市场快照)
    # ----------------------------------------------------------------

    def enrich_stocks_from_spot(
        self,
        stall_check: Callable[[], bool] | None = None,
    ) -> int:
        """从 ``stock_zh_a_spot_em`` 补全 ``stocks`` 表中估值、市值等字段.

        与 ``sync_stock_list`` 的备用数据源一致, 单次调用由 akshare 内部分页拉全市场.
        当前东财该接口**通常仅有**: ``pe_ttm``(市盈率-动态)、``pb``、``总市值``;
        **不含** 行业/地域/ROE — 行业与上市日期依赖 ``enrich_stocks_from_exchange_info``。

        使用 ``COALESCE`` 避免用 NULL 覆盖已有列 (如交易所补全的 industry)。

        Args:
            stall_check: 若可调用且返回 True (如 ``parallel_qmt`` 本类 120s 无落盘), 放弃东财重试,
                返回 0 以便 ``sync_stocks_full`` 继续 **新浪 / QMT** 等下一数据源。

        Returns:
            成功参与 upsert 的股票数量
        """
        import pandas as pd
        import requests

        logger.info("从 stock_zh_a_spot_em 补全 stocks 估值/市值 (带网络重试)...")

        def _is_transient_em(exc: BaseException) -> bool:
            """东财分页拉取常见: RemoteDisconnected / Connection aborted。"""
            if isinstance(
                exc,
                (
                    requests.exceptions.ConnectionError,
                    requests.exceptions.ChunkedEncodingError,
                    requests.exceptions.Timeout,
                ),
            ):
                return True
            if isinstance(exc, OSError):
                return True
            return False

        max_attempts = 10
        df = None
        last_exc: BaseException | None = None
        for attempt in range(1, max_attempts + 1):
            if stall_check and stall_check():
                logger.warning(
                    "stock_zh_a_spot_em: 编排器本类滞停, 放弃东财 (继续 sync_stocks_full 内后续数据源)",
                )
                return 0
            try:
                df = self._call_ak("stock_zh_a_spot_em")
                break
            except Exception as e:  # noqa: BLE001
                last_exc = e
                if not _is_transient_em(e) or attempt >= max_attempts:
                    break
                wait_s = min(120.0, 3.0 * (2.0 ** (attempt - 1)))
                logger.warning(
                    "stock_zh_a_spot_em 重试 %s/10: %s",
                    attempt,
                    e,
                )
                time.sleep(wait_s)
        if df is None:
            if last_exc is not None:
                logger.error(
                    "stock_zh_a_spot_em 多次重试仍失败: %s — 请检查网络/代理; "
                    "sync_stocks_full 可继续新浪/其它源",
                    last_exc,
                )
            return 0

        if df is None or df.empty:
            logger.warning("stock_zh_a_spot_em 返回空表")
            return 0

        code_col = _pick_df_column(df, "代码", "code")
        if not code_col:
            logger.error("行情表缺少代码列, 列名: %s", list(df.columns))
            return 0

        pe_col = (
            _pick_df_column(df, "市盈率-动态", "动态市盈率", "PE(动)", "市盈率(动)")
            or _pick_df_column_fuzzy(df, "市盈")
        )
        pb_col = _pick_df_column(df, "市净率") or _pick_df_column_fuzzy(df, "市净")
        mcap_col = _pick_df_column(df, "总市值") or _pick_df_column_fuzzy(df, "总市值")
        roe_col = _pick_df_column(df, "净资产收益率", "ROE")
        ind_col = _pick_df_column(df, "行业", "所属行业")
        sec_col = _pick_df_column(df, "地域", "所属板块")
        name_col = _pick_df_column(df, "名称", "name")

        logger.info(
            "stock_zh_a_spot 列映射: code=%s pe=%s pb=%s mcap=%s roe=%s ind=%s sec=%s",
            code_col,
            pe_col,
            pb_col,
            mcap_col,
            roe_col,
            ind_col,
            sec_col,
        )

        if not any((pe_col, pb_col, mcap_col)):
            logger.warning(
                "行情表缺少市盈率/市净率/总市值列 (当前列: %s), 跳过补全",
                list(df.columns),
            )
            return 0

        records: list[dict] = []
        for _, row in df.iterrows():
            raw_code = row.get(code_col)
            if raw_code is None or (isinstance(raw_code, float) and pd.isna(raw_code)):
                continue
            code = str(raw_code).strip()
            if not code or len(code) != 6:
                continue

            nm = ""
            if name_col:
                v = row.get(name_col)
                if v is not None and not (isinstance(v, float) and pd.isna(v)):
                    nm = str(v).strip()

            mcap_val = None
            if mcap_col:
                v = _to_float_spot(row.get(mcap_col))
                mcap_val = (v / 1e8) if v is not None else None

            inds = None
            if ind_col:
                ind = row.get(ind_col)
                if ind is not None and not (isinstance(ind, float) and pd.isna(ind)):
                    s = str(ind).strip()
                    inds = s[:50] if s else None

            secs = None
            if sec_col:
                sec = row.get(sec_col)
                if sec is not None and not (isinstance(sec, float) and pd.isna(sec)):
                    s = str(sec).strip()
                    secs = s[:50] if s else None

            rec: dict = {
                "code": code,
                "name": nm if nm else code,
                "exchange": _exchange_from_code(code) or None,
                "pe_ttm": _to_float_spot(row.get(pe_col)) if pe_col else None,
                "pb": _to_float_spot(row.get(pb_col)) if pb_col else None,
                "market_cap": mcap_val,
                "roe": _to_float_spot(row.get(roe_col)) if roe_col else None,
                "industry": inds,
                "sector": secs,
                "updated_at": datetime.now(),
            }
            records.append(rec)

        if not records:
            logger.warning("解析后无有效补全记录")
            return 0

        count = 0
        for i in range(0, len(records), DEFAULT_TABLE_UPSERT_FLUSH):
            if stall_check and stall_check():
                logger.warning(
                    "stock_zh_a_spot_em: 批间滞停, 已落盘约 %d 行, 余量由 sync_stocks_full 后续子步骤补",
                    count,
                )
                return count
            batch = records[i: i + DEFAULT_TABLE_UPSERT_FLUSH]
            with get_session() as session:
                stmt = insert(Stock).values(batch)
                ex = stmt.excluded
                stmt = stmt.on_conflict_do_update(
                    index_elements=["code"],
                    set_={
                        "name": func.coalesce(ex.name, Stock.name),
                        "exchange": func.coalesce(ex.exchange, Stock.exchange),
                        "pe_ttm": func.coalesce(ex.pe_ttm, Stock.pe_ttm),
                        "pb": func.coalesce(ex.pb, Stock.pb),
                        "market_cap": func.coalesce(ex.market_cap, Stock.market_cap),
                        "roe": func.coalesce(ex.roe, Stock.roe),
                        "industry": func.coalesce(ex.industry, Stock.industry),
                        "sector": func.coalesce(ex.sector, Stock.sector),
                        "updated_at": ex.updated_at,
                    },
                )
                session.execute(stmt)
            count += len(batch)
            log_upsert_commit("akshare.spot_em", len(batch))

        logger.info("stocks 扩展字段补全完成, 共 %d 只", count)
        return count

    # ----------------------------------------------------------------
    # A09c2: 新浪 hs_a 实时列表 (per / pb / mktcap) — 与东财并列兜底
    # ----------------------------------------------------------------

    def enrich_stocks_from_spot_sina(self) -> int:
        """新浪 ``Market_Center.getHQNodeData`` (node=hs_a) 分页拉取 A 股, 写入 pe/pb/总市值.

        原始 JSON 含 ``per``(市盈动)、``pb``、``mktcap``(万元); 总市值入库为 **亿元** (``/10000``).
        与 :meth:`enrich_stocks_from_spot` 相同采用 ``COALESCE``, 不覆盖已有非空估值。

        Note:
            新浪对高频重复全量拉取可能短期限流; 与东财错开使用可降低单点故障。
        """
        import re
        import requests
        from akshare.stock.cons import (
            zh_sina_a_stock_count_url,
            zh_sina_a_stock_payload,
            zh_sina_a_stock_url,
        )
        from akshare.utils import demjson
        from tenacity import (
            retry,
            retry_if_exception_type,
            stop_after_attempt,
            wait_exponential,
        )

        logger.info("从新浪 hs_a 补全 stocks pe/pb/总市值 (与东财互补)...")

        def _page_count() -> int:
            res = requests.get(zh_sina_a_stock_count_url, timeout=45)
            res.raise_for_status()
            n = int(re.findall(re.compile(r"\d+"), res.text)[0])
            return max(1, math.ceil(n / 80))

        @retry(
            reraise=True,
            stop=stop_after_attempt(6),
            wait=wait_exponential(multiplier=1, min=2, max=90),
            retry=retry_if_exception_type(
                (
                    requests.exceptions.ConnectionError,
                    requests.exceptions.Timeout,
                    requests.exceptions.HTTPError,
                ),
            ),
        )
        def _get_page(page: int) -> list[dict]:
            payload = zh_sina_a_stock_payload.copy()
            payload["page"] = str(page)
            r = requests.get(zh_sina_a_stock_url, params=payload, timeout=60)
            r.raise_for_status()
            data = demjson.decode(r.text)
            if not isinstance(data, list):
                return []
            return data

        try:
            total_pages = _page_count()
        except Exception as e:
            logger.error("新浪 hs_a 获取总页数失败: %s", e)
            return 0

        records: list[dict] = []
        for page in range(1, total_pages + 1):
            self.limiter.acquire()
            try:
                rows = _get_page(page)
            except Exception as e:
                logger.warning("新浪 hs_a 第 %d/%d 页失败: %s", page, total_pages, e)
                continue
            for row in rows:
                raw_code = row.get("code")
                if raw_code is None:
                    continue
                code = str(raw_code).strip()
                if len(code) != 6 or not code.isdigit():
                    continue
                nm = (row.get("name") or "").strip() or code
                if len(nm) > 50:
                    nm = nm[:50]
                pe_v = _to_float_spot(row.get("per"))
                pb_v = _to_float_spot(row.get("pb"))
                mcap_raw = _to_float_spot(row.get("mktcap"))
                mcap_v = (mcap_raw / 10000.0) if mcap_raw is not None else None
                records.append({
                    "code": code,
                    "name": nm,
                    "exchange": _exchange_from_code(code) or None,
                    "pe_ttm": pe_v,
                    "pb": pb_v,
                    "market_cap": mcap_v,
                    "updated_at": datetime.now(),
                })

        if not records:
            logger.warning("新浪 hs_a 未解析到有效记录")
            return 0

        count = 0
        for i in range(0, len(records), DEFAULT_TABLE_UPSERT_FLUSH):
            batch = records[i: i + DEFAULT_TABLE_UPSERT_FLUSH]
            with get_session() as session:
                stmt = insert(Stock).values(batch)
                ex = stmt.excluded
                stmt = stmt.on_conflict_do_update(
                    index_elements=["code"],
                    set_={
                        "name": func.coalesce(ex.name, Stock.name),
                        "exchange": func.coalesce(ex.exchange, Stock.exchange),
                        "pe_ttm": func.coalesce(ex.pe_ttm, Stock.pe_ttm),
                        "pb": func.coalesce(ex.pb, Stock.pb),
                        "market_cap": func.coalesce(ex.market_cap, Stock.market_cap),
                        "updated_at": ex.updated_at,
                    },
                )
                session.execute(stmt)
            count += len(batch)
            log_upsert_commit("akshare.sina_hs_a", len(batch))

        logger.info("新浪 hs_a 估值补全完成, 共 %d 只", count)
        return count

    # ----------------------------------------------------------------
    # A09f: 财务指标表 → stocks.roe
    # ----------------------------------------------------------------

    def enrich_stocks_roe_from_financial_indicator(self) -> int:
        """用 ``stock_financial_indicator`` 最新一期 ``roe_weighted`` / ``roe_diluted`` 填补 ``stocks.roe``."""
        sql = text("""
            UPDATE stocks s
            SET roe = f.roe_v::double precision,
                updated_at = NOW()
            FROM (
                SELECT DISTINCT ON (code)
                    code,
                    COALESCE(roe_weighted, roe_diluted) AS roe_v
                FROM stock_financial_indicator
                WHERE roe_weighted IS NOT NULL OR roe_diluted IS NOT NULL
                ORDER BY code, report_date DESC
            ) f
            WHERE s.code = f.code
              AND s.roe IS NULL
              AND f.roe_v IS NOT NULL
        """)
        with get_session() as session:
            res = session.execute(sql)
            n = res.rowcount or 0
        logger.info("从财务指标表补全 stocks.roe: %d 行", n)
        return int(n)

    # ----------------------------------------------------------------
    # A09g: 板块默认值 + 北交所代码规范
    # ----------------------------------------------------------------

    def enrich_stocks_sector_board_defaults(self) -> int:
        """按代码规则写入 ``sector`` (仍为空时): 科创/创业板/北证/沪深主板。"""
        sql = text("""
            UPDATE stocks SET sector = CASE
                WHEN code LIKE '688%' OR code LIKE '689%' THEN '科创板'
                WHEN code LIKE '300%' OR code LIKE '301%' THEN '创业板'
                WHEN exchange = 'BJ' OR code LIKE '4%' OR code LIKE '8%'
                     OR code LIKE '920%' THEN '北交所'
                ELSE '沪深主板'
            END,
            updated_at = NOW()
            WHERE sector IS NULL
        """)
        with get_session() as session:
            res = session.execute(sql)
            n = res.rowcount or 0
        logger.info("板块默认值补全 sector: %d 行", int(n))
        return int(n)

    def fix_stocks_exchange_bj_920(self) -> int:
        """``920xxx`` 统一为北交所代码 (部分数据源 exchange 为空)。"""
        sql = text("""
            UPDATE stocks SET exchange = 'BJ', updated_at = NOW()
            WHERE code LIKE '920%%' AND (
                exchange IS NULL OR trim(exchange) = ''
            )
        """)
        with get_session() as session:
            res = session.execute(sql)
            n = res.rowcount or 0
        logger.info("修正 920xxx 交易所=>BJ: %d 行", int(n))
        return int(n)

    # ----------------------------------------------------------------
    # A09h: 巨潮资讯 → industry / list_date / sector
    # ----------------------------------------------------------------

    def enrich_stocks_from_cninfo_profile(self) -> int:
        """巨潮 ``stock_profile_cninfo`` 按股拉取概况, 填补 **仍为空的** industry/list_date/sector.

        仅处理 ``industry IS NULL OR list_date IS NULL`` 的行 (上证主板等交易所表无行业,
        通常两千余只)。``sector`` 已由 :meth:`enrich_stocks_sector_board_defaults` 写入粗粒度板块;
        巨潮 ``所属市场`` 可进一步细化 (若该行仍需拉概况)。退市股巨潮无概况时跳过。

        Note:
            巨潮域名与东财 AkShare 限流桶分离, 使用固定短间隔避免触发对方限流,
            而不走 ``self.limiter`` (默认 0.15req/s 会拖长到数小时)。
        """
        import time

        import pandas as pd

        with get_session(readonly=True) as session:
            q = session.query(Stock.code, Stock.name).filter(
                or_(
                    Stock.industry.is_(None),
                    Stock.list_date.is_(None),
                ),
            )
            pairs = q.all()
            codes = [p[0] for p in pairs]
            code_to_name: dict[str, str] = {p[0]: p[1] for p in pairs}

        if not codes:
            return 0

        logger.info("巨潮公司概况补全: 待处理 %d 只...", len(codes))
        updated = 0
        batch: list[dict] = []

        def _flush(sess, rows: list[dict]) -> None:
            nonlocal updated
            if not rows:
                return
            for i in range(0, len(rows), 200):
                chunk = rows[i: i + 200]
                stmt = insert(Stock).values(chunk)
                ex = stmt.excluded
                stmt = stmt.on_conflict_do_update(
                    index_elements=["code"],
                    set_={
                        "name": func.coalesce(ex.name, Stock.name),
                        "exchange": func.coalesce(
                            ex.exchange, Stock.exchange,
                        ),
                        "industry": func.coalesce(
                            ex.industry, Stock.industry,
                        ),
                        "list_date": func.coalesce(
                            ex.list_date, Stock.list_date,
                        ),
                        "sector": func.coalesce(ex.sector, Stock.sector),
                        "updated_at": ex.updated_at,
                    },
                )
                sess.execute(stmt)
                log_upsert_commit("akshare.cninfo_profile", len(chunk))
            updated += len(rows)
            rows.clear()

        with get_session() as session:
            for idx, code in enumerate(codes, start=1):
                time.sleep(0.12)
                try:
                    df = self._call_ak(
                        "stock_profile_cninfo",
                        symbol=code,
                        use_limiter=False,
                    )
                except Exception as e:
                    if idx <= 3:
                        logger.debug("cninfo %s: %s", code, e)
                    continue
                if df is None or df.empty:
                    continue
                row = df.iloc[0]
                ind_col = _pick_df_column(
                    df, "所属行业",
                ) or _pick_df_column_fuzzy(df, "行业")
                date_col = _pick_df_column(df, "上市日期")
                mkt_col = _pick_df_column(df, "所属市场")

                inds = None
                if ind_col:
                    v = row.get(ind_col)
                    if v is not None and not (
                        isinstance(v, float) and pd.isna(v)
                    ):
                        s = str(v).strip()
                        inds = s[:50] if s else None
                ld = _to_date_only(row.get(date_col)) if date_col else None
                sec = None
                if mkt_col:
                    v = row.get(mkt_col)
                    if v is not None and not (
                        isinstance(v, float) and pd.isna(v)
                    ):
                        s = str(v).strip()
                        sec = s[:50] if s else None

                nm = None
                name_col = _pick_df_column(df, "A股简称")
                if name_col:
                    v = row.get(name_col)
                    if v is not None and not (
                        isinstance(v, float) and pd.isna(v)
                    ):
                        s = str(v).strip()
                        nm = s[:50] if s else None

                cur_nm = code_to_name.get(code) or code
                batch.append({
                    "code": code,
                    "name": nm or cur_nm,
                    "exchange": _exchange_from_code(code) or None,
                    "industry": inds,
                    "list_date": ld,
                    "sector": sec,
                    "updated_at": datetime.now(),
                })
                if len(batch) >= 80:
                    _flush(session, batch)
                if idx % 400 == 0:
                    logger.info("cninfo 进度 %d/%d", idx, len(codes))

            _flush(session, batch)

        logger.info("巨潮概况补全完成, 累计 upsert %d 只", updated)
        return updated

    # ----------------------------------------------------------------
    # A09e: QMT 合约详情兜底 (与 akshare 合并, 不盲目覆盖)
    # ----------------------------------------------------------------

    def enrich_stocks_from_qmt(self) -> int:
        """使用 MiniQMT/标准 QMT ``get_instrument_detail`` 补全 ``list_date``、名称、交易所.

        - 先遍历 ``沪深A股`` 板块合约, 与 ``stocks`` 行 **COALESCE 合并** (东财/交易所有值时保留)。
        - 再对库中 **仍缺 list_date** 且疑似北交所的代码尝试 ``xxxxxx.BJ``。

        说明: 全推 tick 不含 PE/PB; 估值仍依赖 A09c 东财; QMT 主要兜底 **上市日期与基础身份**。
        """
        try:
            from src.data.market_data import _parse_open_date
            from src.data.qmt_client import QMTClient
        except ImportError as e:
            logger.warning("QMT 模块不可用, 跳过: %s", e)
            return 0

        client = QMTClient()
        total = 0
        failed = 0

        def _merge_upsert(session, row: dict) -> None:
            stmt = insert(Stock).values(**row)
            ex = stmt.excluded
            stmt = stmt.on_conflict_do_update(
                index_elements=["code"],
                set_={
                    "name": func.coalesce(ex.name, Stock.name),
                    "exchange": func.coalesce(ex.exchange, Stock.exchange),
                    "list_date": func.coalesce(ex.list_date, Stock.list_date),
                    "updated_at": ex.updated_at,
                },
            )
            session.execute(stmt)

        try:
            main_codes = client.get_stock_list_in_sector("沪深A股")
        except Exception as e:
            logger.warning("QMT get_stock_list_in_sector 失败: %s", e)
            main_codes = []

        logger.info("QMT 合并: 沪深A股成分 %d 只", len(main_codes))

        pending: list[dict] = []
        for full_code in main_codes:
            try:
                detail = client.get_instrument_detail(full_code)
                if not detail:
                    continue
                code = full_code.split(".")[0]
                ex = full_code.split(".")[-1] if "." in full_code else ""
                nm = (detail.get("InstrumentName") or "").strip()
                if len(nm) > 50:
                    nm = nm[:50]
                row = {
                    "code": code,
                    "name": nm or code,
                    "exchange": ex or None,
                    "list_date": _parse_open_date(detail.get("OpenDate")),
                    "updated_at": datetime.now(),
                }
                pending.append(row)
                if len(pending) >= DEFAULT_TABLE_UPSERT_FLUSH:
                    with get_session() as session:
                        for r in pending:
                            _merge_upsert(session, r)
                    total += len(pending)
                    pending.clear()
            except Exception as e:
                failed += 1
                if failed <= 5:
                    logger.debug("QMT %s detail 失败: %s", full_code, e)

        if pending:
            with get_session() as session:
                for r in pending:
                    _merge_upsert(session, r)
            total += len(pending)

        main_n = total
        bj_n = self._enrich_bj_list_date_from_qmt(client)
        total += bj_n
        logger.info(
            "QMT 基础信息合并完成: 沪深A股处理 %d 条, 北交所补漏 %d 条, 明细异常约 %d 次",
            main_n,
            bj_n,
            failed,
        )
        return total

    def _enrich_bj_list_date_from_qmt(self, client) -> int:
        """库中 list_date 为空且疑似北交所时, 尝试 ``code.BJ`` 拉 OpenDate。"""
        from src.data.market_data import _parse_open_date

        bj_cond = or_(
            Stock.exchange == "BJ",
            Stock.code.startswith("4"),
            Stock.code.startswith("8"),
            and_(Stock.code.startswith("9"), not_(Stock.code.startswith("900"))),
        )
        with get_session(readonly=True) as session:
            codes = [
                row[0]
                for row in session.query(Stock.code)
                .filter(Stock.list_date.is_(None), bj_cond)
                .all()
            ]

        if not codes:
            return 0

        logger.info("QMT 北交所补漏 list_date: %d 只", len(codes))
        n = 0
        pending_bj: list[dict] = []
        for code in codes:
            full = f"{code}.BJ"
            try:
                detail = client.get_instrument_detail(full)
                if not detail:
                    continue
                ld = _parse_open_date(detail.get("OpenDate"))
                if ld is None:
                    continue
                nm = (detail.get("InstrumentName") or "").strip()
                if len(nm) > 50:
                    nm = nm[:50]
                row = {
                    "code": code,
                    "name": nm or code,
                    "exchange": "BJ",
                    "list_date": ld,
                    "updated_at": datetime.now(),
                }
                pending_bj.append(row)
                if len(pending_bj) >= DEFAULT_TABLE_UPSERT_FLUSH:
                    with get_session() as session:
                        for rw in pending_bj:
                            stmt = insert(Stock).values(**rw)
                            ex = stmt.excluded
                            stmt = stmt.on_conflict_do_update(
                                index_elements=["code"],
                                set_={
                                    "name": func.coalesce(ex.name, Stock.name),
                                    "exchange": func.coalesce(ex.exchange, Stock.exchange),
                                    "list_date": func.coalesce(ex.list_date, Stock.list_date),
                                    "updated_at": ex.updated_at,
                                },
                            )
                            session.execute(stmt)
                    n += len(pending_bj)
                    pending_bj.clear()
            except Exception:
                continue
        if pending_bj:
            with get_session() as session:
                for rw in pending_bj:
                    stmt = insert(Stock).values(**rw)
                    ex = stmt.excluded
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["code"],
                        set_={
                            "name": func.coalesce(ex.name, Stock.name),
                            "exchange": func.coalesce(ex.exchange, Stock.exchange),
                            "list_date": func.coalesce(ex.list_date, Stock.list_date),
                            "updated_at": ex.updated_at,
                        },
                    )
                    session.execute(stmt)
            n += len(pending_bj)
        return n

    def try_enrich_from_qmt(self) -> int:
        """兼容旧调用: 与 :meth:`enrich_stocks_from_qmt` 相同 (合并模式, 非整表覆盖)。"""
        return self.enrich_stocks_from_qmt()

    def sync_stocks_full(
        self,
        use_qmt: bool = False,
        *,
        stall_check: Callable[[], bool] | None = None,
    ) -> dict[str, int]:
        """补全 ``stocks`` 推荐流程: akshare 列表 → 交易所表 → 东财估值 → **QMT 合并兜底**。

        Args:
            use_qmt: 已废弃; QMT 合并默认执行。传 True 时仅打一行说明。
            stall_check: 若可调用且返回 True(如 parallel_qmt 本类 120s 无落盘), 不再执行后续子步骤, 返回已完成的 results。
        """
        db_tail = settings.database.url
        if "@" in db_tail:
            db_tail = db_tail.split("@", 1)[-1]
        logger.info("sync_stocks_full 目标 PostgreSQL: …@%s", db_tail)
        if use_qmt:
            logger.info("sync_stocks_full: --use-qmt 已默认内置 QMT 合并, 无需再指定")

        results: dict[str, int] = {}

        def _stall() -> bool:
            if stall_check and stall_check():
                logger.warning(
                    "sync_stocks_full: 编排器判定本类滞停(约无批量落盘), 跳过后续子步骤, 已写入: %s",
                    list(results.keys()),
                )
                return True
            return False

        results["stock_list"] = self.sync_stock_list()
        if _stall():
            return results
        results["exchange_info"] = self.enrich_stocks_from_exchange_info()
        if _stall():
            return results
        results["spot_enrich"] = self.enrich_stocks_from_spot(stall_check=stall_check)
        if _stall():
            return results
        results["spot_sina"] = self.enrich_stocks_from_spot_sina()
        if _stall():
            return results
        results["qmt_merge"] = self.enrich_stocks_from_qmt()
        if _stall():
            return results
        results["roe_from_financial"] = (
            self.enrich_stocks_roe_from_financial_indicator()
        )
        if _stall():
            return results
        results["sector_board"] = self.enrich_stocks_sector_board_defaults()
        if _stall():
            return results
        results["exchange_920"] = self.fix_stocks_exchange_bj_920()
        if _stall():
            return results
        results["cninfo_profile"] = self.enrich_stocks_from_cninfo_profile()
        if _stall():
            return results
        logger.info("sync_stocks_full 完成: %s", results)
        return results

    # ----------------------------------------------------------------
    # A10: 日线增量同步
    # ----------------------------------------------------------------
    def sync_daily_incremental(self, days_back: int = 30) -> int:
        """增量同步日线数据: 对每只股票补齐最近 days_back 天内缺失的日线

        Returns:
            入库记录总数
        """
        logger.info("开始增量同步日线数据 (days_back=%d)...", days_back)
        end_date = datetime.now().strftime("%Y%m%d")
        fallback_start = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")

        with get_session() as session:
            stocks = session.query(Stock.code).all()
        stock_codes = [row[0] for row in stocks]

        if not stock_codes:
            logger.warning("stocks 表为空, 请先运行 sync_stock_list()")
            return 0

        max_dates: dict[str, str] = {}
        with get_session() as session:
            rows = (
                session.query(StockDaily.code, func.max(StockDaily.trade_date))
                .group_by(StockDaily.code)
                .all()
            )
            for code, max_date in rows:
                if max_date:
                    max_dates[code] = max_date.strftime("%Y%m%d")

        total_inserted = 0
        total_stocks = len(stock_codes)
        batch_size = settings.download.batch_size or 500

        for batch_idx in range(0, total_stocks, batch_size):
            batch_codes = stock_codes[batch_idx: batch_idx + batch_size]
            batch_num = batch_idx // batch_size + 1
            total_batches = (total_stocks + batch_size - 1) // batch_size
            logger.info(
                "日线同步批次 %d/%d (%d 只股票)...",
                batch_num, total_batches, len(batch_codes),
            )

            batch_records: list[dict] = []
            for code in batch_codes:
                start_date = max_dates.get(code, fallback_start)
                try:
                    records = self._fetch_daily_for_stock(code, start_date, end_date)
                    batch_records.extend(records)
                except Exception as e:
                    logger.warning("获取 %s 日线失败: %s", code, e)

            if batch_records:
                total_inserted += _bulk_upsert_daily(batch_records)

            logger.info(
                "批次 %d/%d 完成, 本批入库 %d 条",
                batch_num, total_batches, len(batch_records),
            )

        logger.info("日线增量同步完成, 共入库 %d 条", total_inserted)
        return total_inserted

    def _fetch_daily_for_stock(
        self, code: str, start_date: str, end_date: str
    ) -> list[dict]:
        """获取单只股票的日线数据并转换为入库记录列表"""
        import akshare as ak

        self.limiter.acquire()
        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )

        if df is None or df.empty:
            return []

        records: list[dict] = []
        for _, row in df.iterrows():
            trade_date_raw = row.get("日期")
            if trade_date_raw is None:
                continue
            try:
                if hasattr(trade_date_raw, "date"):
                    trade_date = trade_date_raw.date()
                else:
                    trade_date = datetime.strptime(str(trade_date_raw), "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue

            records.append({
                "code": code,
                "trade_date": trade_date,
                "open": _safe_float(row, "开盘"),
                "high": _safe_float(row, "最高"),
                "low": _safe_float(row, "最低"),
                "close": _safe_float(row, "收盘"),
                "volume": _safe_int(row, "成交量"),
                "amount": _safe_float(row, "成交额"),
                "amplitude": _safe_float(row, "振幅"),
                "change_pct": _safe_float(row, "涨跌幅"),
                "change": _safe_float(row, "涨跌额"),
                "turnover_rate": _safe_float(row, "换手率"),
            })
        return records

    # ----------------------------------------------------------------
    # A11: 指数数据同步
    # ----------------------------------------------------------------
    def sync_index_data(self, start_date: str = "20230101") -> int:
        """同步主要指数日线数据到 market_index 表

        Returns:
            入库记录总数
        """
        import akshare as ak

        end_date = datetime.now().strftime("%Y%m%d")
        logger.info(
            "开始同步指数数据 (%s ~ %s, %d 个指数)...",
            start_date, end_date, len(INDEX_NAME_MAP),
        )

        total_inserted = 0

        for index_code, index_name in INDEX_NAME_MAP.items():
            try:
                self.limiter.acquire()
                df = ak.stock_zh_index_daily_em(
                    symbol=index_code,
                    start_date=start_date,
                    end_date=end_date,
                )

                if df is None or df.empty:
                    logger.warning("指数 %s (%s) 无数据", index_code, index_name)
                    continue

                records = self._parse_index_df(index_code, index_name, df)
                if records:
                    total_inserted += _bulk_upsert_index(records)

                logger.info(
                    "指数 %s (%s) 同步 %d 条",
                    index_code, index_name, len(records),
                )
            except Exception as e:
                logger.warning("同步指数 %s 失败: %s", index_code, e)

        logger.info("指数数据同步完成, 共入库 %d 条", total_inserted)
        return total_inserted

    def _parse_index_df(
        self, index_code: str, index_name: str, df
    ) -> list[dict]:
        """将 akshare 指数 DataFrame 转换为入库记录, 并补算涨跌额/涨跌幅"""
        records: list[dict] = []
        prev_close: float | None = None

        for _, row in df.iterrows():
            trade_date_raw = row.get("日期")
            if trade_date_raw is None:
                continue
            try:
                if hasattr(trade_date_raw, "date"):
                    trade_date = trade_date_raw.date()
                else:
                    trade_date = datetime.strptime(str(trade_date_raw), "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue

            close_val = _safe_float(row, "收盘")
            change_val = _safe_float(row, "涨跌额") if "涨跌额" in row.index else None
            change_pct_val = _safe_float(row, "涨跌幅") if "涨跌幅" in row.index else None

            if change_val is None and prev_close is not None and close_val is not None:
                change_val = round(close_val - prev_close, 4)
            if change_pct_val is None and prev_close and close_val is not None:
                change_pct_val = round((close_val - prev_close) / prev_close * 100, 4)

            records.append({
                "index_code": index_code,
                "index_name": index_name,
                "trade_date": trade_date,
                "open": _safe_float(row, "开盘"),
                "high": _safe_float(row, "最高"),
                "low": _safe_float(row, "最低"),
                "close": close_val,
                "volume": _safe_int(row, "成交量"),
                "amount": _safe_float(row, "成交额"),
                "change": change_val,
                "change_pct": change_pct_val,
            })

            if close_val is not None:
                prev_close = close_val

        return records


# ====================================================================
# 内部工具函数
# ====================================================================

def _safe_float(row, col: str) -> float | None:
    try:
        v = row.get(col) if hasattr(row, "get") else getattr(row, col, None)
        if v is not None:
            import pandas as pd
            if not pd.isna(v):
                return float(v)
    except (ValueError, TypeError):
        pass
    return None


def _safe_int(row, col: str) -> int | None:
    try:
        v = row.get(col) if hasattr(row, "get") else getattr(row, col, None)
        if v is not None:
            import pandas as pd
            if not pd.isna(v):
                return int(v)
    except (ValueError, TypeError):
        pass
    return None


def _bulk_upsert_daily(
    records: list[dict], batch_size: int = DEFAULT_TABLE_UPSERT_FLUSH,
) -> int:
    count = 0
    for i in range(0, len(records), batch_size):
        batch = records[i: i + batch_size]
        with get_session() as session:
            stmt = insert(StockDaily).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=["code", "trade_date"],
                set_={
                    "open": stmt.excluded.open,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "close": stmt.excluded.close,
                    "volume": stmt.excluded.volume,
                    "amount": stmt.excluded.amount,
                    "amplitude": stmt.excluded.amplitude,
                    "change_pct": stmt.excluded.change_pct,
                    "change": stmt.excluded.change,
                    "turnover_rate": stmt.excluded.turnover_rate,
                },
            )
            session.execute(stmt)
        count += len(batch)
        log_upsert_commit("akshare.stock_daily", len(batch))
    return count


def _bulk_upsert_index(
    records: list[dict], batch_size: int = DEFAULT_TABLE_UPSERT_FLUSH,
) -> int:
    count = 0
    for i in range(0, len(records), batch_size):
        batch = records[i: i + batch_size]
        with get_session() as session:
            stmt = insert(MarketIndex).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=["index_code", "trade_date"],
                set_={
                    "index_name": stmt.excluded.index_name,
                    "open": stmt.excluded.open,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "close": stmt.excluded.close,
                    "volume": stmt.excluded.volume,
                    "amount": stmt.excluded.amount,
                    "change": stmt.excluded.change,
                    "change_pct": stmt.excluded.change_pct,
                },
            )
            session.execute(stmt)
        count += len(batch)
        log_upsert_commit("akshare.market_index", len(batch))
    return count


# ====================================================================
# CLI 入口
# ====================================================================

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Akshare 数据同步 CLI")
    parser.add_argument(
        "task",
        choices=[
            "stock_list", "enrich", "exchange_info",
            "stocks_full", "qmt_enrich", "daily", "index", "all",
        ],
        help="stock_list / exchange_info / enrich / stocks_full(一键补全stocks) / qmt_enrich(仅QMT补name/list_date等) / daily / index / all",
    )
    parser.add_argument("--days-back", type=int, default=30, help="日线增量天数 (默认 30)")
    parser.add_argument("--start-date", type=str, default="20230101", help="指数起始日期 (默认 20230101)")
    parser.add_argument(
        "--use-qmt",
        action="store_true",
        help="与 stocks_full 合用: 最后用 QMT 再补 list_date",
    )
    args = parser.parse_args()

    syncer = AkshareDataSync()
    try:
        if args.task in ("stock_list", "all"):
            n = syncer.sync_stock_list()
            logger.info("sync_stock_list => %d", n)

        if args.task == "enrich":
            n = syncer.enrich_stocks_from_spot()
            logger.info("enrich_stocks_from_spot => %d", n)
            n2 = syncer.enrich_stocks_from_spot_sina()
            logger.info("enrich_stocks_from_spot_sina => %d", n2)
            n3 = syncer.enrich_stocks_roe_from_financial_indicator()
            logger.info("enrich_stocks_roe_from_financial_indicator => %d", n3)

        if args.task == "exchange_info":
            n = syncer.enrich_stocks_from_exchange_info()
            logger.info("enrich_stocks_from_exchange_info => %d", n)

        if args.task == "stocks_full":
            r = syncer.sync_stocks_full(use_qmt=args.use_qmt)
            logger.info("sync_stocks_full => %s", r)

        if args.task == "qmt_enrich":
            n = syncer.enrich_stocks_from_qmt()
            logger.info("enrich_stocks_from_qmt => %d", n)

        if args.task in ("daily", "all"):
            n = syncer.sync_daily_incremental(days_back=args.days_back)
            logger.info("sync_daily_incremental => %d", n)

        if args.task in ("index", "all"):
            n = syncer.sync_index_data(start_date=args.start_date)
            logger.info("sync_index_data => %d", n)
    except Exception as exc:
        logger.error("同步失败: %s", exc, exc_info=True)
        sys.exit(1)
