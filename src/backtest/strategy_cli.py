"""
策略回测命令行工具

用法:
  # 使用 mock 选股 JSON 运行全年策略
  python -m backtest.strategy_cli run --schedule mock_schedule.json

  # 指定日期范围和初始资金
  python -m backtest.strategy_cli run --schedule mock_schedule.json \
      --start 2025-01-01 --end 2025-12-31 --capital 1000000

  # 生成 mock 选股计划 (基于股票池每隔N个交易日随机选股)
  python -m backtest.strategy_cli generate-mock --output mock_schedule.json \
      --pool 000001,600519,000002,600036 --interval 3 --count 2

  # 输出JSON报告
  python -m backtest.strategy_cli run --schedule mock_schedule.json --json --output report.json
"""
import argparse
import json
import logging
import sys
from datetime import datetime
from typing import List

from .stock_picker import MockPicker, RandomPicker, load_prompt
from .strategy_runner import run_strategy, run_continuous, StrategyConfig, StrategyResult, DayTrade
from .data_loader import get_trading_dates
from .fees import FeeConfig

logger = logging.getLogger(__name__)


# ======== 格式化输出 ========

def print_divider(char="=", width=70):
    print(char * width)


def print_strategy_result(result: StrategyResult):
    """格式化打印策略回测结果"""
    print()
    print_divider()
    mode = "连续持仓" if result.avg_holding_days > 1.05 else "T+1 隔日卖出"
    print(f"{'  ' + mode + '策略 回测报告  ':=^62}")
    print_divider()

    print(f"\n  {'回测区间':>12}  {result.start_date} ~ {result.end_date}")
    print(f"  {'初始资金':>12}  {result.initial_capital:>14,.2f} 元")
    print(f"  {'最终资金':>12}  {result.final_capital:>14,.2f} 元")

    color_start = "\033[32m" if result.total_return >= 0 else "\033[31m"
    color_end = "\033[0m"
    sign = "+" if result.total_return >= 0 else ""

    print(f"  {'总收益':>12}  {color_start}{sign}{result.total_return:>14,.2f} 元{color_end}")
    print(f"  {'收益率':>12}  {color_start}{sign}{result.total_return_pct:.2f}%{color_end}")
    print(f"  {'年化收益率':>12}  {color_start}{sign}{result.annualized_return_pct:.2f}%{color_end}")

    print("\n  --- 交易统计 ---")
    print(f"  {'成交笔数':>12}  {result.total_trades}")
    print(f"  {'盈利笔数':>12}  {result.win_trades}")
    print(f"  {'亏损笔数':>12}  {result.lose_trades}")
    print(f"  {'跳过笔数':>12}  {result.skipped_trades}  (涨停/无数据)")
    print(f"  {'胜率':>12}  {result.win_rate:.1f}%")

    print(f"  {'平均持仓天数':>12}  {result.avg_holding_days:.1f} 天")

    print("\n  --- 盈亏明细 ---")
    print(f"  {'总手续费':>12}  {result.total_fees:>14,.2f} 元")
    print(f"  {'单笔最大盈利':>12}  {result.max_single_profit:>14,.2f} 元")
    print(f"  {'单笔最大亏损':>12}  {result.max_single_loss:>14,.2f} 元")
    print(f"  {'平均每笔盈亏':>12}  {result.avg_profit_per_trade:>14,.2f} 元")

    print_divider()
    print()


def print_trade_detail(trades: List[DayTrade], limit: int = 20):
    """打印交易明细 (最近N笔)"""
    if not trades:
        print("  无交易记录")
        return

    total = len(trades)
    show = trades[-limit:] if total > limit else trades
    if total > limit:
        print(f"\n  (显示最近 {limit} / {total} 笔交易)\n")

    header = f"  {'选股日':>12} {'代码':>8} {'买入价':>10} {'卖出价':>10} {'数量':>8} {'盈亏':>12} {'收益率':>8}"
    print(header)
    print("  " + "-" * 72)

    for t in show:
        sign = "+" if t.profit >= 0 else ""
        color = "\033[32m" if t.profit >= 0 else "\033[31m"
        end = "\033[0m"
        print(
            f"  {t.pick_date!s:>12} {t.code:>8} {t.buy_price:>10.2f} {t.sell_price:>10.2f} "
            f"{t.quantity:>8} {color}{sign}{t.profit:>12,.2f}{end} {color}{sign}{t.profit_pct:.2f}%{end}"
        )

    print()


def print_skipped_detail(skipped: List[DayTrade], limit: int = 10):
    """打印跳过的交易"""
    if not skipped:
        return

    total = len(skipped)
    show = skipped[:limit]
    print(f"\n  --- 跳过的交易 (前 {min(limit, total)} / {total} 笔) ---")
    for t in show:
        print(f"  {t.pick_date} {t.code:>8}  {t.skip_reason}")
    print()


def print_equity_curve(curve: List[dict], sample_interval: int = 20):
    """简略打印净值曲线 (每N个交易日采样一次)"""
    if not curve:
        return

    print(f"\n  --- 净值曲线 (每{sample_interval}个交易日) ---")
    initial = curve[0]["capital"] if curve else 0
    for i, point in enumerate(curve):
        if i % sample_interval == 0 or i == len(curve) - 1:
            cap = point["capital"]
            ret = ((cap - initial) / initial * 100) if initial else 0
            sign = "+" if ret >= 0 else ""
            print(f"  {point['date']}  资金: {cap:>14,.2f}  收益: {sign}{ret:.2f}%")
    print()


# ======== 子命令 ========

def cmd_run(args):
    """运行策略回测"""
    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()

    fee_config = FeeConfig()
    if args.commission is not None:
        fee_config.commission_rate = args.commission

    fixed_amt = getattr(args, 'per_stock_amount', None)
    strategy_config = StrategyConfig(
        initial_capital=args.capital,
        max_position_pct=args.max_position,
        max_holdings=args.max_holdings,
        limit_up_threshold=args.limit_up,
        fee_config=fee_config,
        fixed_amount_per_stock=fixed_amt,
    )

    # 加载选股器
    if args.schedule:
        picker = MockPicker(schedule_file=args.schedule)
        logger.info(f"使用 MockPicker, 加载 {args.schedule}")
    elif args.random_pool:
        pool = [c.strip() for c in args.random_pool.split(",")]
        picker = RandomPicker(pool, pick_count=args.random_count, seed=args.seed)
        logger.info(f"使用 RandomPicker, 股票池: {pool}")
    else:
        print("[ERROR] 请指定 --schedule 或 --random-pool", file=sys.stderr)
        sys.exit(1)

    prompt_text = ""
    prompt_template_name = ""
    if args.prompt:
        if args.continuous:
            prompt_template_name = args.prompt
            logger.info(f"连续持仓模式: 每天用模板 {args.prompt} 替换日期")
        else:
            prompt_text = load_prompt(name=args.prompt, trade_date=start)
        logger.info(f"使用提示词模板: {args.prompt}")
    elif args.prompt_file:
        with open(args.prompt_file, "r", encoding="utf-8") as f:
            prompt_text = f.read()

    try:
        if args.continuous:
            result = run_continuous(
                picker=picker,
                start_date=start,
                end_date=end,
                config=strategy_config,
                prompt=prompt_text,
                prompt_template=prompt_template_name,
            )
        else:
            result = run_strategy(
                picker=picker,
                start_date=start,
                end_date=end,
                config=strategy_config,
                prompt=prompt_text,
            )
    except ValueError as e:
        print(f"\n  [ERROR] {e}\n", file=sys.stderr)
        sys.exit(1)

    # 输出结果
    print_strategy_result(result)

    if args.detail:
        print_trade_detail(result.trades, limit=args.detail_limit)
        print_skipped_detail(result.skipped)

    if args.curve:
        print_equity_curve(result.equity_curve, sample_interval=args.curve_interval)

    # JSON输出
    if args.json:
        report = result.to_dict()
        if args.detail:
            report["trades"] = [
                {
                    "pick_date": t.pick_date.isoformat(),
                    "code": t.code,
                    "buy_date": t.buy_date.isoformat(),
                    "sell_date": t.sell_date.isoformat(),
                    "buy_price": t.buy_price,
                    "sell_price": t.sell_price,
                    "quantity": t.quantity,
                    "profit": t.profit,
                    "profit_pct": t.profit_pct,
                } for t in result.trades
            ]
            report["skipped"] = [
                {
                    "code": t.code,
                    "pick_date": t.pick_date.isoformat(),
                    "reason": t.skip_reason,
                } for t in result.skipped
            ]
        report["equity_curve"] = result.equity_curve

        json_str = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(json_str)
            print(f"  报告已保存: {args.output}")
        else:
            print(json_str)


def cmd_generate_mock(args):
    """生成 mock 选股计划"""
    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()
    pool = [c.strip() for c in args.pool.split(",")]

    trading_dates = get_trading_dates(start, end)
    if not trading_dates:
        print(f"[ERROR] {start}~{end} 无交易日数据", file=sys.stderr)
        sys.exit(1)

    import random
    rng = random.Random(args.seed)
    schedule = {}

    for i, td in enumerate(trading_dates):
        if i % args.interval == 0:
            n = min(args.count, len(pool))
            picks = rng.sample(pool, n)
            schedule[td.isoformat()] = picks

    output = args.output or "mock_schedule.json"
    with open(output, "w", encoding="utf-8") as f:
        json.dump(schedule, f, ensure_ascii=False, indent=2)

    print(f"  Mock 选股计划已生成: {output}")
    print(f"  交易日数: {len(trading_dates)}, 选股日数: {len(schedule)}, 股票池: {len(pool)}")


# ======== 主入口 ========

def main():
    parser = argparse.ArgumentParser(
        description="Fin-R1 策略回测工具 (隔日卖出 / 连续持仓)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 连续持仓模式 (选股重复则续持, 不再选中才卖出)
  python -m backtest.strategy_cli run --schedule mock.json --continuous --prompt prompt1.txt

  # 简单隔日卖出模式
  python -m backtest.strategy_cli run --schedule mock_schedule.json

  # 随机选股基线测试
  python -m backtest.strategy_cli run --random-pool 000001,600519,000002 --random-count 1

  # 生成 mock 选股计划 (每天选股)
  python -m backtest.strategy_cli generate-mock --pool 000001,600519,000002 --interval 1 --count 2

  # 带详细交易明细和净值曲线
  python -m backtest.strategy_cli run --schedule mock.json --continuous --detail --curve

  # 输出JSON报告到文件
  python -m backtest.strategy_cli run --schedule mock.json --json --output report.json
        """,
    )

    parser.add_argument("-v", "--verbose", action="store_true", help="详细日志")

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # run 子命令
    p_run = subparsers.add_parser("run", help="运行策略回测")
    p_run.add_argument("--continuous", action="store_true",
                        help="连续持仓模式 (选股重复则续持, 不再选中才卖出)")
    p_run.add_argument("--schedule", help="Mock 选股 JSON 文件路径")
    p_run.add_argument("--random-pool", help="随机选股股票池 (逗号分隔)")
    p_run.add_argument("--random-count", type=int, default=1, help="每次随机选几只 (默认1)")
    p_run.add_argument("--seed", type=int, default=42, help="随机种子")
    p_run.add_argument("--prompt", help="提示词模板名称 (从 prompts/ 目录加载, 如 prompt1.txt)")
    p_run.add_argument("--prompt-file", help="提示词文件完整路径 (直接读取, 不做模板替换)")
    p_run.add_argument("--start", default="2025-01-01", help="回测起始 (默认2025-01-01)")
    p_run.add_argument("--end", default="2025-12-31", help="回测结束 (默认2025-12-31)")
    p_run.add_argument("--capital", type=float, default=1_000_000, help="初始资金 (默认100万)")
    p_run.add_argument("--max-position", type=float, default=0.3, help="单股最大仓位比例")
    p_run.add_argument("--max-holdings", type=int, default=3, help="最大持仓数")
    p_run.add_argument("--limit-up", type=float, default=9.8, help="涨停阈值%%")
    p_run.add_argument("--per-stock-amount", type=float, help="每只股票固定买入金额 (如100000)")
    p_run.add_argument("--commission", type=float, help="佣金费率")
    p_run.add_argument("--detail", action="store_true", help="显示交易明细")
    p_run.add_argument("--detail-limit", type=int, default=50, help="交易明细显示条数")
    p_run.add_argument("--curve", action="store_true", help="显示净值曲线")
    p_run.add_argument("--curve-interval", type=int, default=20, help="净值曲线采样间隔")
    p_run.add_argument("--json", action="store_true", help="输出JSON格式")
    p_run.add_argument("--output", help="JSON报告输出文件")
    p_run.set_defaults(func=cmd_run)

    # generate-mock 子命令
    p_gen = subparsers.add_parser("generate-mock", help="生成 mock 选股计划")
    p_gen.add_argument("--pool", required=True, help="股票池 (逗号分隔)")
    p_gen.add_argument("--interval", type=int, default=5, help="每隔N个交易日选股一次 (默认5)")
    p_gen.add_argument("--count", type=int, default=1, help="每次选几只 (默认1)")
    p_gen.add_argument("--start", default="2025-01-01", help="起始日期")
    p_gen.add_argument("--end", default="2025-12-31", help="结束日期")
    p_gen.add_argument("--seed", type=int, default=42, help="随机种子")
    p_gen.add_argument("--output", help="输出文件路径 (默认mock_schedule.json)")
    p_gen.set_defaults(func=cmd_generate_mock)

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(asctime)s %(name)s %(message)s")
    else:
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if not args.command:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
