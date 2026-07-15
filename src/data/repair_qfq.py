"""前复权修复 CLI: 检测混用 + 全量刷新.

用法::

    uv run python -m src.data.repair_qfq --detect-only
    uv run python -m src.data.repair_qfq
    uv run python -m src.data.repair_qfq --full
    uv run python -m src.data.repair_qfq --full --concurrency 8 --source qmt

``--full`` 对 ``stocks`` 全市场按 QMT 前复权重拉日 K (``--no-resume``), 一次性消除历史混用。
默认模式仅修复「库内跳变检测 + 近 N 日除权因子」命中的标的。
"""
from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import text

from src.common.db import get_session
from src.common.logger import get_logger
from src.data.kline_ex_div_refresh import (
    collect_codes_needing_qfq_refresh,
    codes_with_ex_dividend_gap_in_db,
    codes_with_recent_ex_date,
    refresh_qfq_klines,
    sync_divid_factors_incremental,
)

logger = get_logger(__name__)

ALL_HISTORY_GAP_DAYS = 36500  # ~100 年, 等效全历史跳变扫描


def all_stock_codes() -> list[str]:
    """``stocks`` 表全部 A 股代码."""
    with get_session() as session:
        rows = session.execute(text("SELECT code FROM stocks ORDER BY code")).fetchall()
    return [r[0] for r in rows]


def summarize_gap_detection(gap_scan_days: int) -> dict[str, int | list[str]]:
    """检测统计 (不下载)."""
    from_factor = codes_with_recent_ex_date()
    from_gap = codes_with_ex_dividend_gap_in_db(gap_scan_days)
    union = sorted(set(from_factor) | set(from_gap))
    return {
        "from_factor": len(from_factor),
        "from_gap": len(from_gap),
        "union": len(union),
        "codes": union,
    }


async def repair_qfq_incremental(
    *,
    source: str = "qmt",
    concurrency: int = 4,
    ex_lookback_days: int = 7,
    gap_scan_days: int = 30,
    divid_sync_days: int = 365,
    skip_divid: bool = False,
) -> dict[str, int]:
    """检测混用标的并全量前复权刷新."""
    divid_rows = 0
    if not skip_divid:
        try:
            divid_rows = sync_divid_factors_incremental(start_days=divid_sync_days)
        except Exception as exc:  # noqa: BLE001
            logger.warning("除权因子同步失败: %s", exc)

    codes = collect_codes_needing_qfq_refresh(ex_lookback_days, gap_scan_days)
    kline_rows = 0
    if codes:
        kline_rows = await refresh_qfq_klines(codes, source=source, concurrency=concurrency)

    remaining = len(codes_with_ex_dividend_gap_in_db(gap_scan_days))
    return {
        "divid_rows": divid_rows,
        "refreshed_codes": len(codes),
        "kline_rows": kline_rows,
        "remaining_gaps": remaining,
    }


async def repair_qfq_full(
    *,
    source: str = "qmt",
    concurrency: int = 8,
    days_back: int = 3650,
    divid_sync_days: int = 3650,
    skip_divid: bool = False,
    gap_scan_days: int = ALL_HISTORY_GAP_DAYS,
) -> dict[str, int]:
    """全市场前复权重拉 (消除全部历史混用)."""
    divid_rows = 0
    if not skip_divid:
        try:
            divid_rows = sync_divid_factors_incremental(start_days=divid_sync_days)
        except Exception as exc:  # noqa: BLE001
            logger.warning("除权因子同步失败: %s", exc)

    gaps_before = len(codes_with_ex_dividend_gap_in_db(gap_scan_days))
    logger.info("全量前复权修复开始: gaps_before=%d, days_back=%d", gaps_before, days_back)

    from src.data import kline_bulk_sync

    kline_rows = await kline_bulk_sync.run(
        mode="stock",
        days_back=days_back,
        source=source,
        concurrency=concurrency,
        resume=False,
        fill_interior_gaps=False,
    )

    gaps_after = len(codes_with_ex_dividend_gap_in_db(gap_scan_days))
    return {
        "divid_rows": divid_rows,
        "kline_rows": int(kline_rows or 0),
        "gaps_before": gaps_before,
        "gaps_after": gaps_after,
        "stock_count": len(all_stock_codes()),
    }


def _print_detect(summary: dict[str, int | list[str]], gap_scan_days: int) -> None:
    print(f"跳变扫描窗口: 近 {gap_scan_days} 自然日")  # noqa: T201
    print(f"  除权因子表(近7日): {summary['from_factor']} 只")  # noqa: T201
    print(f"  库内跳变检测:     {summary['from_gap']} 只")  # noqa: T201
    print(f"  合并待修复:       {summary['union']} 只")  # noqa: T201
    codes = summary.get("codes") or []
    if codes:
        sample = ", ".join(codes[:20])
        suffix = " ..." if len(codes) > 20 else ""
        print(f"  样例: {sample}{suffix}")  # noqa: T201


def _print_result(result: dict[str, int], *, full: bool) -> None:
    print("\n=== repair-qfq 完成 ===")  # noqa: T201
    for k, v in result.items():
        print(f"  {k}: {v}")  # noqa: T201
    if full:
        if result.get("gaps_after", 0) == 0:
            print("  状态: 全历史跳变检测通过, 库内口径已统一为前复权")  # noqa: T201
        else:
            print(  # noqa: T201
                f"  警告: 仍有 {result['gaps_after']} 只跳变待查, "
                "可重跑或检查 QMT/网络"
            )
    elif result.get("remaining_gaps", 0) == 0:
        print("  状态: 扫描窗口内无剩余跳变")  # noqa: T201


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="检测 stock_daily 前复权混用并全量刷新 (MiniQMT dividend_type=front)",
    )
    p.add_argument(
        "--detect-only",
        action="store_true",
        help="仅检测并打印待修复标的, 不下载",
    )
    p.add_argument(
        "--full",
        action="store_true",
        help="全市场前复权重拉 (--no-resume), 一次性修复全部历史",
    )
    p.add_argument(
        "--source",
        choices=["qmt", "auto", "eastmoney", "tencent"],
        default="qmt",
        help="K 线数据源 (默认 qmt)",
    )
    p.add_argument("--concurrency", type=int, default=8, help="并发数 (默认 8)")
    p.add_argument(
        "--days-back",
        type=int,
        default=3650,
        help="--full 时回溯自然日 (默认 3650≈10年)",
    )
    p.add_argument(
        "--gap-scan-days",
        type=int,
        default=30,
        help="跳变检测窗口自然日; --full 完成后用极大值验全历史",
    )
    p.add_argument(
        "--ex-lookback-days",
        type=int,
        default=7,
        help="除权因子表近 N 日除权事件 (增量模式)",
    )
    p.add_argument(
        "--divid-sync-days",
        type=int,
        default=None,
        help="除权因子同步起点 (默认: 增量365 / 全量3650)",
    )
    p.add_argument("--skip-divid", action="store_true", help="跳过除权因子同步")
    return p


async def async_main(args: argparse.Namespace) -> int:
    gap_scan = args.gap_scan_days
    if args.detect_only:
        summary = summarize_gap_detection(gap_scan)
        _print_detect(summary, gap_scan)
        return 0

    divid_days = args.divid_sync_days
    if divid_days is None:
        divid_days = 3650 if args.full else 365

    if args.full:
        result = await repair_qfq_full(
            source=args.source,
            concurrency=max(1, args.concurrency),
            days_back=max(30, args.days_back),
            divid_sync_days=divid_days,
            skip_divid=args.skip_divid,
            gap_scan_days=ALL_HISTORY_GAP_DAYS,
        )
    else:
        result = await repair_qfq_incremental(
            source=args.source,
            concurrency=max(1, args.concurrency),
            ex_lookback_days=args.ex_lookback_days,
            gap_scan_days=gap_scan,
            divid_sync_days=divid_days,
            skip_divid=args.skip_divid,
        )

    _print_result(result, full=args.full)
    if args.full and result.get("gaps_after", 0) > 0:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return asyncio.run(async_main(args))


if __name__ == "__main__":
    sys.exit(main())
