"""回测运行入口

用法:
  python scripts/run_backtest.py --picks-file reports/candidates_bull_launch_20260707.json
  python scripts/run_backtest.py --screen --start 2025-01-01 --end 2025-06-30
"""
import argparse
import sys

sys.path.insert(0, ".")

from datetime import date

from src.common.logger import get_logger
from src.backtest.stock_picker import CachedPicker, MockPicker
from src.backtest.strategy_runner import run_continuous, StrategyConfig
from src.backtest.performance import full_performance_report
from src.selection.ma_screener import screen_universe

logger = get_logger(__name__)


def _build_ma_schedule(start: date, end: date) -> dict[date, list[str]]:
    from src.backtest.data_loader import get_trading_dates

    schedule: dict[date, list[str]] = {}
    for td in get_trading_dates(start, end):
        codes, _ = screen_universe(td)
        schedule[td] = codes[:5]
    return schedule


def main():
    parser = argparse.ArgumentParser(description="选股清单回测")
    parser.add_argument("--picks-file", help="selection 输出的 candidates JSON")
    parser.add_argument("--picks-dir", help="reports 目录 (加载 candidates_*.json)")
    parser.add_argument("--screen", action="store_true", help="回测区间内每日 MA 初筛")
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--capital", type=float, default=1_000_000)
    args = parser.parse_args()

    start_date = date.fromisoformat(args.start)
    end_date = date.fromisoformat(args.end)

    if args.picks_file:
        picker = CachedPicker(picks_file=args.picks_file)
    elif args.picks_dir:
        picker = CachedPicker(picks_dir=args.picks_dir)
    elif args.screen:
        schedule = _build_ma_schedule(start_date, end_date)
        picker = MockPicker(schedule=schedule)
    else:
        parser.error("请指定 --picks-file / --picks-dir 或 --screen")

    config = StrategyConfig(
        initial_capital=args.capital,
        max_position_pct=0.30,
        max_holdings=5,
    )

    result = run_continuous(
        picker=picker,
        start_date=start_date,
        end_date=end_date,
        config=config,
    )

    print(f"回测完成: {result.to_dict()}")
    perf = full_performance_report(result.equity_curve)
    print(f"绩效: {perf}")


if __name__ == "__main__":
    main()
