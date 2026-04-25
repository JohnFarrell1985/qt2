"""**统一采集入口** — 一类一线程, 全类与 ETF/股日 K 同构的续传语义.

- **向今** / **向史** / **中缝(可选)**: 见 ``collect_resume.global_series_work_segments``、``kline_bulk_sync.daily_kline_work_segments``;
- **K 线**: ``kline_bulk_sync.run(..., resume=...)``;
- **北向/调研/板块表**: 按表内 min/max 拆段;
- **龙虎榜/资金流**: 按 XSHG 历缺失日;
- **财务(AkShare)**: 仅 ``missing_financial_*_periods`` 缺季;
- QMT 仍受 ``parallel_qmt_orchestrator.QMT_ORCHESTRATOR_LOCK`` 串行保护.

建议::

    uv run python -m src.data.unified_collect
    uv run python -m src.data.unified_collect --no-kline --categories universe,trading_calendar,alt,survey,sector_index,financial
    uv run python -m src.data.unified_collect --include-lhb-mf
"""
from __future__ import annotations

import sys
from src.common.logger import get_logger
from src.data.parallel_qmt_orchestrator import (
    DEFAULT_COLLECT_FLOOR_YMD,
    CategoryResult,
    CollectConfig,
    _KNOWN,
    release_thread_routed_file_handlers,
    run_parallel,
)

logger = get_logger(__name__)

_DEFAULT_CATS = [
    "kline", "universe", "trading_calendar", "financial", "convertible", "factors",
    "sector_index", "alt", "survey", "lhb", "moneyflow",
]


def _log_post_collect_report(res: list[CategoryResult]) -> None:
    """全部线程 join 后: 标出 (1) 编排层仍失败 (2) 成功但本趟行数为 0/None 的种类。"""
    failed = [r for r in res if not r.ok]
    if failed:
        parts: list[str] = []
        for r in failed:
            err = f" err={r.error!r}" if r.error else ""
            parts.append(f"{r.name} source={r.data_source!r} msg={r.message!r}{err}")
        logger.error("==== 采集汇总: 以下种类 QMT+级联/降级后仍 **失败** (ok=False): %s", " | ".join(parts))
    zero_ok = [
        r for r in res
        if r.ok and (r.value is None or (isinstance(r.value, (int, float)) and r.value == 0))
    ]
    if zero_ok:
        parts2 = [f"{r.name} source={r.data_source!r} msg={r.message!r}" for r in zero_ok]
        logger.warning(
            "==== 采集汇总: 以下种类 ok=True 但 value=0/None (可能本趟无新行、无数据、或该种类以 message 为主): %s",
            " | ".join(parts2),
        )
    if not failed and not zero_ok:
        logger.info(
            "==== 采集汇总: 本趟无 ok=False, 且各类 value 非 0(或为非计数语义). 详见上行 [OK]/[FAIL] 明细。",
        )


def main() -> int:
    import argparse

    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass

    p = argparse.ArgumentParser(
        description="统一多线程采集(续传与 kline/ETF 同构, 见 collect_resume + kline_bulk_sync).",
    )
    p.add_argument(
        "--categories",
        default=",".join(_DEFAULT_CATS),
        help="逗号分隔, 见: " + ", ".join(sorted(_KNOWN)),
    )
    p.add_argument(
        "--include-lhb-mf", action="store_true",
        help="(兼容) 默认已含 lhb、moneyflow; 指定后仍再确保二者在列表中",)
    p.add_argument("--no-kline", action="store_true", help="排除 kline")
    p.add_argument("--no-resume", action="store_true", help="全类关闭向今/向史续传(整段 [floor,今日])")
    p.add_argument("--no-interior", action="store_true", help="关闭中缝(与 DATACOLLECT_KLINE_FILL_INTERIOR_GAPS=false 同效)")
    p.add_argument("--no-kline-resume", action="store_true", help="仅 K 线: 等效 kline --no-resume")
    p.add_argument("--kline-days-back", type=int, default=None)
    p.add_argument("--kline-concurrency", type=int, default=8)
    p.add_argument("--index-codes", default="000300.SH,000905.SH,000852.SH")
    p.add_argument("--sector-start", default=DEFAULT_COLLECT_FLOOR_YMD)
    p.add_argument("--hsgt-start", default=DEFAULT_COLLECT_FLOOR_YMD)
    p.add_argument("--survey-start", default=DEFAULT_COLLECT_FLOOR_YMD)
    p.add_argument("--financial-start", default=DEFAULT_COLLECT_FLOOR_YMD)
    p.add_argument("--factor-start", default=DEFAULT_COLLECT_FLOOR_YMD)
    p.add_argument(
        "--lhb-floor", default=DEFAULT_COLLECT_FLOOR_YMD, help="龙虎榜 续传地板 yyyymmdd",
    )
    p.add_argument(
        "--mf-floor", default=DEFAULT_COLLECT_FLOOR_YMD, help="个股资金流 续传地板",
    )
    p.add_argument("--monitor-sec", type=float, default=30.0)
    p.add_argument(
        "--db-stall-warn-sec",
        type=float,
        default=120.0,
        help="某类超过该秒数无**本类**批量落盘, 打 ERROR 并令该类切换数据源: 财务→AkShare, 因子→结束; 0 关闭; "
        "未设 --monitor-sec 时仍每 10s 检测(仅不打印存活 DEBUG)",
    )
    p.add_argument(
        "--sector-no-fund", action="store_true",
        help="sector_index: 不拉东财板块资金排名(仅 K/行业映射 等)",
    )
    p.add_argument(
        "--sector-force-fund", action="store_true",
        help="sector_index: 即使区间 end<今日 仍拉资金快照(东财为实时, trade_date=拉取日)",
    )
    p.add_argument(
        "--thread-log-dir",
        default=None,
        metavar="DIR",
        help="为 MainThread/各采集 dc-线/监控 dc-monitor 各写一 .log(见 parallel_qmt 说明); base 下写 parallel_orch_latest.txt, 可配合 scripts/parallel_orch_tails.ps1 多窗 tail",
    )
    args = p.parse_args()

    cats = [x.strip() for x in args.categories.split(",") if x.strip()]
    if args.no_kline:
        cats = [c for c in cats if c != "kline"]
    if args.include_lhb_mf:
        for x in ("lhb", "moneyflow"):
            if x not in cats:
                cats.append(x)

    cfg = CollectConfig(
        resume=not args.no_resume,
        fill_interior=False if args.no_interior else None,
        kline_resume=not (args.no_resume or args.no_kline_resume),
        kline_days_back=args.kline_days_back,
        kline_concurrency=args.kline_concurrency,
        hsgt_start=args.hsgt_start,
        survey_start=args.survey_start,
        sector_start=args.sector_start,
        financial_start=args.financial_start,
        factor_start=args.factor_start,
        lhb_floor=args.lhb_floor,
        mf_floor=args.mf_floor,
        sector_include_fund_flow=not args.sector_no_fund,
        sector_force_fund_snapshot=bool(args.sector_force_fund),
        index_codes=tuple(x.strip() for x in args.index_codes.split(",") if x.strip()),
        monitor_interval=args.monitor_sec,
        db_stall_warn_sec=args.db_stall_warn_sec,
        thread_log_dir=args.thread_log_dir,
    )

    logger.info("unified_collect 启动: %s (resume=%s, interior=%s, kline_resume=%s)", cats, cfg.resume, cfg.fill_interior, cfg.kline_resume)
    res = run_parallel(cats, cfg)
    for r in res:
        st = "OK" if r.ok else "FAIL"
        logger.info(
            "[%s] %s  source=%s  value=%s  %.1fs  %s",
            st, r.name, r.data_source, r.value, r.duration_sec, r.message,
        )
        if r.error:
            logger.error("  err: %s", r.error)
    _log_post_collect_report(res)
    release_thread_routed_file_handlers()
    return 0 if all(r.ok for r in res) else 1


if __name__ == "__main__":
    raise SystemExit(main())
