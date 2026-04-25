"""多线程「分类」下载编排: **MiniQMT/xtdata 优先**, 无数据或异常时切其它源.

- **一类一线程**: 每类在独立 `threading.Thread` 中执行, 主线程可 `join` 并汇总.
- **监控**: 守护线程按间隔可打日志; **本类**超过 ``db_stall_warn_sec``(默认 120s) 无批量落盘则置 ``stall``,
  各 ``run_*`` 协作换源/截断; **若已换源或截断后本类累计行数仍为 0**, ``CategoryResult.ok=False`` 结束该线程
  (协作式返回, 不 ``kill``). 财务: QMT→AkShare; 因子: 仅 QMT 无降级则失败; ``universe`` 见 ``sync_stocks_full`` 子链.
- **xtdata 与并发**: 迅投官方 API 非线程安全, 本模块用全局 `QMT_ORCHESTRATOR_LOCK` 将 **所有** 经本编排器发起的
  QMT 调用串行化; 东财/腾讯/tushare/akshare 等路径**不**持该锁, 可与持锁的 QMT 阶段重叠时并发执行
  (实际 CPU/网络上仍可能受 GIL 与 DB 影响).
- **多线程与 import**: ``run_parallel`` 在启动工作线程**前**于主线程调用 ``_preload_unified_collect_imports``,
  预载 ``datacollect`` / ``alt_data_sync`` / ``akshare_sync`` 等, 减少 ``_ModuleLock`` 与半初始化类名的竞态.
- **按线细节**: 同进程无法为每线程各绑一个 TTY. 可设 ``CollectConfig.thread_log_dir`` (或 ``unified_collect --thread-log-dir``),
  在目录下为 ``MainThread`` / ``dc-<类>`` / 监控 ``dc-monitor`` 各写一 ``.log``; 用 ``qt/scripts/parallel_orch_tails.ps1 -LogDir <本次目录>`` 多窗口追日志.

用法::

    uv run python -m src.data.parallel_qmt_orchestrator
    uv run python -m src.data.parallel_qmt_orchestrator --no-kline --categories universe,trading_calendar,alt,survey,lhb,moneyflow
"""
from __future__ import annotations

import asyncio
import importlib
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Any

from src.common.logger import get_logger

logger = get_logger(__name__)

# run_parallel 若启用 thread_log, 在归还 handler 前让主进程仍能写 main.log(汇总等) — 由 unified_collect 在收尾调用 ``release``。
_thread_routed_deferred: tuple[list[logging.FileHandler], int, bool] | None = None


def release_thread_routed_file_handlers() -> None:
    """释放在 ``run_parallel`` 末尾挂到 root 上的按线 FileHandler(若有). 在 ``unified_collect`` 或自定义入口汇总日志后再调."""
    global _thread_routed_deferred
    if _thread_routed_deferred is None:
        return
    h, prev, ch = _thread_routed_deferred
    _thread_routed_deferred = None
    from src.common import thread_routed_logging as trl

    trl.uninstall(h, prev, root_level_was_changed=ch)

# 所有经本模块触发的 QMT/xtdata 访问必须在此锁内 (含 kline/财务/因子/转债/指数权重等).
QMT_ORCHESTRATOR_LOCK = threading.RLock()

# 北向/板块/调研/财务/因子/龙虎榜/资金流 等续传地板 (约 10 个自然年, 以 20160101 为统一起点; CLI 可改).
DEFAULT_COLLECT_FLOOR_YMD: str = "20160101"


@dataclass
class CollectConfig:
    """全库采集统一直连参数 — 与 ``kline_bulk_sync`` / `collect_resume` 的续传语义一致."""

    resume: bool = True
    fill_interior: bool | None = None
    kline_resume: bool = True
    kline_days_back: int | None = None
    kline_concurrency: int = 8
    hsgt_start: str = DEFAULT_COLLECT_FLOOR_YMD
    survey_start: str = DEFAULT_COLLECT_FLOOR_YMD
    sector_start: str = DEFAULT_COLLECT_FLOOR_YMD
    financial_start: str = DEFAULT_COLLECT_FLOOR_YMD
    factor_start: str = DEFAULT_COLLECT_FLOOR_YMD
    lhb_floor: str = DEFAULT_COLLECT_FLOOR_YMD
    mf_floor: str = DEFAULT_COLLECT_FLOOR_YMD
    # 板块: end<今日时是否仍拉东财资金快照(见 ``sector_market_data`` 说明, 数据仍为实时)
    sector_include_fund_flow: bool = True
    sector_force_fund_snapshot: bool = False
    index_codes: tuple[str, ...] = ("000300.SH", "000905.SH", "000852.SH")
    monitor_interval: float = 0.0
    # 某采集类超过该秒数无**本类**批量落盘 (见 ``db_batch`` per-category 心跳), 打 ERROR 并置 stall, 以切换数据源
    db_stall_warn_sec: float = 120.0
    # 若设目录, 在子目录 ``orch_YYYYMMDD_HHMMSS/`` 下为 main / 各类工作线程 / 监控线程 各写一 .log, 与 stdout 并行
    thread_log_dir: str | None = None


@dataclass
class CategoryResult:
    name: str
    ok: bool
    message: str = ""
    value: int | None = None
    data_source: str = ""  # qmt / akshare / tushare / mixed / n/a
    duration_sec: float = 0.0
    error: str | None = None


@dataclass
class OrchestratorState:
    results: list[CategoryResult] = field(default_factory=list)
    start_times: dict[str, float] = field(default_factory=dict)
    stop_monitor: threading.Event = field(default_factory=threading.Event)
    # 每采集类一事件: 监控线程在「本类超过 db_stall_warn_sec 无落盘」时 set, 工作线程读取后 clear
    stall_events: dict[str, threading.Event] = field(default_factory=dict)
    # 类别 -> 上次打「长无本类落盘」提醒的 time.monotonic(), 防刷屏
    stall_lag_warn_at_mono: dict[str, float] = field(default_factory=dict)


def _stall_event_is_set(state: OrchestratorState | None, name: str) -> bool:
    if not state:
        return False
    ev = state.stall_events.get(name)
    return bool(ev and ev.is_set())


def _consume_stall(state: OrchestratorState | None, name: str) -> bool:
    """工作线程在换源/退出前 clear stall, 返回之前是否处于滞停。"""
    if not state:
        return False
    ev = state.stall_events.get(name)
    if ev and ev.is_set():
        ev.clear()
        return True
    return False


def _ok_after_stall_exhausted(had_stall: bool, row_count: int | None) -> bool:
    """本类曾触滞停(120s 无本类落盘)且换源/协作结束后仍无任何行数时判失败.

    采用**协作式**结束 (``CategoryResult ok=False``), 由 ``wrap`` 自然返回; 不用 ``kill`` 线程,
    因 CPython 无法安全终止子线程, 且另起同线程会重复改库。
    """
    if not had_stall:
        return True
    n = 0 if row_count is None else int(row_count)
    return n > 0


def _orchestrator_stall_reconcile(
    name: str,
    r: CategoryResult,
    state: OrchestratorState | None,
) -> CategoryResult:
    """``run_*`` 返回后: 若本类 **stall 事件仍为 set** 且 ``value==0/None`` 且 ``ok=True``, 判为失败并 clear.

    防止某路径忘调 ``_consume_stall``/漏判, 导致「无落盘却 ok=True」. 有行数时仅清事件, 不降级 ok.
    """
    if not state:
        return r
    ev = state.stall_events.get(name)
    if not ev or not ev.is_set():
        return r
    val = r.value
    if val is not None and not isinstance(val, (int, float)):
        if _consume_stall(state, name):
            pass
        return r
    n = 0 if val is None else int(val)
    if n > 0:
        _consume_stall(state, name)
        return r
    if not r.ok:
        _consume_stall(state, name)
        return r
    had = _consume_stall(state, name)
    if not had:
        return r
    logger.error("编排收口: 类别 %s 曾滞停且本类 n==0, 子结果仍为 ok, 已改为失败", name)
    return CategoryResult(
        name,
        False,
        r.message,
        r.value,
        r.data_source,
        r.duration_sec,
        (r.error + " 滞停+0行(编排收口)") if r.error else "滞停+0行(编排收口)",
    )


def _coerce_qmt_day(x: Any) -> date | None:
    if x is None:
        return None
    if isinstance(x, datetime):
        return x.date()
    if isinstance(x, date) and not isinstance(x, datetime):
        return x
    if isinstance(x, (int, float)) and not (isinstance(x, float) and (x != x)):
        s = f"{int(x):08d}"
        if len(s) == 8:
            try:
                return datetime.strptime(s, "%Y%m%d").date()
            except ValueError:
                return None
    s = str(x).strip()
    if len(s) >= 10 and s[4] == "-":
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d").date()
        except ValueError:
            return None
    digits = "".join(ch for ch in s if ch.isdigit())[:8]
    if len(digits) == 8:
        try:
            return datetime.strptime(digits, "%Y%m%d").date()
        except ValueError:
            return None
    return None


def _stock_list_qmt_format() -> list[str]:
    from src.common.db import get_session
    from src.data.models import Stock

    out: list[str] = []
    with get_session(readonly=True) as session:
        for (code,) in session.query(Stock.code).all():
            c = (code or "").strip()
            if not c or len(c) < 6:
                continue
            p = c[:6]
            if p[0] in ("6", "5", "9"):
                out.append(f"{p}.SH")
            else:
                out.append(f"{p}.SZ")
    return out


# ---------------------------------------------------------------------------
# 各类任务 (QMT 优先, 内层自行降级)
# ---------------------------------------------------------------------------


def run_kline(
    days_back: int | None = None,
    kline_concurrency: int = 8,
    source: str = "auto",
    resume: bool = True,
    state: OrchestratorState | None = None,
    stall_sec: float = 120.0,
) -> CategoryResult:
    """A 股+ETF+指数 日 K: ``kline_bulk_sync.run``, ``source=auto`` 为 MiniQMT 优先;

    **resume**: 与 ``--no-resume`` 相反, 为 True 时按标的拆向今/向史/中缝(见环境 ``DATACOLLECT_KLINE_*``)。"""
    t0 = time.perf_counter()
    from src.data import kline_bulk_sync

    async def _go() -> int:
        return await kline_bulk_sync.run(
            mode="all",
            days_back=days_back,
            concurrency=kline_concurrency,
            source=source,
            rate=3.0,
            burst=5,
            resume=resume,
        )

    with QMT_ORCHESTRATOR_LOCK:
        try:
            loop = asyncio.new_event_loop()
            try:
                asyncio.set_event_loop(loop)
                n = loop.run_until_complete(_go())
            finally:
                loop.close()
        except Exception as e:  # noqa: BLE001
            return CategoryResult(
                "kline", False, "kline 失败", None, "n/a", time.perf_counter() - t0, str(e),
            )
    had = _consume_stall(state, "kline")
    if had:
        logger.error(
            "kline: 约 %.0f 秒无本类落盘(整段 kline 内可能未内嵌断点), 本趟行数见 value",
            stall_sec,
        )
    k_ok = _ok_after_stall_exhausted(had, n)
    return CategoryResult(
        "kline",
        k_ok,
        "kline 完成",
        n,
        f"auto({source})",
        time.perf_counter() - t0,
        None if k_ok else "本类曾滞停且本趟 k 线写入为 0",
    )


def run_universe(
    state: OrchestratorState | None = None,
    stall_sec: float = 120.0,
) -> CategoryResult:
    """股票全量: akshare 为主, 内建 QMT 合并; 本类久无落盘时 ``sync_stocks_full`` 在子步骤间协作退出。"""
    t0 = time.perf_counter()
    sc = (lambda: _stall_event_is_set(state, "universe")) if state else None
    try:
        from src.data.akshare_sync import AkshareDataSync

        r = AkshareDataSync().sync_stocks_full(stall_check=sc)
        n = sum(int(v) for v in r.values() if isinstance(v, int))
        had = _consume_stall(state, "universe")
        if had:
            logger.error("universe: 约 %.0f 秒无本类落盘, sync_stocks_full 已提前结束 (后续子步骤已跳过)", stall_sec)
        u_ok = _ok_after_stall_exhausted(had, n)
        return CategoryResult(
            "universe",
            u_ok,
            f"sync_stocks_full {r!r}",
            n,
            "akshare+qmt",
            time.perf_counter() - t0,
            None if u_ok else "本类曾滞停且全链子步骤仍无行数(无本类落盘)",
        )
    except Exception as e:  # noqa: BLE001
        return CategoryResult("universe", False, "universe 失败", None, "n/a", time.perf_counter() - t0, str(e))


def run_trading_calendar(
    state: OrchestratorState | None = None,
    stall_sec: float = 120.0,
) -> CategoryResult:
    """交易日历: 先 QMT 写入; 无数据/异常/本类滞停则 ``backfill_trading_date``(新浪/ak)。"""
    t0 = time.perf_counter()
    end = date.today().strftime("%Y%m%d")
    start = "20100101"
    n_q = 0
    sc = (lambda: _stall_event_is_set(state, "trading_calendar")) if state else None
    with QMT_ORCHESTRATOR_LOCK:
        try:
            from sqlalchemy.dialects.postgresql import insert

            from src.common.db import get_session
            from src.common.db_batch import DEFAULT_TABLE_UPSERT_FLUSH, log_upsert_commit
            from src.data.models import TradingDate
            from src.data.qmt_client import QMTClient

            c = QMTClient()
            _ = c.xtdata
            for mkt in ("SH", "SZ"):
                if sc and sc():
                    logger.warning("交易日历: 本类滞停, 中断 QMT 交易所循环, 将试新浪/ak 回填")
                    break
                cal: Any = None
                try:
                    cal = c.get_trading_calendar(mkt, start_time=start, end_time=end)
                except Exception:  # noqa: BLE001
                    try:
                        cal = c.get_trading_dates(
                            mkt, start_time=start, end_time=end, count=-1,
                        )
                    except Exception:
                        cal = None
                rows: list[dict] = []
                for x in (cal or []):
                    td = _coerce_qmt_day(x)
                    if td is None:
                        continue
                    rows.append(
                        {
                            "market": mkt,
                            "trade_date": td,
                            "is_holiday": False,
                        },
                    )
                if not rows:
                    continue
                mkt_broken = False
                for i in range(0, len(rows), DEFAULT_TABLE_UPSERT_FLUSH):
                    if sc and sc():
                        mkt_broken = True
                        break
                    batch = rows[i : i + DEFAULT_TABLE_UPSERT_FLUSH]
                    with get_session() as session:
                        session.execute(
                            insert(TradingDate)
                            .values(batch)
                            .on_conflict_do_nothing(constraint="uq_trading_date"),
                        )
                    log_upsert_commit("orchestrator.trading_date_qmt", len(batch))
                    n_q += len(batch)
                if mkt_broken:
                    logger.warning("交易日历: 本类滞停, QMT 批次中断, 将试新浪/ak 回填")
                    break
        except Exception as e:  # noqa: BLE001
            logger.warning("交易日历 QMT 路径失败, 将尝试新浪: %s", e)

    had = _consume_stall(state, "trading_calendar")
    if had:
        logger.error("交易日历: 约 %.0f 秒无本类落盘, 已结束/中断 QMT 段, 将试新浪/ak 回填", stall_sec)
    if n_q > 0:
        return CategoryResult(
            "trading_calendar", True, f"QMT 写入 {n_q} 行(含 SH/SZ 可能同日)", n_q, "qmt", time.perf_counter() - t0, None,
        )
    from src.data.data_completeness import backfill_trading_date

    try:
        n = backfill_trading_date()
        t_ok = _ok_after_stall_exhausted(had, n)
        return CategoryResult(
            "trading_calendar",
            t_ok,
            "新浪/akshare 交易日历",
            n,
            "akshare",
            time.perf_counter() - t0,
            None if t_ok else "QMT 后曾滞停且新浪/ak 仍无行数",
        )
    except Exception as e:  # noqa: BLE001
        return CategoryResult("trading_calendar", False, "交易日历失败", None, "n/a", time.perf_counter() - t0, str(e))


def run_financial(
    cfg: CollectConfig,
    batch_size: int = 300,
    state: OrchestratorState | None = None,
) -> CategoryResult:
    """财报+指标: QMT 全窗拉取; 失败、0 行或 120s 无本类落盘则转 AkShare — **续传** 时只跑 ``missing_*_report_periods`` 缺季."""
    t0 = time.perf_counter()
    start_time = cfg.financial_start
    end_ymd = date.today().strftime("%Y%m%d")
    codes = _stock_list_qmt_format()
    if not codes:
        try:
            from src.data.data_completeness import backfill_financial

            n = backfill_financial(mode="batch")
            return CategoryResult("financial", True, "无股票列表, 仅 akshare batch", n, "akshare", time.perf_counter() - t0, None)
        except Exception as e:  # noqa: BLE001
            return CategoryResult("financial", False, "financial 失败", None, "n/a", time.perf_counter() - t0, str(e))

    def _qmt_stall() -> bool:
        return _stall_event_is_set(state, "financial")

    total = 0
    qmt_aborted_stall = False
    with QMT_ORCHESTRATOR_LOCK:
        try:
            from src.data.financial_data import FinancialDataSync

            fs = FinancialDataSync()
            for i in range(0, len(codes), batch_size):
                if _stall_event_is_set(state, "financial"):
                    _consume_stall(state, "financial")
                    qmt_aborted_stall = True
                    logger.error(
                        "财务采集: 已约 %.0f 秒无本类落盘(判为 QMT/当前源不可用), 中断 QMT, 将尝试 AkShare/其它源",
                        cfg.db_stall_warn_sec,
                    )
                    break
                chunk = codes[i : i + batch_size]
                total += fs.sync_reports(
                    chunk, start_time=start_time, end_time="",
                    stall_check=_qmt_stall,
                )
                if _stall_event_is_set(state, "financial"):
                    _consume_stall(state, "financial")
                    qmt_aborted_stall = True
                    logger.error(
                        "财务同步报表: 约 %.0f 秒无本类落盘, 不再继续 QMT, 将尝试其它源",
                        cfg.db_stall_warn_sec,
                    )
                    break
                total += fs.sync_indicators(
                    chunk, start_time=start_time, end_time="",
                    stall_check=_qmt_stall,
                )
                if _stall_event_is_set(state, "financial"):
                    _consume_stall(state, "financial")
                    qmt_aborted_stall = True
                    logger.error(
                        "财务同步指标: 约 %.0f 秒无本类落盘, 不再继续 QMT, 将尝试其它源",
                        cfg.db_stall_warn_sec,
                    )
                    break
        except Exception as e:  # noqa: BLE001
            logger.warning("QMT 财务同步失败, 改用 akshare: %s", e)
            total = 0

    if total > 0:
        if _consume_stall(state, "financial"):
            logger.warning("财务: QMT 已有入库, 清滞停事件(避免遗留)")
        return CategoryResult("financial", True, "QMT 财务入库", total, "qmt", time.perf_counter() - t0, None)
    try:
        from src.data.akshare_financial_sync import AkshareFinancialSync
        from src.data.collect_resume import (
            missing_financial_indicator_periods,
            missing_financial_report_periods,
        )

        a = AkshareFinancialSync()
        n2 = 0
        if not cfg.resume:
            n2 = a.sync_financial_report_batch()
            n2 += a.sync_financial_indicator_batch()
        else:
            pr = missing_financial_report_periods(start_time, end_ymd)
            pi = missing_financial_indicator_periods(start_time, end_ymd)
            if pr:
                n2 += a.sync_financial_report_batch(periods=pr)
            else:
                logger.info("财报报告期无缺失(窗口内), 跳过 report batch")
            if pi:
                n2 += a.sync_financial_indicator_batch(periods=pi)
            else:
                logger.info("财务指标报告期无缺失(窗口内), 跳过 indicator batch")
        ak_stall = _consume_stall(state, "financial")
        if ak_stall:
            logger.error("财务(akshare 段后): 曾判本类滞停(约无批量落盘), 与 QMT 弃跑一并计入")
        fin_ok = _ok_after_stall_exhausted(qmt_aborted_stall or ak_stall, n2)
        return CategoryResult(
            "financial", fin_ok, f"akshare 财报/指标(约 {n2} 次写入)", n2, "akshare",
            time.perf_counter() - t0,
            None if fin_ok else "滞停后 akshare 仍无写入次数(QMT+Ak 合计为 0)",
        )
    except Exception as e:  # noqa: BLE001
        return CategoryResult("financial", False, "财务失败", None, "n/a", time.perf_counter() - t0, str(e))


def run_convertible(
    state: OrchestratorState | None = None,
    stall_sec: float = 120.0,
) -> CategoryResult:
    """转债基础信息: QMT ``sync_cb_info``; 无数据/失败/本类滞停则集思录 ``sync_cb_list``。"""
    t0 = time.perf_counter()
    n = 0
    sc = (lambda: _stall_event_is_set(state, "convertible")) if state else None

    stall_cleared = False
    if sc and sc():
        if _consume_stall(state, "convertible"):
            stall_cleared = True
            logger.error("convertible: 本类已滞停, 跳过 QMT, 将试集思录")
    else:
        with QMT_ORCHESTRATOR_LOCK:
            try:
                from src.data.cb_data import CBDataSync

                n = CBDataSync().sync_cb_info()
            except Exception as e:  # noqa: BLE001
                logger.warning("QMT 转债: %s", e)
        if _consume_stall(state, "convertible"):
            stall_cleared = True
            logger.error("convertible: 约 %.0f 秒无本类落盘, QMT 段结束, 将试集思录", stall_sec)
    if n and n > 0:
        return CategoryResult("convertible", True, "QMT 转债信息", n, "qmt", time.perf_counter() - t0, None)
    try:
        from src.data.cb_sync import CBDataSync as AkCB

        m = AkCB().sync_cb_list()
        c_ok = _ok_after_stall_exhausted(stall_cleared, m)
        return CategoryResult(
            "convertible",
            c_ok,
            "集思录转债列表",
            m,
            "akshare",
            time.perf_counter() - t0,
            None if c_ok else "曾滞停且集思录仍无行数",
        )
    except Exception as e:  # noqa: BLE001
        return CategoryResult("convertible", False, "转债失败", None, "n/a", time.perf_counter() - t0, str(e))


def run_factors(
    start_time: str = DEFAULT_COLLECT_FLOOR_YMD,
    batch_size: int = 200,
    state: OrchestratorState | None = None,
    stall_sec: float = 120.0,
) -> CategoryResult:
    """价量+财务因子: 仅 QMT ``FactorDataManager.sync_factors``; 约 stall_sec 秒无本类落盘则结束(无其它源)。"""
    t0 = time.perf_counter()
    codes = _stock_list_qmt_format()
    if not codes:
        return CategoryResult("factors", False, "stocks 表为空, 跳过因子", 0, "n/a", time.perf_counter() - t0, None)

    def _fac_stall() -> bool:
        return _stall_event_is_set(state, "factors")

    total = 0
    with QMT_ORCHESTRATOR_LOCK:
        try:
            from src.data.qmt_client import QMTClient

            ok_probe, probe_msg = QMTClient().probe_xtdata_connection()
            logger.info("QMT 因子前探测: %s", probe_msg)
            if not ok_probe:
                return CategoryResult(
                    "factors", False, probe_msg, 0, "n/a",
                    time.perf_counter() - t0, None,
                )
            from src.data.factor_data import FactorDataManager

            fm = FactorDataManager()
            for i in range(0, len(codes), batch_size):
                if _stall_event_is_set(state, "factors"):
                    _consume_stall(state, "factors")
                    logger.error(
                        "因子: 已约 %.0f 秒无本类落盘(判为 QMT 不可用), 本类无其它数据源, 结束",
                        stall_sec,
                    )
                    return CategoryResult(
                        "factors", False,
                        f"QMT 滞停(约{stall_sec:.0f}s 无本类落盘), 无降级源", total, "n/a",
                        time.perf_counter() - t0, None,
                    )
                chunk = codes[i : i + batch_size]
                total += fm.sync_factors(
                    stock_list=chunk, start_time=start_time, end_time="",
                    stall_check=_fac_stall,
                )
                if _stall_event_is_set(state, "factors"):
                    _consume_stall(state, "factors")
                    logger.error("因子: 约 %.0f 秒无本类落盘, QMT 无其它可用源, 本类结束", stall_sec)
                    return CategoryResult(
                        "factors", False,
                        f"QMT 滞停(约{stall_sec:.0f}s 无本类落盘), 无降级源", total, "n/a",
                        time.perf_counter() - t0, None,
                    )
        except ImportError as e:
            msg = str(e)
            hint = "因子仅 QMT"
            if "xtquant" in msg or "xtdata" in msg.lower():
                hint = "未安装 xtquant(迅投 QMT 行情扩展), 无法拉取因子, 已跳过本类"
            return CategoryResult(
                "factors", False, hint, 0, "n/a", time.perf_counter() - t0, msg,
            )
        except Exception as e:  # noqa: BLE001
            return CategoryResult("factors", False, "因子仅 QMT", None, "qmt", time.perf_counter() - t0, str(e))
    had = _consume_stall(state, "factors")
    f_ok = (total > 0) and _ok_after_stall_exhausted(had, total)
    return CategoryResult(
        "factors", f_ok, "因子条数", total, "qmt", time.perf_counter() - t0,
        None if f_ok else "无因子行(含滞停后为 0)",
    )


def run_sector_index(
    cfg: CollectConfig,
    state: OrchestratorState | None = None,
) -> CategoryResult:
    """指数权重: ``sync_index_weight`` 内 **QMT 优先**, 无数据再 Tushare/东财/新浪等 (与 ``alt_datacollect_progress`` 一致); 此处预 ``download_index_weight`` + 板块元数据.

    板块 K 经 ``backfill_sector_data`` → ``SectorMarketSync``; 行业映射 ``sync_industry_to_sector_stock``.
    """
    t0 = time.perf_counter()
    ics = list(cfg.index_codes) or ["000300.SH", "000905.SH", "000852.SH"]
    n_w = 0
    n_s = 0
    n_i = 0
    errs: list[str] = []
    sector_had_stall = False
    with QMT_ORCHESTRATOR_LOCK:
        try:
            from src.data.qmt_client import QMTClient

            c = QMTClient()
            c.download_index_weight()
            c.download_sector_data()
        except Exception as e:  # noqa: BLE001
            logger.warning("QMT 预下板块/指数元数据(可忽略, 级联会换源): %s", e)
    if state and _stall_event_is_set(state, "sector_index"):
        sector_had_stall = bool(_consume_stall(state, "sector_index"))
        if sector_had_stall:
            logger.error(
                "sector_index: 约 %.0f 秒无本类落盘(含 QMT 元数据段可能无 commit); 仍继续 Tushare/东财/新浪 级联与板块回补",
                cfg.db_stall_warn_sec,
            )
    try:
        from src.data.alt_data_sync import AltDataSync
        from datetime import date as ddate

        alt = AltDataSync()
        for ic in ics:
            n_w += alt.sync_index_weight(
                ic, ddate.today(), lookback_days=20,
            )
    except Exception as e:  # noqa: BLE001
        errs.append(f"index_weight: {e!s}")
        logger.warning("指数权重级联: %s", e)

    try:
        from src.data.data_completeness import backfill_sector_data

        n_s = backfill_sector_data(
            start_date=cfg.sector_start,
            resume=cfg.resume,
            fill_interior=cfg.fill_interior,
            include_fund_flow=cfg.sector_include_fund_flow,
            force_fund_snapshot=cfg.sector_force_fund_snapshot,
        )
    except Exception as e:  # noqa: BLE001
        errs.append(f"sector_data: {e!s}")
        logger.warning("板块行情: %s", e)

    try:
        from src.data.alt_data_sync import AltDataSync

        n_i = AltDataSync().sync_industry_to_sector_stock()
    except Exception as e:  # noqa: BLE001
        errs.append(f"sector_stock: {e!s}")
        logger.warning("行业映射: %s", e)
    if _consume_stall(state, "sector_index"):
        sector_had_stall = True
        logger.error("sector_index: 级联/板块段后曾本类滞停, 与累计行数一并判定 ok")
    n = n_w + n_s + n_i
    row_ok = _ok_after_stall_exhausted(sector_had_stall, n)
    no_exc = len(errs) == 0
    ok = no_exc and row_ok
    em = "; ".join(errs) if errs else None
    if not row_ok and sector_had_stall:
        stall_msg = "滞停后仍无行数(指数/板块/行业映射合计为 0)"
        em = f"{em}; {stall_msg}" if em else stall_msg
    return CategoryResult(
        "sector_index",
        ok,
        f"权重≈{n_w}, 板块≈{n_s}, 行业≈{n_i}" + (f" | 异常: {em}" if em else ""),
        n,
        "mixed",
        time.perf_counter() - t0,
        em,
    )


def run_alt(
    cfg: CollectConfig,
    state: OrchestratorState | None = None,
    stall_sec: float = 120.0,
) -> CategoryResult:
    """沪深港通市场日频, 与 ``hsgt_market_daily`` 续传区段一致 (向今/向史/中缝). 本类无落盘超阈值则中断续传."""
    t0 = time.perf_counter()
    sc = (lambda: _stall_event_is_set(state, "alt")) if state else None
    try:
        from src.data.alt_data_sync import AltDataSync

        a = AltDataSync()
        end = date.today()
        n = a.sync_hsgt_market_resuming(
            cfg.hsgt_start, end, resume=cfg.resume, fill_interior=cfg.fill_interior,
            stall_check=sc,
        )
        had = _consume_stall(state, "alt")
        if had:
            logger.error("北向 hsgt: 约 %.0f 秒无本类落盘, 已中断续传 (级联日循环内协作退出)", stall_sec)
        a_ok = _ok_after_stall_exhausted(had, n)
        return CategoryResult(
            "alt", a_ok, f"北向 hsgt 续传 累计行≈{n}", n, "tushare/ak", time.perf_counter() - t0,
            None if a_ok else "滞停后仍无行数(级联无落盘)",
        )
    except Exception as e:  # noqa: BLE001
        return CategoryResult("alt", False, "alt 失败", None, "n/a", time.perf_counter() - t0, str(e))


def run_survey(
    cfg: CollectConfig,
    state: OrchestratorState | None = None,
    stall_sec: float = 120.0,
) -> CategoryResult:
    """机构调研 ``institution_survey`` — Tushare + AkShare ``stock_jgdy_tj_em`` 级联."""
    t0 = time.perf_counter()
    sc = (lambda: _stall_event_is_set(state, "survey")) if state else None
    try:
        from src.data.alt_data_sync import AltDataSync

        a = AltDataSync()
        end = date.today()
        n = a.sync_stk_surv_resuming(
            cfg.survey_start, end, resume=cfg.resume, fill_interior=cfg.fill_interior,
            stall_check=sc,
        )
        had = _consume_stall(state, "survey")
        if had:
            logger.error("机构调研: 约 %.0f 秒无本类落盘, 已中断续传", stall_sec)
        s_ok = _ok_after_stall_exhausted(had, n)
        return CategoryResult(
            "survey", s_ok, f"机构调研续传 累计行≈{n}", n, "cascade", time.perf_counter() - t0,
            None if s_ok else "滞停后仍无行数",
        )
    except Exception as e:  # noqa: BLE001
        return CategoryResult("survey", False, "survey 失败", None, "n/a", time.perf_counter() - t0, str(e))


def run_lhb(
    cfg: CollectConfig,
    state: OrchestratorState | None = None,
    stall_sec: float = 120.0,
) -> CategoryResult:
    """龙虎榜按 **缺失交易日** 补 (相对 ``stock_lhb_daily``)。"""
    t0 = time.perf_counter()
    sc = (lambda: _stall_event_is_set(state, "lhb")) if state else None
    try:
        from src.data.alt_data_sync import AltDataSync
        from src.data.collect_resume import parse_ymd

        a = AltDataSync()
        end = date.today()
        n = a.sync_lhb_resuming(
            parse_ymd(cfg.lhb_floor), end, resume=cfg.resume,
            stall_check=sc,
        )
        had = _consume_stall(state, "lhb")
        if had:
            logger.error("龙虎榜: 约 %.0f 秒无本类落盘, 已中断续传", stall_sec)
        l_ok = _ok_after_stall_exhausted(had, n)
        return CategoryResult(
            "lhb", l_ok, f"龙虎榜续传 累计行≈{n}", n, "cascade", time.perf_counter() - t0,
            None if l_ok else "滞停后仍无行数",
        )
    except Exception as e:  # noqa: BLE001
        return CategoryResult("lhb", False, "lhb 失败", None, "n/a", time.perf_counter() - t0, str(e))


def run_moneyflow(
    cfg: CollectConfig,
    state: OrchestratorState | None = None,
    stall_sec: float = 120.0,
) -> CategoryResult:
    """个股资金流按 **缺失交易日** 补。"""
    t0 = time.perf_counter()
    sc = (lambda: _stall_event_is_set(state, "moneyflow")) if state else None
    try:
        from src.data.alt_data_sync import AltDataSync
        from src.data.collect_resume import parse_ymd

        a = AltDataSync()
        end = date.today()
        n = a.sync_moneyflow_resuming(
            parse_ymd(cfg.mf_floor), end, resume=cfg.resume,
            stall_check=sc,
        )
        had = _consume_stall(state, "moneyflow")
        if had:
            logger.error("个股资金流: 约 %.0f 秒无本类落盘, 已中断续传", stall_sec)
        mf_ok = _ok_after_stall_exhausted(had, n)
        return CategoryResult(
            "moneyflow", mf_ok, f"moneyflow 续传 累计行≈{n}", n, "cascade", time.perf_counter() - t0,
            None if mf_ok else "滞停后仍无行数",
        )
    except Exception as e:  # noqa: BLE001
        return CategoryResult("moneyflow", False, "moneyflow 失败", None, "n/a", time.perf_counter() - t0, str(e))


# ---------------------------------------------------------------------------
# 编排与监控
# ---------------------------------------------------------------------------

_KNOWN = frozenset({
    "kline", "universe", "trading_calendar", "financial", "convertible", "factors",
    "sector_index", "alt", "survey", "lhb", "moneyflow",
})
# 见 ``_monitor_loop`` + 各 ``run_*`` 内对 ``stall_events`` 的消费.
# **kline**: ``kline_bulk_sync.run`` 长时 asyncio 内未内嵌断点, 但监控线程可置 **stall**; 结束时 ``_consume_stall`` + 行数判定.
_STALL_SWITCH_CATEGORIES: frozenset[str] = frozenset({
    "kline",
    "financial", "factors", "sector_index",
    "alt", "survey", "lhb", "moneyflow",
    "universe",
    "trading_calendar", "convertible",
})


def _preload_unified_collect_imports(categories: list[str]) -> None:
    """在启动子线程**之前**于主线程完成会竞争 import 的模块加载。

    多类并行时, 若多个线程**各自**第一次 ``import`` 到 ``src.datacollect`` / ``alt_data_sync`` 等,
    可能在 ``_ModuleLock`` 上与交叉依赖叠加形成死锁, 或出现
    ``cannot import name 'AltDataSync'``(模块半初始化). 在单线程中按固定顺序把上述模块
    录入 ``sys.modules`` 后再 ``Thread.start`` 可规避(见 Python import 多线程说明).

    失败仅打 debug, 不阻断采集(线程内仍会重试 import).
    """
    active = {c for c in categories if c in _KNOWN}
    if not active:
        return

    def _im(mod: str) -> None:
        try:
            importlib.import_module(mod)
        except Exception as e:  # noqa: BLE001
            logger.debug("采集预热 %s: %s", mod, e)

    # 定序: datacollect 基类与采集器 → 顶层依赖 TushareCollector 的 alt_data_sync(含 AltDataSync)
    _im("src.datacollect.base")
    _im("src.datacollect.collectors.tushare_collector")
    _im("src.data.alt_data_sync")
    _im("src.data.akshare_sync")
    if "financial" in active:
        _im("src.data.akshare_financial_sync")
    if "convertible" in active:
        _im("src.data.cb_data")
        _im("src.data.cb_sync")
    if "trading_calendar" in active:
        _im("src.data.data_completeness")
    if "factors" in active:
        _im("src.data.factor_data")
    if "kline" in active:
        _im("src.data.kline_bulk_sync")


def dispatch_category(
    name: str,
    cfg: CollectConfig,
    state: OrchestratorState | None = None,
) -> CategoryResult:
    if name == "kline":
        return run_kline(
            days_back=cfg.kline_days_back,
            kline_concurrency=cfg.kline_concurrency,
            source="auto",
            resume=cfg.kline_resume,
            state=state,
            stall_sec=cfg.db_stall_warn_sec,
        )
    if name == "universe":
        return run_universe(state=state, stall_sec=cfg.db_stall_warn_sec)
    if name == "trading_calendar":
        return run_trading_calendar(state=state, stall_sec=cfg.db_stall_warn_sec)
    if name == "financial":
        return run_financial(cfg, state=state)
    if name == "convertible":
        return run_convertible(state=state, stall_sec=cfg.db_stall_warn_sec)
    if name == "factors":
        return run_factors(
            start_time=cfg.factor_start[:8].ljust(8, "0"),
            state=state,
            stall_sec=cfg.db_stall_warn_sec,
        )
    if name == "sector_index":
        return run_sector_index(cfg, state=state)
    if name == "alt":
        return run_alt(cfg, state=state, stall_sec=cfg.db_stall_warn_sec)
    if name == "survey":
        return run_survey(cfg, state=state, stall_sec=cfg.db_stall_warn_sec)
    if name == "lhb":
        return run_lhb(cfg, state=state, stall_sec=cfg.db_stall_warn_sec)
    if name == "moneyflow":
        return run_moneyflow(cfg, state=state, stall_sec=cfg.db_stall_warn_sec)
    raise KeyError(f"unknown category: {name}")


def _monitor_loop(
    state: OrchestratorState,
    watch: list[str],
    interval: float,
    db_stall_warn_sec: float,
    log_parallel_info: bool,
) -> None:
    from src.common import db_batch

    # 本类长无 `log_upsert_commit`(见 db_batch) 的 INFO 时, 打「落盘 x 行」; tqdm/多线程/长 HTTP 下终端里可能**看不到**这些行, 以本循环里的「距本类落盘」为准。
    _lag_warn_min = 45.0
    _lag_throttle_s = 50.0

    while not state.stop_monitor.wait(timeout=interval):
        if log_parallel_info:
            parts: list[str] = []
            for n in watch:
                if n in state.start_times:
                    t0w = state.start_times[n]
                    run_s = time.perf_counter() - t0w
                    idle = db_batch.seconds_since_last_upsert_for_category(n)
                    # 已跑=线程墙钟; 距本类落盘=自上次本类有 row>0 的 `落盘` commit 起算 (与 --db-stall-warn-sec 对比)
                    parts.append(f"{n}(已跑{run_s:.0f}s, 距本类落盘{idle:.0f}s)")
            if parts:
                logger.info("[parallel_qmt] 监控: %s", ", ".join(parts))
        for n in watch:
            if n not in state.start_times:
                continue
            idle = db_batch.seconds_since_last_upsert_for_category(n)
            if idle < _lag_warn_min:
                continue
            nowm = time.monotonic()
            lastm = state.stall_lag_warn_at_mono.get(n, 0.0)
            if nowm - lastm < _lag_throttle_s:
                continue
            state.stall_lag_warn_at_mono[n] = nowm
            logger.warning(
                "[parallel_qmt] 类别 %s 已约 %.0f 秒**无**本类 `落盘` 行(见 logger `src.common.db_batch`). "
                "常见原因: 东财/新浪整段请求未结束、重试、或 tqdm 把 INFO 冲掉; 以「距本类落盘」与后续 [数据源滞停] 为准。",
                n, idle,
            )
        if not db_stall_warn_sec or db_stall_warn_sec <= 0:
            continue
        for n in watch:
            if n not in state.start_times:
                continue
            idle = db_batch.seconds_since_last_upsert_for_category(n)
            if idle < db_stall_warn_sec:
                continue
            if n not in _STALL_SWITCH_CATEGORIES:
                logger.warning(
                    "[本类无落盘] 类别 %s 已约 %.0f 秒无本类批量落盘 (整段阻塞、未打 log_upsert 心跳、或该类未接写库段).",
                    n, idle,
                )
                continue
            ev = state.stall_events.get(n)
            if not ev:
                continue
            was_set = ev.is_set()
            ev.set()
            if not was_set:
                logger.error(
                    "[数据源滞停] 类别 %s 已约 %.0f 秒无本类批量落盘(判为当前数据源/下载路径不可用), "
                    "将通知工作线程: 财务/因子协作中断 QMT, 或 sector_index 续跑级联。",
                    n, idle,
                )


def run_parallel(
    categories: list[str],
    cfg: CollectConfig | None = None,
) -> list[CategoryResult]:
    cfg = cfg or CollectConfig()
    from src.common import db_batch

    release_thread_routed_file_handlers()  # 同进程重跑时先收掉上一趟的按线 handler, 防重复
    _preload_unified_collect_imports(categories)
    watch = [c for c in categories if c in _KNOWN]
    db_batch.reset_upsert_heartbeat()
    state = OrchestratorState(
        stall_events={c: threading.Event() for c in watch},
    )
    threads: list[threading.Thread] = []
    results_lock = threading.Lock()

    stall_on = bool(cfg.db_stall_warn_sec and cfg.db_stall_warn_sec > 0)
    log_pi = bool(cfg.monitor_interval and cfg.monitor_interval > 0)
    poll = cfg.monitor_interval if log_pi else (10.0 if (stall_on and watch) else 0.0)
    need_monitor = bool(watch and poll > 0 and (log_pi or stall_on))

    thread_log_handlers: list[logging.FileHandler] = []
    thread_log_prev: int = logging.NOTSET
    thread_log_level_changed: bool = False
    if cfg.thread_log_dir:
        from src.common import thread_routed_logging as trl

        base = Path(cfg.thread_log_dir)
        session = base / f"orch_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        spec: list[tuple[str, str]] = [("MainThread", "main")]
        for c in watch:
            spec.append((f"dc-{c}", c))
        if need_monitor:
            spec.append(("dc-monitor", "monitor"))
        thread_log_handlers, thread_log_prev, thread_log_level_changed = trl.install(session, spec)
        trl.write_latest_pointer(base, session)
        logger.info(
            "按线程分文件日志: %s (多终端: scripts/parallel_orch_tails.ps1 -LogDir 指向该目录, 同 base 下 parallel_orch_latest.txt).",
            session,
        )

    def wrap(name: str) -> None:
        from src.common import db_batch as dbb
        dbb.touch_category_heartbeat(name)
        cat_tok = dbb.log_upsert_category_set(name)
        state.start_times[name] = time.perf_counter()
        try:
            r = dispatch_category(name, cfg, state=state)
            r = _orchestrator_stall_reconcile(name, r, state)
            with results_lock:
                state.results.append(r)
        except Exception as e:  # noqa: BLE001
            with results_lock:
                state.results.append(
                    CategoryResult(name, False, "未捕获异常", None, "n/a", 0.0, str(e)),
                )
        finally:
            dbb.log_upsert_category_reset(cat_tok)
            state.start_times.pop(name, None)

    for c in categories:
        if c not in _KNOWN:
            logger.warning("未知类别, 已跳过: %s", c)
            continue
        t = threading.Thread(target=wrap, name=f"dc-{c}", args=(c,), daemon=False)
        threads.append(t)

    mon: threading.Thread | None = None
    if need_monitor:
        mon = threading.Thread(
            name="dc-monitor",
            target=_monitor_loop,
            args=(state, watch, poll, cfg.db_stall_warn_sec, log_pi),
            daemon=True,
        )
        mon.start()

    global _thread_routed_deferred
    try:
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        state.stop_monitor.set()
        if mon is not None:
            mon.join(timeout=2.0)
        if thread_log_handlers:
            _thread_routed_deferred = (
                thread_log_handlers,
                thread_log_prev,
                thread_log_level_changed,
            )
    return sorted(state.results, key=lambda r: r.name)


def main() -> int:
    """保留兼容: 与 ``python -m src.data.unified_collect`` 相同."""
    from src.data import unified_collect

    return unified_collect.main()


if __name__ == "__main__":
    raise SystemExit(main())
