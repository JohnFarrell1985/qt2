"""并发批量下载 A股 + ETF + 指数 日K线数据

多数据源自动降级 (``--source auto`` 默认):
  0. **MiniQMT / xtdata** (本地迅投; 需已安装 ``xtquant`` 并启动 MiniQMT 或 QMT 终端)
  1. 东方财富 (curl_cffi + Chrome指纹 + UA轮换 + 令牌桶限流)
  2. 腾讯财经 (requests 直连; 单次约 500 根 K 线, 已内部分页拉满区间)

**续传 (默认)**: 与 ``akshare_financial_sync.sync_etf_daily`` 一致 —— 落库可能只有**中间一段**时,
会拉 **(MAX+1..今日)** 与 **(地板..MIN-1)**; 且当 ``DATACOLLECT_KLINE_FILL_INTERIOR_GAPS``(默认) 为真时,
再按 XSHG 历补 **MIN~MAX 内** 缺日(关则与旧版相同、不扫中缝). 全队列在 resume 下按区段 (末, 起) 降序.

**ETF 默认近 10 年**: 仅 ``etf`` 模式且未传 ``--days-back`` 时, 地板为约 **3650 自然日前**
(可 ``DATACOLLECT_KLINE_ETF_DAYS_BACK``); 股票/指数单模式未指定时仍为 365. ``all`` 未指定时 ETF 用 10 年、股/指用 1 年.

用法:
    uv run python -m src.data.kline_bulk_sync stock   --days-back 365
    uv run python -m src.data.kline_bulk_sync etf
    uv run python -m src.data.kline_bulk_sync index   --days-back 365
    uv run python -m src.data.kline_bulk_sync all     --days-back 365 --concurrency 8
    uv run python -m src.data.kline_bulk_sync all     --days-back 365 --source tencent
    uv run python -m src.data.kline_bulk_sync stock   --no-resume
    uv run python -m src.data.kline_bulk_sync stock   --source qmt
    # 配置见 ``QMT_PATH`` (``env/.env.qmt``), 与全项目 QMT 一致
"""
from __future__ import annotations

import asyncio
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any

import pandas as pd

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

from src.common.config import settings
from src.common.db import get_session
from src.common.db_batch import DEFAULT_TABLE_UPSERT_FLUSH, log_upsert_commit
from src.common.logger import get_logger
from src.data.models import ETFDaily, ETFInfo, MarketIndex, StockDaily, Stock

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

# ==================================================================
# 数据源 1: 东方财富 (完整字段, 需反反爬)
# ==================================================================
_EM_KLINE_URL = "https://push2his.eastmoney.com/api/qt/stock/kline/get"
_EM_FIELDS1 = "f1,f2,f3,f4,f5,f6,f7,f8,f9,f10,f11,f12,f13"
_EM_FIELDS2 = "f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"

_em_client = None
_em_limiter = None


def _get_em_client():
    global _em_client
    if _em_client is None:
        from src.datacollect.client import SmartHttpClient
        _em_client = SmartHttpClient()
    return _em_client


def _get_em_limiter(rate: float = 3.0, burst: int = 5):
    global _em_limiter
    if _em_limiter is None:
        from src.datacollect.rate_limiter import TokenBucketLimiter
        _em_limiter = TokenBucketLimiter.for_domain(
            "eastmoney_bulk", rate=rate, burst=burst,
        )
    return _em_limiter


def _em_stock_secid(code: str) -> str:
    return f"1.{code}" if code.startswith("6") else f"0.{code}"


def _em_etf_secid(code: str) -> str:
    pure = code.split(".")[0]
    prefix = pure[:2]
    if prefix in ("51", "58", "56", "52", "53"):
        return f"1.{pure}"
    return f"0.{pure}"


def _em_index_secid(code: str) -> str:
    return f"0.{code}" if code.startswith("399") else f"1.{code}"


def _em_fetch_kline(
    secid: str, start_date: str, end_date: str, *, quick_fail: bool = False,
) -> list[list[str]]:
    """东方财富 K线 API, 返回原始行 [date, open, close, high, low, vol, amount, amp, pct, chg, turnover].

    默认走 ``SmartHttpClient`` 重试 (``DATACOLLECT_MAX_RETRIES``, 默认 3 次); 仍失败则熔断东财并返回空,
    由上层级联改试腾讯等. ``quick_fail=True`` 时单次请求且异常向上抛 (测试/特殊场景).
    若已熔断或 ``_probe_em()`` 判不可达, 直接空返回.
    """
    if _em_push2his_circuit_open:
        return []
    if not _probe_em():
        return []
    limiter = _get_em_limiter()
    limiter.acquire()
    client = _get_em_client()
    params = {
        "secid": secid, "klt": "101", "fqt": "1", "lmt": "0",
        "beg": start_date, "end": end_date,
        "fields1": _EM_FIELDS1, "fields2": _EM_FIELDS2,
    }
    try:
        resp = client.get(_EM_KLINE_URL, params=params, skip_retry=quick_fail)
    except Exception as e:
        if quick_fail:
            raise
        _trip_em_push2his(str(e))
        return []
    body: dict = resp.json()
    if body.get("rc") not in (0, None):
        return []
    klines = body.get("data", {}).get("klines") or []
    return [line.split(",")[:11] for line in klines if len(line.split(",")) >= 11]


# ==================================================================
# 数据源 2: 腾讯财经 (OHLCV, 无需反爬)
# ==================================================================
_QQ_KLINE_URL = "https://web.ifzq.gtimg.cn/appstock/app/fqkline/get"

_qq_session = None
_qq_limiter = None


def _get_qq_session():
    """腾讯 K 线 requests Session.

    - 若 ``DATACOLLECT_PROXY_URL`` 非空: 只走该 HTTP(S) 代理
    - 否则 ``trust_env=True`` 以便使用系统/环境变量中的代理 (公司网常见)
    """
    global _qq_session
    if _qq_session is None:
        import requests

        from src.common.config import settings

        _qq_session = requests.Session()
        proxy = (getattr(settings.datacollect, "proxy_url", None) or "").strip()
        if proxy:
            _qq_session.trust_env = False
            _qq_session.proxies = {"http": proxy, "https": proxy}
        else:
            _qq_session.proxies = {}
            # 与 curl_cffi 手填代理区分: 无显式配置时允许 HTTP(S)_PROXY
            _qq_session.trust_env = True
        _qq_session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Referer": "https://stockapp.finance.qq.com/",
        })
    return _qq_session


def _get_qq_limiter(rate: float = 10.0, burst: int = 15):
    """腾讯财经限流: 默认 10 req/s, burst=15 (宽松但有保护)."""
    global _qq_limiter
    if _qq_limiter is None:
        from src.datacollect.rate_limiter import TokenBucketLimiter
        _qq_limiter = TokenBucketLimiter.for_domain(
            "tencent_finance", rate=rate, burst=burst,
        )
    return _qq_limiter


def _qq_symbol(code: str, asset_type: str = "stock") -> str:
    """Convert code to Tencent symbol format (sh/sz prefix)."""
    pure = code.split(".")[0]
    if asset_type == "index":
        return f"sz{pure}" if pure.startswith("399") else f"sh{pure}"
    if pure.startswith(("6", "5", "9")):
        return f"sh{pure}"
    return f"sz{pure}"


def _qq_fetch_kline_once(symbol: str, start_date: str, end_date: str) -> list[list[str]]:
    """单请求腾讯 K 线, 单次 **最多约 500 根**, 与参数里 500 一致。"""
    _get_qq_limiter().acquire()
    s_fmt = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
    e_fmt = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
    session = _get_qq_session()
    resp = session.get(
        _QQ_KLINE_URL,
        params={"param": f"{symbol},day,{s_fmt},{e_fmt},500,qfq"},
        timeout=15,
    )
    body = resp.json()
    data = body.get("data", {})
    if not data:
        return []
    sym_data = data.get(symbol, {})
    rows = sym_data.get("qfqday") or []
    if not rows and sym_data.get("day"):
        logger.warning("腾讯 K 线 %s 无 qfqday, 跳过未复权 day 数据", symbol)
    return rows


def _qq_fetch_kline(symbol: str, start_date: str, end_date: str) -> list[list[str]]:
    """腾讯 K 线: **分页拼接** 直到覆盖 [start_date,end_date], 解决单次 500 根截断导致只约 2 年数据."""
    d_end = datetime.strptime(end_date, "%Y%m%d")
    all_rows: list[list[str]] = []
    by_date: dict[str, list[str]] = {}
    cur_s = start_date
    for _ in range(200):
        part = _qq_fetch_kline_once(symbol, cur_s, end_date)
        if not part:
            break
        for row in part:
            if not row or len(row) < 1:
                continue
            by_date[row[0]] = row
        last_d = _safe_date(part[-1][0])
        if not last_d:
            break
        if last_d >= d_end.date():
            break
        if len(part) < 500:
            break
        nxt = last_d + timedelta(days=1)
        cur_s = nxt.strftime("%Y%m%d")
    all_rows = [by_date[k] for k in sorted(by_date.keys())]
    return all_rows


# ==================================================================
# 辅助函数
# ==================================================================

def _safe_float(v: Any) -> float | None:
    try:
        return float(v)
    except (ValueError, TypeError):
        return None


def _safe_int(v: Any) -> int | None:
    try:
        return int(float(v))
    except (ValueError, TypeError):
        return None


def _safe_date(v: str) -> date | None:
    try:
        return datetime.strptime(v, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


# ==================================================================
# 健康探测: 检测 eastmoney 是否可达
# ==================================================================
_em_healthy: bool | None = None
# 级联里东财曾连接失败时本进程内不再打 push2his (避免每段都 tenacity 重试)
_em_push2his_circuit_open: bool = False
_qmt_healthy: bool | None = None  # MiniQMT / xtdata 可用性 (与 reset_em_cache 一并重置)
# 是否已打 ETF 板块只数 vs 阈值的说明日志 (与 reset 一并清, 新任务可再打一次)
_qmt_etf_diagnostics_logged: bool = False


def reset_em_cache() -> None:
    """清东财探测缓存、MiniQMT 可达缓存与 ``fetch_etf_daily_cascade`` 用的 push2his 熔断.

    首次探测若因网络/代理失败, 会整段退回腾讯; ``sync_etf_daily`` 等入口
    每任务开始调用, 避免「一次失败, 全程只爬腾讯」; 同次重置熔断以便新任务可再试东财.
    亦重置 ``_qmt_healthy`` / ETF 板块诊断日志标记, 避免误缓存.
    """
    global _em_healthy, _em_push2his_circuit_open, _qmt_healthy, _qmt_etf_diagnostics_logged
    _em_healthy = None
    _qmt_healthy = None
    _qmt_etf_diagnostics_logged = False
    _em_push2his_circuit_open = False


def reset_qq_session() -> None:
    """下次腾讯 K 线请求重建 ``requests.Session`` (改 ``DATACOLLECT_PROXY_URL`` 后需新进程或调此)."""
    global _qq_session
    _qq_session = None


def _trip_em_push2his(reason: str) -> None:
    """东财 push2his 在当前进程内熔断 (``SmartHttpClient`` 已重试 ``max_retries`` 次)。"""
    global _em_push2his_circuit_open, _em_healthy
    if _em_push2his_circuit_open:
        return
    _em_push2his_circuit_open = True
    _em_healthy = False
    logger.info(
        "东财 push2his 重试 %d 次后放弃, 本进程内改走腾讯等备用源: %s",
        settings.datacollect.max_retries,
        reason,
    )


def _probe_em() -> bool:
    """探测 push2his.eastmoney.com 是否可用 (缓存结果)。"""
    global _em_healthy
    if _em_healthy is not None:
        return _em_healthy
    try:
        client = _get_em_client()
        _get_em_limiter().acquire()
        resp = client.get(
            _EM_KLINE_URL,
            params={
                "secid": "1.000300", "klt": "101", "fqt": "1",
                "lmt": "0", "beg": "20260410", "end": "20260413",
                "fields1": _EM_FIELDS1, "fields2": _EM_FIELDS2,
            },
        )
        body = resp.json()
        _em_healthy = body.get("rc") in (0, None)
    except Exception as e:
        logger.warning("东方财富探测失败, 将使用腾讯数据源: %s", e)
        _em_healthy = False
    logger.info("东方财富可达: %s", _em_healthy)
    return _em_healthy


# ==================================================================
# MiniQMT / xtdata (与 QMTClient 相同入口; 与 download_engine 行为一致)
# ==================================================================
_kline_qmt_client: Any = None
_qmt_kline_lock = threading.Lock()
_QMT_FETCH_TIMEOUT_SEC = 180


def _get_kline_qmt_client() -> Any:
    global _kline_qmt_client
    if _kline_qmt_client is None:
        from src.data.qmt_client import QMTClient

        _kline_qmt_client = QMTClient()
    return _kline_qmt_client


def _probe_qmt() -> bool:
    """本进程内缓存: 能否加载 xtdata 并连接 (MiniQMT/标准 QMT)。"""
    global _qmt_healthy
    if _qmt_healthy is not None:
        return _qmt_healthy
    try:
        c = _get_kline_qmt_client()
        _ = c.xtdata
        _qmt_healthy = True
    except Exception as e:
        logger.warning("xtdata (MiniQMT) 不可用, 日线将走东财/腾讯: %s", e)
        _qmt_healthy = False
    logger.info("xtdata (MiniQMT) 可用: %s", _qmt_healthy)
    return _qmt_healthy


def probe_qmt_etf_sector_size() -> tuple[int, str]:
    """QMT 中 ETF 板块可列出的合约数 (与本地行情覆盖相关). 失败返回 (0, 原因)。"""
    try:
        c = _get_kline_qmt_client()
        for name in ("沪深ETF", "ETF", "全部ETF"):
            try:
                codes = c.get_stock_list_in_sector(name)
            except Exception:
                continue
            n = len(codes) if codes else 0
            if n > 0:
                return n, name
        return 0, "无可用ETF板块"
    except Exception as e:
        return 0, str(e)


def _log_etf_qmt_sector_diagnostics_if_needed() -> None:
    """在已会走 QMT 的上下文中, 进程内至多打一次 ETF 板块只数与 ``DATACOLLECT_QMT_ETF_MIN_SECTOR_SIZE`` 对比.

    只用于观测, **不**再作为「是否先拉 MiniQMT」的门槛 (与股票 auto 一致: 只要 ``_probe_qmt()`` 为真即先试 xtdata).
    """
    global _qmt_etf_diagnostics_logged
    if _qmt_etf_diagnostics_logged:
        return
    _qmt_etf_diagnostics_logged = True
    n, label = probe_qmt_etf_sector_size()
    threshold = int(getattr(settings.datacollect, "qmt_etf_min_sector_size", 1500))
    logger.info(
        "ETF 日线: QMT 板块「%s」%d 只, 配置阈值 %d(仅参考); 仍优先 MiniQMT, 无数据再落网页多源",
        label,
        n,
        threshold,
    )


def _qmt_code_stock_etf(code: str) -> str:
    c = (code or "").strip()
    if "." in c:
        return c
    # 港股通: 5 位数字 (或 HK 前缀) → QMT 符号 ``00700.HK``
    clean = c.upper().replace("HK", "").strip()
    if clean.isdigit() and len(clean) <= 5:
        return f"{clean.zfill(5)}.HK"
    pure = c[:6]
    if not pure:
        return c
    if pure.startswith(("6", "5", "9")):
        return f"{pure}.SH"
    return f"{pure}.SZ"


def _qmt_code_index(code: str) -> str:
    pure = (code or "").split(".")[0]
    if pure.startswith("399"):
        return f"{pure}.SZ"
    return f"{pure}.SH"


def _qmt_ts_to_date(ts: Any) -> date | None:
    if isinstance(ts, pd.Timestamp):
        return ts.date()
    s = str(ts)
    if len(s) >= 10 and s[4] == "-":
        return _safe_date(s[:10])
    s2 = "".join(ch for ch in s if ch.isdigit())[:8]
    if len(s2) == 8:
        try:
            return datetime.strptime(s2, "%Y%m%d").date()
        except ValueError:
            return None
    return None


def _qmt_clip_df(
    df: pd.DataFrame, start_ymd: str, end_ymd: str,
) -> pd.DataFrame:
    s = datetime.strptime(start_ymd[:8], "%Y%m%d").date()
    e = datetime.strptime(end_ymd[:8], "%Y%m%d").date()
    out: list[pd.Timestamp] = []
    for ts in df.index:
        d = _qmt_ts_to_date(ts)
        if d is not None and s <= d <= e:
            out.append(ts)
    if not out:
        return df.iloc[0:0]
    return df.loc[out]


def _qmt_df_to_stock_records(
    code: str, df: pd.DataFrame, start_ymd: str, end_ymd: str,
) -> list[dict]:
    df2 = _qmt_clip_df(df, start_ymd, end_ymd)
    if df2.empty:
        return []
    df2 = df2.sort_index()
    records: list[dict] = []
    prev_close: float | None = None
    for ts, row in df2.iterrows():
        td = _qmt_ts_to_date(ts)
        if not td:
            continue
        op = _safe_float(row.get("open"))
        hi = _safe_float(row.get("high"))
        lo = _safe_float(row.get("low"))
        close_val = _safe_float(row.get("close"))
        vol = _safe_int(row.get("volume"))
        amt: float | None
        if "amount" in row.index:
            amt = _safe_float(row.get("amount"))
        else:
            amt = None
        chg = (close_val - prev_close) if close_val and prev_close else None
        pct = (chg / prev_close * 100) if chg and prev_close else _safe_float(row.get("change_pct"))
        records.append({
            "code": code, "trade_date": td,
            "open": op, "close": close_val,
            "high": hi, "low": lo,
            "volume": vol, "amount": amt,
            "amplitude": _safe_float(row.get("amplitude")),
            "change_pct": pct, "change": chg,
            "turnover_rate": _safe_float(
                row.get("turnover_rate") or row.get("turnover"),
            ),
        })
        prev_close = close_val
    return records


def _qmt_df_to_etf_records(
    code: str, df: pd.DataFrame, start_ymd: str, end_ymd: str,
) -> list[dict]:
    df2 = _qmt_clip_df(df, start_ymd, end_ymd)
    if df2.empty:
        return []
    records: list[dict] = []
    for ts, row in df2.sort_index().iterrows():
        td = _qmt_ts_to_date(ts)
        if not td:
            continue
        amt: float | None
        if "amount" in row.index:
            amt = _safe_float(row.get("amount"))
        else:
            amt = None
        records.append({
            "code": code, "trade_date": td,
            "open": _safe_float(row.get("open")),
            "close": _safe_float(row.get("close")),
            "high": _safe_float(row.get("high")),
            "low": _safe_float(row.get("low")),
            "volume": _safe_int(row.get("volume")),
            "amount": amt,
        })
    return records


def _qmt_df_to_index_records(
    index_key: str, index_name: str, df: pd.DataFrame, start_ymd: str, end_ymd: str,
) -> list[dict]:
    df2 = _qmt_clip_df(df, start_ymd, end_ymd)
    if df2.empty:
        return []
    records: list[dict] = []
    prev_close: float | None = None
    for ts, row in df2.sort_index().iterrows():
        td = _qmt_ts_to_date(ts)
        if not td:
            continue
        close_val = _safe_float(row.get("close"))
        chg = (close_val - prev_close) if close_val and prev_close else None
        pct = (chg / prev_close * 100) if chg and prev_close else _safe_float(
            row.get("change_pct"),
        )
        amt: float | None
        if "amount" in row.index:
            amt = _safe_float(row.get("amount"))
        else:
            amt = None
        records.append({
            "index_code": index_key, "index_name": index_name, "trade_date": td,
            "open": _safe_float(row.get("open")), "close": close_val,
            "high": _safe_float(row.get("high")), "low": _safe_float(row.get("low")),
            "volume": _safe_int(row.get("volume")), "amount": amt,
            "change": chg, "change_pct": pct,
        })
        prev_close = close_val
    return records


def _qmt_fetch_stock(code: str, start_date: str, end_date: str) -> list[dict]:
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout

    def _do_fetch() -> list[dict]:
        sym = _qmt_code_stock_etf(code)
        c = _get_kline_qmt_client()
        with _qmt_kline_lock:
            c.download_history_data(
                sym, "1d",
                start_time=start_date[:8], end_time=end_date[:8],
            )
            data = c.get_market_data_ex(
                [sym], period="1d",
                start_time=start_date[:8], end_time=end_date[:8],
                dividend_type="front",
            )
        df = data.get(sym) if isinstance(data, dict) else None
        if df is None or (hasattr(df, "empty") and df.empty):
            return []
        return _qmt_df_to_stock_records(code, df, start_date, end_date)

    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(_do_fetch)
        try:
            return fut.result(timeout=_QMT_FETCH_TIMEOUT_SEC)
        except FutTimeout:
            logger.warning(
                "QMT K线超时 %ss, 跳过 %s %s~%s",
                _QMT_FETCH_TIMEOUT_SEC, code, start_date, end_date,
            )
            return []


def _qmt_fetch_etf(code: str, start_date: str, end_date: str) -> list[dict]:
    sym = _qmt_code_stock_etf(code)
    c = _get_kline_qmt_client()
    with _qmt_kline_lock:
        c.download_history_data(
            sym, "1d",
            start_time=start_date[:8], end_time=end_date[:8],
        )
        data = c.get_market_data_ex(
            [sym], period="1d",
            start_time=start_date[:8], end_time=end_date[:8],
            dividend_type="front",
        )
    df = data.get(sym) if isinstance(data, dict) else None
    if df is None or (hasattr(df, "empty") and df.empty):
        return []
    return _qmt_df_to_etf_records(code, df, start_date, end_date)


def _qmt_fetch_index(code: str, start_date: str, end_date: str) -> list[dict]:
    sym = _qmt_code_index(code)
    name = INDEX_NAME_MAP.get(code, code)
    c = _get_kline_qmt_client()
    with _qmt_kline_lock:
        c.download_history_data(
            sym, "1d",
            start_time=start_date[:8], end_time=end_date[:8],
        )
        data = c.get_market_data_ex(
            [sym], period="1d",
            start_time=start_date[:8], end_time=end_date[:8],
            dividend_type="front",
        )
    df = data.get(sym) if isinstance(data, dict) else None
    if df is None or (hasattr(df, "empty") and df.empty):
        return []
    return _qmt_df_to_index_records(code, name, df, start_date, end_date)


def _etf_sina_symbol(full_code: str) -> str:
    num = (full_code or "").split(".")[0]
    if (full_code or "").upper().endswith(".SH"):
        return f"sh{num}"
    return f"sz{num}"


def _map_etf_daily_rows(df: pd.DataFrame, code: str) -> list[dict]:
    """akshare 风格列 (日期/开收高低成交量额) → ``etf_daily`` 行."""
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
        raw = row.get("日期")
        if raw is not None and hasattr(raw, "date"):
            trade_date = raw.date()
        else:
            trade_date = _safe_date(str(raw)[:10]) if raw is not None else None
        if trade_date is None:
            continue
        rec: dict[str, Any] = {"code": code, "trade_date": trade_date}
        for cn_col, db_col in col_map.items():
            if db_col == "trade_date":
                continue
            val = row.get(cn_col)
            if db_col == "volume":
                if val is not None and not (isinstance(val, float) and pd.isna(val)):
                    rec[db_col] = int(val)
                else:
                    rec[db_col] = None
            else:
                rec[db_col] = _safe_float(val)
        records.append(rec)
    return records


def _sina_fetch_etf(code: str, start_date: str, end_date: str) -> list[dict]:
    try:
        import akshare as ak
    except ImportError:
        return []
    try:
        df2 = ak.fund_etf_hist_sina(symbol=_etf_sina_symbol(code))
    except Exception as e:  # noqa: BLE001
        logger.debug("新浪 ETF 日线 %s: %s", code, e)
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
        f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:8]}",
    )
    end_d = _safe_date(
        f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:8]}",
    )
    if start_d is not None:
        out = out[out["日期"] >= pd.Timestamp(start_d)]
    if end_d is not None:
        out = out[out["日期"] <= pd.Timestamp(end_d)]
    return _map_etf_daily_rows(out, code)


def _web_fetch_etf_cascade(code: str, start_date: str, end_date: str) -> list[dict]:
    """腾讯/新浪/东财, 有数据即停. 东财最多 ``max_retries`` 次后熔断, 不再每段重试刷屏。"""
    order: list[tuple[str, Any]] = [
        ("tencent", lambda: _qq_fetch_etf(code, start_date, end_date)),
        ("sina", lambda: _sina_fetch_etf(code, start_date, end_date)),
    ]
    if _probe_em() and not _em_push2his_circuit_open:
        order.insert(0, ("eastmoney", lambda: _em_fetch_etf(code, start_date, end_date)))
    for label, fn in order:
        try:
            rows = fn()
        except Exception as e:  # noqa: BLE001
            logger.debug("ETF %s %s: %s", code, label, e)
            continue
        if rows:
            return rows
    return []


def _web_fetch_stock(code: str, start_date: str, end_date: str) -> list[dict]:
    """东财 (``max_retries`` 次) → 腾讯; 东财熔断后仅腾讯。"""
    if not _em_push2his_circuit_open and _probe_em():
        rows = _em_fetch_stock(code, start_date, end_date)
        if rows:
            return rows
    return _qq_fetch_stock(code, start_date, end_date)


def _web_fetch_index(code: str, start_date: str, end_date: str) -> list[dict]:
    """东财 (``max_retries`` 次) → 腾讯; 东财熔断后仅腾讯。"""
    if not _em_push2his_circuit_open and _probe_em():
        rows = _em_fetch_index(code, start_date, end_date)
        if rows:
            return rows
    return _qq_fetch_index(code, start_date, end_date)


# ==================================================================
# 标的拉取 (线程池中运行) — 自动选择数据源
# ==================================================================

def _fetch_stock_daily(code: str, start_date: str, end_date: str) -> list[dict]:
    source = _active_source
    if source == "qmt":
        if not _probe_qmt():
            return []
        try:
            return _qmt_fetch_stock(code, start_date, end_date)
        except Exception as e:
            logger.warning("QMT 股票日线 %s %s~%s: %s", code, start_date, end_date, e)
            return []
    if source == "auto":
        if _probe_qmt():
            try:
                qrows = _qmt_fetch_stock(code, start_date, end_date)
                if qrows:
                    return qrows
            except Exception as e:
                logger.debug(
                    "QMT 股票日线 %s %s~%s: %s", code, start_date, end_date, e,
                )
        return _web_fetch_stock(code, start_date, end_date)
    if source == "eastmoney":
        rows = _em_fetch_stock(code, start_date, end_date)
        if rows:
            return rows
        if _em_push2his_circuit_open:
            return _qq_fetch_stock(code, start_date, end_date)
        return []
    return _qq_fetch_stock(code, start_date, end_date)


def _fetch_etf_daily(code: str, start_date: str, end_date: str) -> list[dict]:
    source = _active_source
    if source == "qmt":
        if not _probe_qmt():
            return []
        try:
            return _qmt_fetch_etf(code, start_date, end_date)
        except Exception as e:
            logger.warning("QMT ETF 日线 %s %s~%s: %s", code, start_date, end_date, e)
            return []
    if source == "auto":
        if _probe_qmt():
            _log_etf_qmt_sector_diagnostics_if_needed()
            try:
                qrows = _qmt_fetch_etf(code, start_date, end_date)
                if qrows:
                    return qrows
            except Exception as e:
                logger.debug(
                    "QMT ETF 日线 %s %s~%s: %s", code, start_date, end_date, e,
                )
        return _web_fetch_etf_cascade(code, start_date, end_date)
    if source == "eastmoney":
        return _em_fetch_etf(code, start_date, end_date)
    return _qq_fetch_etf(code, start_date, end_date)


def fetch_etf_daily_cascade(
    code: str,
    start_date: str,
    end_date: str,
    *,
    kline_prefer: str = "auto",
) -> tuple[list[dict], str | None]:
    """MiniQMT (xtdata) / 东财 / 腾讯; ``kline_prefer=auto`` 时 **优先本地 QMT**, 再按东财/腾讯.

    东财在级联中走 ``SmartHttpClient`` 默认重试 (``max_retries``); 仍失败则熔断 push2his,
    本进程内后续段不再打东财 K 线 URL, 直接试腾讯/新浪.

    返回 ``(rows, tag)`` — tag 为 ``kline_qmt`` / ``kline_eastmoney`` / ``kline_tencent`` 等; 全失败 ``[]``, ``None``。
    """
    if kline_prefer not in ("eastmoney", "tencent", "auto", "qmt"):
        raise ValueError("kline_prefer 须为 eastmoney / tencent / auto / qmt")

    def _em() -> list[dict]:
        if _em_push2his_circuit_open:
            return []
        return _em_fetch_etf(code, start_date, end_date)

    def _qq() -> list[dict]:
        return _qq_fetch_etf(code, start_date, end_date)

    def _qmt() -> list[dict]:
        if not _probe_qmt():
            return []
        try:
            return _qmt_fetch_etf(code, start_date, end_date)
        except Exception:  # noqa: BLE001
            return []

    def _sina() -> list[dict]:
        return _sina_fetch_etf(code, start_date, end_date)

    if kline_prefer == "eastmoney":
        order = (
            ("kline_eastmoney", _em),
            ("kline_tencent", _qq),
            ("kline_sina", _sina),
        )
    elif kline_prefer == "tencent":
        order = (
            ("kline_tencent", _qq),
            ("kline_eastmoney", _em),
            ("kline_sina", _sina),
        )
    elif kline_prefer == "qmt":
        order = (
            ("kline_qmt", _qmt),
            ("kline_eastmoney", _em),
            ("kline_tencent", _qq),
            ("kline_sina", _sina),
        )
    else:  # auto: xtdata 可用则先 QMT, 再东财/腾讯/新浪
        olist: list[tuple[str, Any]] = []
        if _probe_qmt():
            _log_etf_qmt_sector_diagnostics_if_needed()
            olist.append(("kline_qmt", _qmt))
        if _probe_em():
            olist.append(("kline_eastmoney", _em))
            olist.append(("kline_tencent", _qq))
        else:
            olist.append(("kline_tencent", _qq))
            olist.append(("kline_eastmoney", _em))
        olist.append(("kline_sina", _sina))
        order = tuple(olist)

    for name, fn in order:
        try:
            rows = fn()
        except Exception as e:  # noqa: BLE001
            logger.debug(
                "ETF K线 %s %s 段 %s~%s: %s", name, code, start_date, end_date, e,
            )
            continue
        if rows:
            return rows, name
    return [], None


def _fetch_index_daily(code: str, start_date: str, end_date: str) -> list[dict]:
    source = _active_source
    if source == "qmt":
        if not _probe_qmt():
            return []
        try:
            return _qmt_fetch_index(code, start_date, end_date)
        except Exception as e:
            logger.warning("QMT 指数日线 %s %s~%s: %s", code, start_date, end_date, e)
            return []
    if source == "auto":
        if _probe_qmt():
            try:
                qrows = _qmt_fetch_index(code, start_date, end_date)
                if qrows:
                    return qrows
            except Exception as e:
                logger.debug(
                    "QMT 指数日线 %s %s~%s: %s", code, start_date, end_date, e,
                )
        return _web_fetch_index(code, start_date, end_date)
    if source == "eastmoney":
        rows = _em_fetch_index(code, start_date, end_date)
        if rows:
            return rows
        if _em_push2his_circuit_open:
            return _qq_fetch_index(code, start_date, end_date)
        return []
    return _qq_fetch_index(code, start_date, end_date)


_active_source: str = "auto"


# -- Eastmoney 实现 --

def _em_fetch_stock(code: str, start_date: str, end_date: str) -> list[dict]:
    rows = _em_fetch_kline(_em_stock_secid(code), start_date, end_date)
    records: list[dict] = []
    for p in rows:
        td = _safe_date(p[0])
        if not td:
            continue
        records.append({
            "code": code, "trade_date": td,
            "open": _safe_float(p[1]), "close": _safe_float(p[2]),
            "high": _safe_float(p[3]), "low": _safe_float(p[4]),
            "volume": _safe_int(p[5]), "amount": _safe_float(p[6]),
            "amplitude": _safe_float(p[7]), "change_pct": _safe_float(p[8]),
            "change": _safe_float(p[9]), "turnover_rate": _safe_float(p[10]),
        })
    return records


def _em_fetch_etf(
    code: str, start_date: str, end_date: str, *, quick_fail: bool = False,
) -> list[dict]:
    rows = _em_fetch_kline(
        _em_etf_secid(code), start_date, end_date, quick_fail=quick_fail,
    )
    records: list[dict] = []
    for p in rows:
        td = _safe_date(p[0])
        if not td:
            continue
        records.append({
            "code": code, "trade_date": td,
            "open": _safe_float(p[1]), "close": _safe_float(p[2]),
            "high": _safe_float(p[3]), "low": _safe_float(p[4]),
            "volume": _safe_int(p[5]), "amount": _safe_float(p[6]),
        })
    return records


def _em_fetch_index(code: str, start_date: str, end_date: str) -> list[dict]:
    rows = _em_fetch_kline(_em_index_secid(code), start_date, end_date)
    index_name = INDEX_NAME_MAP.get(code, code)
    records: list[dict] = []
    prev_close: float | None = None
    for p in rows:
        td = _safe_date(p[0])
        if not td:
            continue
        close_val = _safe_float(p[2])
        chg = (close_val - prev_close) if close_val and prev_close else None
        pct = (chg / prev_close * 100) if chg and prev_close else None
        records.append({
            "index_code": code, "index_name": index_name, "trade_date": td,
            "open": _safe_float(p[1]), "close": close_val,
            "high": _safe_float(p[3]), "low": _safe_float(p[4]),
            "volume": _safe_int(p[5]), "amount": _safe_float(p[6]),
            "change": chg, "change_pct": pct,
        })
        prev_close = close_val
    return records


# -- Tencent 实现 --

def _qq_fetch_stock(code: str, start_date: str, end_date: str) -> list[dict]:
    symbol = _qq_symbol(code, "stock")
    rows = _qq_fetch_kline(symbol, start_date, end_date)
    records: list[dict] = []
    prev_close: float | None = None
    for p in rows:
        td = _safe_date(p[0])
        if not td:
            continue
        close_val = _safe_float(p[2])
        chg = (close_val - prev_close) if close_val and prev_close else None
        pct = (chg / prev_close * 100) if chg and prev_close else None
        records.append({
            "code": code, "trade_date": td,
            "open": _safe_float(p[1]), "close": close_val,
            "high": _safe_float(p[3]), "low": _safe_float(p[4]),
            "volume": _safe_int(p[5]), "amount": None,
            "amplitude": None, "change_pct": pct,
            "change": chg, "turnover_rate": None,
        })
        prev_close = close_val
    return records


def _qq_fetch_etf(code: str, start_date: str, end_date: str) -> list[dict]:
    pure = code.split(".")[0]
    symbol = _qq_symbol(pure, "stock")
    rows = _qq_fetch_kline(symbol, start_date, end_date)
    records: list[dict] = []
    for p in rows:
        td = _safe_date(p[0])
        if not td:
            continue
        records.append({
            "code": code, "trade_date": td,
            "open": _safe_float(p[1]), "close": _safe_float(p[2]),
            "high": _safe_float(p[3]), "low": _safe_float(p[4]),
            "volume": _safe_int(p[5]), "amount": None,
        })
    return records


def _qq_fetch_index(code: str, start_date: str, end_date: str) -> list[dict]:
    symbol = _qq_symbol(code, "index")
    rows = _qq_fetch_kline(symbol, start_date, end_date)
    index_name = INDEX_NAME_MAP.get(code, code)
    records: list[dict] = []
    prev_close: float | None = None
    for p in rows:
        td = _safe_date(p[0])
        if not td:
            continue
        close_val = _safe_float(p[2])
        chg = (close_val - prev_close) if close_val and prev_close else None
        pct = (chg / prev_close * 100) if chg and prev_close else None
        records.append({
            "index_code": code, "index_name": index_name, "trade_date": td,
            "open": _safe_float(p[1]), "close": close_val,
            "high": _safe_float(p[3]), "low": _safe_float(p[4]),
            "volume": _safe_int(p[5]), "amount": None,
            "change": chg, "change_pct": pct,
        })
        prev_close = close_val
    return records


# ==================================================================
# 批量 upsert
# ==================================================================

def _bulk_upsert_stock_daily(
    records: list[dict], batch_size: int = DEFAULT_TABLE_UPSERT_FLUSH,
) -> None:
    if not records:
        return
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
        log_upsert_commit("kline.stock_daily", len(batch))


def _bulk_upsert_etf_daily(
    records: list[dict], batch_size: int = DEFAULT_TABLE_UPSERT_FLUSH,
) -> None:
    if not records:
        return
    with get_session() as session:
        for i in range(0, len(records), batch_size):
            batch = records[i: i + batch_size]
            stmt = insert(ETFDaily).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=["code", "trade_date"],
                set_={
                    "open": stmt.excluded.open,
                    "high": stmt.excluded.high,
                    "low": stmt.excluded.low,
                    "close": stmt.excluded.close,
                    "volume": stmt.excluded.volume,
                    "amount": stmt.excluded.amount,
                },
            )
            session.execute(stmt)
            log_upsert_commit("kline.etf_daily", len(batch))


def _bulk_upsert_index_daily(
    records: list[dict], batch_size: int = DEFAULT_TABLE_UPSERT_FLUSH,
) -> None:
    if not records:
        return
    with get_session() as session:
        for i in range(0, len(records), batch_size):
            batch = records[i: i + batch_size]
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
            log_upsert_commit("kline.market_index", len(batch))


# ==================================================================
# 异步并发调度
# ==================================================================

async def _async_download(
    tasks: list[tuple[str, str, str]],
    fetch_fn,
    upsert_fn,
    label: str,
    concurrency: int = 8,
    flush_every: int = 200,
):
    sem = asyncio.Semaphore(concurrency)
    loop = asyncio.get_running_loop()

    total_records = 0
    total_done = 0
    total_failed = 0
    buffer: list[dict] = []
    t0 = time.time()

    async def _worker(code: str, start: str, end: str):
        nonlocal total_records, total_done, total_failed, buffer
        async with sem:
            await asyncio.sleep(0.02)
            try:
                records = await loop.run_in_executor(None, fetch_fn, code, start, end)
            except Exception as e:
                total_failed += 1
                logger.debug("[%s] %s failed: %s", label, code, e)
                return
            total_done += 1
            if records:
                buffer.extend(records)
                total_records += len(records)

    n = len(tasks)
    logger.info("[%s] 开始并发下载, %d 个标的, concurrency=%d, source=%s",
                label, n, concurrency, _active_source)

    for batch_start in range(0, n, flush_every):
        batch_end = min(batch_start + flush_every, n)
        batch_tasks = tasks[batch_start:batch_end]

        aws = [_worker(code, s, e) for code, s, e in batch_tasks]
        await asyncio.gather(*aws)

        if buffer:
            upsert_fn(buffer)
            buffer = []

        elapsed = time.time() - t0
        rate = total_done / elapsed if elapsed > 0 else 0
        logger.info(
            "[%s] 进度: %d/%d (%.1f/s), 累计 %d 条, 失败 %d, %.0fs",
            label, batch_end, n, rate, total_records, total_failed, elapsed,
        )

    if buffer:
        upsert_fn(buffer)

    elapsed = time.time() - t0
    logger.info(
        "[%s] 完成: %d 个标的, %d 条记录, 失败 %d, 耗时 %.0fs",
        label, total_done, total_records, total_failed, elapsed,
    )
    return total_records


# ==================================================================
# 任务构建: 与 sync_etf_daily 的续传语义一致 (中间段 + 向今 + 向史)
# ==================================================================


def _row_date_to_ymd(v: Any) -> str | None:
    if v is None:
        return None
    if hasattr(v, "strftime"):
        return v.strftime("%Y%m%d")
    s = str(v)[:10].replace("-", "")
    return s[:8] if len(s) >= 8 else None


def kline_per_code_floor(
    global_start: str,
    establish: Any,
    earliest_ymd_in_db: str | None = None,
) -> str:
    """单标的有效地板: ``max(用户 floor, 上市/成立日)``; 可用库内最早日纠偏 (与 etf 侧一致)。"""
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


def daily_kline_work_segments(
    floor_start: str,
    end_date: str,
    last_ymd: str | None,
    first_ymd: str | None,
    resume: bool,
) -> list[tuple[str, str]]:
    """缺段列表: 无库为 ``[(floor, end)]``; 有库时向今 + 向史, 顺序 **先今后史** (与 ``_etf_work_segments`` 同构).

    ``last_ymd``/``first_ymd`` 为库内 max/min; 无行时传 ``None``/``None``.

    **不覆盖** 库内 ``MIN..MAX`` 之间零散缺日: 在 ``DATACOLLECT_KLINE_FILL_INTERIOR_GAPS``(默认开) 时
    由 ``_maybe_append_interior_tasks`` / ``merge_etf_resume_with_interior_gaps`` 追加 XSHG 历缺口区段.
    """
    if not resume:
        return [(floor_start, end_date)]
    if not last_ymd:
        return [(floor_start, end_date)]
    end_s = (end_date[:8] if len(end_date) >= 8 else end_date).ljust(8, "0")
    fl_s = (floor_start[:8] if len(floor_start) >= 8 else floor_start).ljust(8, "0")
    try:
        floor_d = datetime.strptime(fl_s, "%Y%m%d").date()
        end_d = datetime.strptime(end_s, "%Y%m%d").date()
        last_d = datetime.strptime(last_ymd[:8], "%Y%m%d").date()
    except ValueError:
        return [(floor_start, end_date)]
    first = first_ymd or last_ymd
    back_segs: list[tuple[str, str]] = []
    fwd_segs: list[tuple[str, str]] = []
    try:
        first_d = datetime.strptime(first[:8], "%Y%m%d").date()
    except ValueError:
        first_d = floor_d
    if first_d > floor_d:
        back_end_d = first_d - timedelta(days=1)
        if back_end_d >= floor_d:
            back_segs.append((fl_s, back_end_d.strftime("%Y%m%d")))
    nxt_d = last_d + timedelta(days=1)
    if nxt_d <= end_d:
        nxt_s = nxt_d.strftime("%Y%m%d")
        eff = nxt_s if nxt_s >= fl_s else fl_s
        if eff <= end_s:
            fwd_segs.append((eff, end_s))
    return fwd_segs + back_segs


def _kline_fill_interior_gaps_enabled() -> bool:
    return bool(getattr(settings.datacollect, "kline_fill_interior_gaps", True))


def _cell_to_date(v: Any) -> date:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    raise TypeError(f"expected date, got {type(v)}")


_EXCHANGE_CALENDARS_WARNED: bool = False


def _xshg_trading_session_dates(d0: date, d1: date) -> list[date]:
    """沪深京市历 (``XSHG``) 在 ``[d0,d1]`` 闭区间内的交易日列表, 升序.

    优先 ``exchange_calendars``; 未安装时见 :func:`_xshg_trading_session_dates_fallback`.
    """
    if d0 > d1:
        return []
    try:
        import exchange_calendars as ec
    except ImportError:
        global _EXCHANGE_CALENDARS_WARNED
        if not _EXCHANGE_CALENDARS_WARNED:
            _EXCHANGE_CALENDARS_WARNED = True
            logger.warning(
                "未安装 exchange_calendars, 将用库内 ``trading_date`` 或工作日近似; "
                "请在项目根执行 ``uv sync`` 以与 pyproject 对齐",
            )
        return _xshg_trading_session_dates_fallback(d0, d1)

    cal = ec.get_calendar("XSHG")
    d0_ts = pd.Timestamp(d0)
    d1_ts = pd.Timestamp(d1)
    if d0_ts < cal.first_session:
        d0_ts = cal.first_session
    if d1_ts > cal.last_session:
        d1_ts = cal.last_session
    if d0_ts > d1_ts:
        return []
    sess = cal.sessions_in_range(d0_ts, d1_ts)
    return [ts.date() for ts in sess]


def _xshg_trading_session_dates_fallback(d0: date, d1: date) -> list[date]:
    """无 exchange_calendars 时: 先 ``trading_date``(SH、非节假日线), 再 Mon–Fri 近似。"""
    q = text(
        """
        SELECT DISTINCT trade_date FROM trading_date
        WHERE market = 'SH' AND trade_date >= :a AND trade_date <= :b
          AND (is_holiday IS NULL OR is_holiday = false)
        ORDER BY trade_date
        """
    )
    with get_session(readonly=True) as session:
        rows = session.execute(q, {"a": d0, "b": d1}).fetchall()
    if rows:
        out = [r[0] for r in rows if r[0] is not None]
        if out:
            logger.info(
                "XSHG 交易日(回退, 使用库内 SH 历): %d 天, %s ~ %s",
                len(out), out[0], out[-1],
            )
            return out

    d = d0
    out_wd: list[date] = []
    while d <= d1:
        if d.weekday() < 5:
            out_wd.append(d)
        d += timedelta(days=1)
    logger.warning(
        "``trading_date`` 无覆盖区间且未装 exchange_calendars, 使用工作日近似 %d 天 (不含长假, 续传/补缺可能偏差)",
        len(out_wd),
    )
    return out_wd


def _load_table_code_trade_dates(
    table: str,
    code_col: str,
) -> dict[str, set[date]]:
    """白名单表: ``etf_daily`` / ``stock_daily`` / ``market_index``。"""
    allowed = {
        ("etf_daily", "code"),
        ("stock_daily", "code"),
        ("market_index", "index_code"),
    }
    if (table, code_col) not in allowed:
        raise ValueError(f"unsupported table/column: {table} {code_col}")
    sql = text(f"SELECT {code_col} AS c, trade_date AS td FROM {table}")  # noqa: S608
    by_code: dict[str, set[date]] = defaultdict(set)
    with get_session(readonly=True) as session:
        for c, td in session.execute(sql):
            if not c:
                continue
            by_code[str(c)].add(_cell_to_date(td))
    return by_code


def interior_trading_gaps_ymd(
    first_ymd: str,
    last_ymd: str,
    have: set[date],
    all_sessions: list[date],
) -> list[tuple[str, str]]:
    """在 ``[first_ymd, last_ymd]`` 闭区间内, 相对 ``all_sessions`` 缺行且非 ``have`` 的连续交易日 → 闭区间段 YYYYMMDD.

    ``all_sessions`` 须已覆盖 ``[first,last]`` (通常取全局最早~最晚一次预计算切片).
    """
    from bisect import bisect_left, bisect_right

    if not have or not all_sessions:
        return []
    try:
        f_d = datetime.strptime(first_ymd[:8], "%Y%m%d").date()
        l_d = datetime.strptime(last_ymd[:8], "%Y%m%d").date()
    except ValueError:
        return []
    if f_d > l_d:
        return []
    lo = bisect_left(all_sessions, f_d)
    hi_ex = bisect_right(all_sessions, l_d)
    slice_ = all_sessions[lo:hi_ex]
    out: list[tuple[str, str]] = []
    run_s, run_e = None, None
    for d in slice_:
        if d in have:
            if run_s is not None and run_e is not None:
                out.append(
                    (run_s.strftime("%Y%m%d"), run_e.strftime("%Y%m%d")),
                )
                run_s = run_e = None
        else:
            if run_s is None:
                run_s = run_e = d
            else:
                run_e = d
    if run_s is not None and run_e is not None:
        out.append((run_s.strftime("%Y%m%d"), run_e.strftime("%Y%m%d")))
    return out


def build_etf_interior_context() -> tuple[dict[str, set[date]], list[date]] | None:
    """供 ``akshare`` ``sync_etf_daily`` 与 ``_etf_work_segments`` 复用, 成功则返回 (have, xshg_sessions)。"""
    if not _kline_fill_interior_gaps_enabled():
        return None
    have = _load_table_code_trade_dates("etf_daily", "code")
    if not have:
        return None
    d_lo = min(min(s) for s in have.values() if s)
    d_hi = max(max(s) for s in have.values() if s)
    sess = _xshg_trading_session_dates(d_lo, d_hi)
    if not sess:
        return None
    return (have, sess)


def merge_etf_resume_with_interior_gaps(
    base: list[tuple[str, str]],
    code: str,
    first_ymd: str | None,
    last_ymd: str | None,
    resume: bool,
    ctx: tuple[dict[str, set[date]], list[date]] | None,
) -> list[tuple[str, str]]:
    """``sync_etf_daily`` 用: 在 ``daily_kline_work_segments`` 结果上追加 MIN~MAX 内缺口段。"""
    if not ctx or not resume or not first_ymd or not last_ymd:
        return list(base)
    have_by, sessions = ctx
    extra = interior_trading_gaps_ymd(
        first_ymd, last_ymd, have_by.get(code) or set(), sessions,
    )
    return list(base) + extra


def _append_interior_kline_tasks(
    work: list[tuple[str, str, str]],
    min_m: dict[str, str],
    max_m: dict[str, str],
    have: dict[str, set[date]],
    all_sess: list[date],
) -> int:
    """向 ``work`` 追加缺口区段, 返回追加条数。"""
    n_add = 0
    for code, first_ymd in min_m.items():
        last_ymd = max_m.get(code)
        if not last_ymd:
            continue
        hs = have.get(code)
        if not hs:
            continue
        for a, b in interior_trading_gaps_ymd(first_ymd, last_ymd, hs, all_sess):
            work.append((code, a, b))
            n_add += 1
    return n_add


def _maybe_append_interior_tasks(
    *,
    work: list[tuple[str, str, str]],
    resume: bool,
    min_m: dict[str, str],
    max_m: dict[str, str],
    table: str,
    code_col: str,
) -> None:
    if not resume or not _kline_fill_interior_gaps_enabled():
        return
    have = _load_table_code_trade_dates(table, code_col)
    if not have:
        return
    d_lo = min(min(s) for s in have.values() if s)
    d_hi = max(max(s) for s in have.values() if s)
    all_sess = _xshg_trading_session_dates(d_lo, d_hi)
    if not all_sess:
        return
    n = _append_interior_kline_tasks(work, min_m, max_m, have, all_sess)
    if n:
        logger.info(
            "K-line 续传: 已追加 %d 个「MIN~MAX 内 XSHG 缺口」区段 (%s)",
            n, table,
        )


def _stock_min_max_maps(session) -> tuple[dict[str, str], dict[str, str]]:
    rows = session.execute(text(
        "SELECT code, MIN(trade_date) AS dmin, MAX(trade_date) AS dmax "
        "FROM stock_daily GROUP BY code",
    )).fetchall()
    min_m: dict[str, str] = {}
    max_m: dict[str, str] = {}
    for code, dmin, dmax in rows:
        if not code:
            continue
        c = str(code)
        a, b = _row_date_to_ymd(dmin), _row_date_to_ymd(dmax)
        if a:
            min_m[c] = a
        if b:
            max_m[c] = b
    return min_m, max_m


def _etf_min_max_maps(session) -> tuple[dict[str, str], dict[str, str]]:
    rows = session.execute(text(
        "SELECT code, MIN(trade_date) AS dmin, MAX(trade_date) AS dmax "
        "FROM etf_daily GROUP BY code",
    )).fetchall()
    min_m: dict[str, str] = {}
    max_m: dict[str, str] = {}
    for code, dmin, dmax in rows:
        if not code:
            continue
        c = str(code)
        a, b = _row_date_to_ymd(dmin), _row_date_to_ymd(dmax)
        if a:
            min_m[c] = a
        if b:
            max_m[c] = b
    return min_m, max_m


def _index_min_max_maps(session) -> tuple[dict[str, str], dict[str, str]]:
    rows = session.execute(text(
        "SELECT index_code, MIN(trade_date) AS dmin, MAX(trade_date) AS dmax "
        "FROM market_index GROUP BY index_code",
    )).fetchall()
    min_m: dict[str, str] = {}
    max_m: dict[str, str] = {}
    for code, dmin, dmax in rows:
        if not code:
            continue
        c = str(code)
        a, b = _row_date_to_ymd(dmin), _row_date_to_ymd(dmax)
        if a:
            min_m[c] = a
        if b:
            max_m[c] = b
    return min_m, max_m


def _get_stock_tasks(
    days_back: int,
    resume: bool,
    *,
    fill_interior_gaps: bool | None = None,
) -> list[tuple[str, str, str]]:
    end_date = datetime.now().strftime("%Y%m%d")
    fallback_start = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")
    with get_session() as session:
        meta = session.query(Stock.code, Stock.list_date).all()
        min_m, max_m = _stock_min_max_maps(session)
    work: list[tuple[str, str, str]] = []
    for code, list_date in meta:
        pcf = kline_per_code_floor(
            fallback_start, list_date, min_m.get(code),
        )
        last = max_m.get(code)
        first = min_m.get(code) or last
        for seg_s, seg_e in daily_kline_work_segments(
            pcf, end_date, last, first, resume,
        ):
            work.append((code, seg_s, seg_e))
    if fill_interior_gaps if fill_interior_gaps is not None else _kline_fill_interior_gaps_enabled():
        _maybe_append_interior_tasks(
            work=work, resume=resume, min_m=min_m, max_m=max_m,
            table="stock_daily", code_col="code",
        )
    if work and resume:
        work.sort(key=lambda t: (t[2], t[1]), reverse=True)
    return work


def _get_etf_tasks(
    days_back: int,
    resume: bool,
    *,
    fill_interior_gaps: bool | None = None,
) -> list[tuple[str, str, str]]:
    end_date = datetime.now().strftime("%Y%m%d")
    fallback_start = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")
    with get_session() as session:
        meta = session.query(ETFInfo.code, ETFInfo.establish_date).all()
        min_m, max_m = _etf_min_max_maps(session)
    work: list[tuple[str, str, str]] = []
    for code, est in meta:
        pcf = kline_per_code_floor(fallback_start, est, min_m.get(code))
        last = max_m.get(code)
        first = min_m.get(code) or last
        for seg_s, seg_e in daily_kline_work_segments(
            pcf, end_date, last, first, resume,
        ):
            work.append((code, seg_s, seg_e))
    if fill_interior_gaps if fill_interior_gaps is not None else _kline_fill_interior_gaps_enabled():
        _maybe_append_interior_tasks(
            work=work, resume=resume, min_m=min_m, max_m=max_m,
            table="etf_daily", code_col="code",
        )
    if work and resume:
        work.sort(key=lambda t: (t[2], t[1]), reverse=True)
    return work


def _get_index_tasks(
    days_back: int,
    resume: bool,
    *,
    fill_interior_gaps: bool | None = None,
) -> list[tuple[str, str, str]]:
    end_date = datetime.now().strftime("%Y%m%d")
    fallback_start = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")
    with get_session() as session:
        min_m, max_m = _index_min_max_maps(session)
    work: list[tuple[str, str, str]] = []
    for code in INDEX_NAME_MAP:
        pcf = kline_per_code_floor(
            fallback_start, None, min_m.get(code),
        )
        last = max_m.get(code)
        first = min_m.get(code) or last
        for seg_s, seg_e in daily_kline_work_segments(
            pcf, end_date, last, first, resume,
        ):
            work.append((code, seg_s, seg_e))
    if fill_interior_gaps if fill_interior_gaps is not None else _kline_fill_interior_gaps_enabled():
        _maybe_append_interior_tasks(
            work=work, resume=resume, min_m=min_m, max_m=max_m,
            table="market_index", code_col="index_code",
        )
    if work and resume:
        work.sort(key=lambda t: (t[2], t[1]), reverse=True)
    return work


# ==================================================================
# 主入口
# ==================================================================


def _resolve_kline_days(
    mode: str,
    days_back: int | None,
) -> tuple[int | None, int | None, int | None]:
    """返回 (stock_days, index_days, etf_days); None 表示本模式不跑.

    未指定 days_back: ETF 单模式=配置默认约 10 年; 股/指=1 年; all=股/指1年+ETF10年.
    指定 days_back: 对参与的模式统一用该值.
    """
    dc = settings.datacollect
    d_etf = int(getattr(dc, "kline_etf_default_days_back", 3650))
    d_other = int(getattr(dc, "kline_non_etf_default_days_back", 365))
    if days_back is not None:
        u = int(days_back)
        if mode == "all":
            return u, u, u
        if mode == "stock":
            return u, None, None
        if mode == "index":
            return None, u, None
        if mode == "etf":
            return None, None, u
    if mode == "all":
        return d_other, d_other, d_etf
    if mode == "stock":
        return d_other, None, None
    if mode == "index":
        return None, d_other, None
    if mode == "etf":
        return None, None, d_etf
    return d_other, d_other, d_etf


async def run(
    mode: str = "all",
    days_back: int | None = None,
    concurrency: int = 8,
    source: str = "auto",
    rate: float = 3.0,
    burst: int = 5,
    resume: bool = True,
    fill_interior_gaps: bool | None = None,
):
    global _active_source
    _active_source = source
    reset_em_cache()
    if source in ("tencent", "auto", "qmt"):
        reset_qq_session()

    if source in ("eastmoney", "auto"):
        _get_em_limiter(rate=rate, burst=burst)

    d_st, d_ix, d_e = _resolve_kline_days(mode, days_back)
    if d_e is not None and mode in ("etf", "all"):
        logger.info(
            "ETF 日线区段地板: 回溯 %d 自然日 (约 %.1f 年, env DATACOLLECT_KLINE_ETF_DAYS_BACK 可改)",
            d_e, d_e / 365.25,
        )
    if (d_st is not None or d_ix is not None) and mode in ("stock", "index", "all"):
        d0 = d_st or d_ix
        if d0:
            logger.info("股票/指数区段地板: 回溯 %d 日", d0)

    total = 0

    if mode in ("stock", "all") and d_st is not None:
        tasks = _get_stock_tasks(d_st, resume, fill_interior_gaps=fill_interior_gaps)
        total += await _async_download(
            tasks, _fetch_stock_daily, _bulk_upsert_stock_daily,
            label="Stock K-line", concurrency=concurrency,
        )

    if mode in ("etf", "all") and d_e is not None:
        tasks = _get_etf_tasks(d_e, resume, fill_interior_gaps=fill_interior_gaps)
        total += await _async_download(
            tasks, _fetch_etf_daily, _bulk_upsert_etf_daily,
            label="ETF K-line", concurrency=concurrency,
        )

    if mode in ("index", "all") and d_ix is not None:
        tasks = _get_index_tasks(d_ix, resume, fill_interior_gaps=fill_interior_gaps)
        total += await _async_download(
            tasks, _fetch_index_daily, _bulk_upsert_index_daily,
            label="Index K-line", concurrency=concurrency,
        )

    print(f"\n=== K-line sync complete: {total:,} records ===")  # noqa: T201
    return total


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="并发批量下载 A股+ETF+指数 日K线")
    parser.add_argument(
        "mode", choices=["stock", "etf", "index", "all"],
        help="stock=A股, etf=ETF, index=指数, all=全部",
    )
    parser.add_argument(
        "--days-back",
        type=int,
        default=None,
        help="回溯自然日; 省略带环境默认: 仅 etf=约10年(3650), 仅 stock/index=365, all=股/指365+ETF10年",
    )
    parser.add_argument("--concurrency", type=int, default=8, help="并发线程数 (默认8)")
    parser.add_argument(
        "--source",
        choices=["auto", "qmt", "eastmoney", "tencent"],
        default="auto",
        help="数据源: auto=MiniQMT 优先, 再东财/腾讯; qmt=仅 xtdata; 其余=仅东财/腾讯",
    )
    parser.add_argument("--rate", type=float, default=3.0, help="东财限流速率 req/s")
    parser.add_argument("--burst", type=int, default=5, help="东财限流突发上限")
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="关闭缺口续传: 每标的一段 [days-back 与上市日之较晚者, 今日], 不拆向今/向史",
    )
    args = parser.parse_args()

    asyncio.run(run(
        mode=args.mode,
        days_back=args.days_back,
        concurrency=args.concurrency,
        source=args.source,
        rate=args.rate,
        burst=args.burst,
        resume=not args.no_resume,
    ))
