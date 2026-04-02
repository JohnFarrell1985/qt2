"""回测运行入口"""
import sys
sys.path.insert(0, ".")

from datetime import date
from src.common.logger import get_logger
from src.backtest.stock_picker import RandomPicker
from src.backtest.strategy_runner import run_strategy, StrategyConfig
from src.backtest.performance import full_performance_report

logger = get_logger(__name__)


def main():
    pool = ["000001", "600519", "000002", "600036", "601318"]
    picker = RandomPicker(pool, pick_count=1, seed=42)

    config = StrategyConfig(
        initial_capital=1_000_000,
        max_position_pct=0.30,
        max_holdings=3,
    )

    result = run_strategy(
        picker=picker,
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        config=config,
    )

    print(f"回测结果: {result.to_dict()}")

    perf = full_performance_report(result.equity_curve)
    print(f"绩效指标: {perf}")


if __name__ == "__main__":
    main()
