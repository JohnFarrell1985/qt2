"""QMT 交易 CLI.

用法:
  python -m src.trading execute --picks reports/candidates_bull_launch_20260707.json --mode paper
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.common.config import PROJECT_ROOT
from src.common.logger import get_logger
from src.trading.live_trading import LiveTradingEngine
from src.trading.paper_trading import PaperTradingEngine

logger = get_logger(__name__)


def _load_picks(path: Path) -> list[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    codes = list(data.get("candidates") or [])
    if not codes and data.get("final_picks"):
        codes = [p["code"] for p in data["final_picks"]]
    return codes


def _build_signals(codes: list[str]) -> list[dict]:
    return [{"code": c, "signal": "buy", "rank": i + 1} for i, c in enumerate(codes)]


def cmd_execute(args: argparse.Namespace) -> None:
    picks_path = Path(args.picks)
    if not picks_path.is_absolute():
        picks_path = PROJECT_ROOT / picks_path
    codes = _load_picks(picks_path)
    if not codes:
        logger.warning("清单为空, 无交易信号")
        return

    signals = _build_signals(codes)
    if args.mode == "live":
        engine = LiveTradingEngine()
        engine.confirm_live_mode()
    else:
        engine = PaperTradingEngine()

    if not engine.connect():
        raise RuntimeError("QMT 连接失败")

    results = engine.execute_signals(signals)
    print(f"执行 {len(results)} 笔委托")
    for r in results:
        print(r)


def main() -> None:
    parser = argparse.ArgumentParser(description="QMT 交易执行")
    sub = parser.add_subparsers(dest="command", required=True)

    p_exec = sub.add_parser("execute", help="根据 candidates 清单下单")
    p_exec.add_argument("--picks", required=True, help="candidates JSON 路径")
    p_exec.add_argument("--mode", choices=["paper", "live"], default="paper")
    p_exec.set_defaults(func=cmd_execute)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
