"""CLI: MA 程序选股.

用法:
  python -m src.selection screen --date 2026-07-07
  python -m src.selection screen --date 2026-07-07 --strategy bear_rebound --csv
"""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from src.common.config import apply_strategy, list_strategies
from src.selection.workflow import run_screen


def _parse_date(s: str | None) -> date:
    if not s:
        return date.today()
    return date.fromisoformat(s)


def cmd_screen(args: argparse.Namespace) -> None:
    trade_date = _parse_date(args.date)
    out = Path(args.output) if args.output else None
    report = run_screen(trade_date, out, csv_also=args.csv)
    print(f"MA 初筛: {report['ma_candidates']} 只 → {out or 'reports/'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="MA 程序选股")
    parser.add_argument(
        "--strategy",
        choices=list_strategies(),
        help="选股策略 preset (默认 app.json / SELECTION_STRATEGY)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_screen = sub.add_parser("screen", help="MA 初筛")
    p_screen.add_argument("--date", help="交易日期 YYYY-MM-DD")
    p_screen.add_argument("--output", help="输出 JSON 路径")
    p_screen.add_argument("--csv", action="store_true", help="同时输出 CSV")
    p_screen.set_defaults(func=cmd_screen)

    args = parser.parse_args()
    if args.strategy:
        apply_strategy(args.strategy)
    args.func(args)


if __name__ == "__main__":
    main()
