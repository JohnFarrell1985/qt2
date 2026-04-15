"""
量化回溯命令行工具 - 支持A股和港股通

用法:
  # A股单笔交易
  python -m backtest.cli trade 000001 --buy 2025-01-02 --sell 2025-06-30 --qty 1000

  # 港股通单笔交易 (5位代码或HK前缀)
  python -m backtest.cli trade 00700 --buy 2025-01-02 --sell 2025-06-30 --qty 200
  python -m backtest.cli trade HK00700 --buy 2025-01-02 --sell 2025-06-30 --amount 50000

  # 多笔交易批量回溯 (从JSON文件, A股港股可混合)
  python -m backtest.cli portfolio trades.json

  # 交互式模式
  python -m backtest.cli interactive

  # 查看数据范围
  python -m backtest.cli info 000001
"""
import argparse
import json
import sys
from datetime import datetime
from typing import List

from .engine import calc_single_trade, calc_portfolio, TradeResult
from .fees import FeeConfig, detect_market
from .data_loader import get_stock_name, get_data_range


# ======== 格式化输出 ========

def print_divider(char="=", width=60):
    print(char * width)


def print_trade_result(r: TradeResult):
    """格式化打印单笔交易结果"""
    market = detect_market(r.code)
    currency = "港元" if market == "HK" else "元"
    market_label = "[港股通]" if market == "HK" else "[A股]"

    print_divider()
    label = f" {r.code} {r.name or ''} {market_label} 交易回溯 "
    print(f"{label:=^54}")
    print_divider()

    print(f"\n  {'买入':>8}  {r.buy_date}  价格: {r.buy_price:.2f}  数量: {r.buy_quantity}股")
    print(f"  {'卖出':>8}  {r.sell_date}  价格: {r.sell_price:.2f}  数量: {r.sell_quantity}股")
    print(f"  {'持仓':>8}  {r.holding_days} 天")

    print("\n  --- 费用明细 ---")
    if market == "HK":
        # 港股通: 买卖双方均收全部费用
        print(f"  {'买入佣金':>10}  {r.buy_fees.commission:>10.2f} {currency}")
        print(f"  {'买入印花税':>10}  {r.buy_fees.stamp_tax:>10.2f} {currency}")
        if r.buy_fees.transfer_fee > 0:
            print(f"  {'买入杂费':>10}  {r.buy_fees.transfer_fee:>10.2f} {currency}  (交易费+征费+交收费)")
        print(f"  {'卖出佣金':>10}  {r.sell_fees.commission:>10.2f} {currency}")
        print(f"  {'卖出印花税':>10}  {r.sell_fees.stamp_tax:>10.2f} {currency}")
        if r.sell_fees.transfer_fee > 0:
            print(f"  {'卖出杂费':>10}  {r.sell_fees.transfer_fee:>10.2f} {currency}  (交易费+征费+交收费)")
    else:
        # A股
        print(f"  {'买入佣金':>10}  {r.buy_fees.commission:>10.2f} {currency}")
        if r.buy_fees.transfer_fee > 0:
            print(f"  {'买入过户费':>10}  {r.buy_fees.transfer_fee:>10.2f} {currency}")
        print(f"  {'卖出佣金':>10}  {r.sell_fees.commission:>10.2f} {currency}")
        print(f"  {'卖出印花税':>10}  {r.sell_fees.stamp_tax:>10.2f} {currency}")
        if r.sell_fees.transfer_fee > 0:
            print(f"  {'卖出过户费':>10}  {r.sell_fees.transfer_fee:>10.2f} {currency}")
    print(f"  {'费用合计':>10}  {r.total_fees:>10.2f} {currency}")

    print("\n  --- 盈亏 ---")
    print(f"  {'买入总额':>10}  {r.buy_amount:>12.2f} {currency}")
    print(f"  {'卖出净额':>10}  {r.sell_amount:>12.2f} {currency}")
    profit_sign = "+" if r.net_profit >= 0 else ""
    color_start = "\033[32m" if r.net_profit >= 0 else "\033[31m"
    color_end = "\033[0m"
    print(f"  {'净盈亏':>10}  {color_start}{profit_sign}{r.net_profit:>12.2f} {currency}  ({profit_sign}{r.profit_pct:.2f}%){color_end}")

    if r.period_high or r.period_low:
        print("\n  --- 持仓期间行情 ---")
        if r.period_high:
            print(f"  {'区间最高':>10}  {r.period_high:.2f}")
        if r.period_low:
            print(f"  {'区间最低':>10}  {r.period_low:.2f}")
        if r.max_drawdown_pct is not None:
            print(f"  {'最大回撤':>10}  {r.max_drawdown_pct:.2f}%")

    print_divider()
    print()


def print_portfolio_summary(s):
    """格式化打印汇总统计"""
    print_divider("=", 60)
    print(f"{'  交易汇总统计  ':=^56}")
    print_divider("=", 60)

    print(f"\n  {'统计区间':>12}  {s.start_date} ~ {s.end_date}")
    print(f"  {'总交易笔数':>12}  {s.total_trades}")
    print(f"  {'盈利笔数':>12}  {s.win_trades}")
    print(f"  {'亏损笔数':>12}  {s.lose_trades}")
    print(f"  {'胜率':>12}  {s.win_rate:.1f}%")

    print("\n  --- 资金 ---")
    print(f"  {'总投入':>12}  {s.total_invested:>14.2f} 元")
    print(f"  {'总收回':>12}  {s.total_returned:>14.2f} 元")
    print(f"  {'总手续费':>12}  {s.total_fees:>14.2f} 元")

    profit_sign = "+" if s.net_profit >= 0 else ""
    color_start = "\033[32m" if s.net_profit >= 0 else "\033[31m"
    color_end = "\033[0m"
    print(f"  {'净盈亏':>12}  {color_start}{profit_sign}{s.net_profit:>14.2f} 元  ({profit_sign}{s.profit_pct:.2f}%){color_end}")

    print("\n  --- 统计 ---")
    print(f"  {'单笔最大盈利':>12}  {s.max_single_profit:>14.2f} 元")
    print(f"  {'单笔最大亏损':>12}  {s.max_single_loss:>14.2f} 元")
    print(f"  {'平均每笔盈亏':>12}  {s.avg_profit_per_trade:>14.2f} 元")
    print(f"  {'平均持仓天数':>12}  {s.avg_holding_days:>14.1f} 天")

    print_divider("=", 60)
    print()


# ======== 子命令 ========

def cmd_trade(args):
    """单笔交易回溯"""
    buy_date = datetime.strptime(args.buy, "%Y-%m-%d").date()
    sell_date = datetime.strptime(args.sell, "%Y-%m-%d").date()

    fee_config = FeeConfig()
    if args.commission is not None:
        fee_config.commission_rate = args.commission
    if args.stamp_tax is not None:
        fee_config.stamp_tax_rate = args.stamp_tax

    try:
        result = calc_single_trade(
            code=args.code,
            buy_date=buy_date,
            sell_date=sell_date,
            quantity=args.qty or 0,
            buy_amount=args.amount or 0.0,
            fee_config=fee_config,
        )
        print_trade_result(result)

        if args.json:
            print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))

    except ValueError as e:
        print(f"\n  [ERROR] {e}\n", file=sys.stderr)
        sys.exit(1)


def cmd_portfolio(args):
    """多笔交易批量回溯"""
    with open(args.file, "r", encoding="utf-8") as f:
        trade_list = json.load(f)

    fee_config = FeeConfig()
    results: List[TradeResult] = []

    for i, t in enumerate(trade_list, 1):
        try:
            r = calc_single_trade(
                code=t["code"],
                buy_date=datetime.strptime(t["buy_date"], "%Y-%m-%d").date(),
                sell_date=datetime.strptime(t["sell_date"], "%Y-%m-%d").date(),
                quantity=t.get("quantity", 0),
                buy_amount=t.get("amount", 0.0),
                fee_config=fee_config,
            )
            results.append(r)
            print_trade_result(r)
        except ValueError as e:
            print(f"\n  [SKIP] 第{i}笔交易失败: {e}\n", file=sys.stderr)

    if results:
        summary = calc_portfolio(results)
        print_portfolio_summary(summary)

        if args.json:
            print(json.dumps(summary.to_dict(), ensure_ascii=False, indent=2))
    else:
        print("  没有有效的交易记录。")


def cmd_interactive(args):
    """交互式输入交易"""
    print("\n  量化回溯 - 交互式模式")
    print("  输入 'q' 退出, 's' 查看汇总统计\n")

    trades: List[TradeResult] = []
    fee_config = FeeConfig()

    while True:
        try:
            code = input("  股票代码 (如 000001): ").strip()
            if code.lower() == 'q':
                break
            if code.lower() == 's':
                if trades:
                    summary = calc_portfolio(trades)
                    print_portfolio_summary(summary)
                else:
                    print("  暂无交易记录\n")
                continue

            name = get_stock_name(code)
            if name:
                print(f"  >> {name}")

            buy_str = input("  买入日期 (YYYY-MM-DD): ").strip()
            sell_str = input("  卖出日期 (YYYY-MM-DD): ").strip()

            mode = input("  按数量(q)还是金额(a)? [q/a]: ").strip().lower()
            qty = 0
            amount = 0.0
            if mode == 'a':
                amount = float(input("  买入金额 (元): ").strip())
            else:
                qty = int(input("  买入数量 (股): ").strip())

            buy_date = datetime.strptime(buy_str, "%Y-%m-%d").date()
            sell_date = datetime.strptime(sell_str, "%Y-%m-%d").date()

            result = calc_single_trade(code, buy_date, sell_date, qty, amount, fee_config)
            trades.append(result)
            print_trade_result(result)

        except ValueError as e:
            print(f"\n  [ERROR] {e}\n")
        except (KeyboardInterrupt, EOFError):
            print()
            break

    if trades:
        print("\n  是否查看汇总统计? [Y/n]: ", end="")
        try:
            ans = input().strip().lower()
        except (KeyboardInterrupt, EOFError):
            ans = 'n'
        if ans != 'n':
            summary = calc_portfolio(trades)
            print_portfolio_summary(summary)


def cmd_info(args):
    """查看股票数据信息"""
    name = get_stock_name(args.code)
    data_range = get_data_range(args.code)

    print_divider()
    print(f"  股票代码: {args.code}")
    print(f"  股票名称: {name or '未知'}")

    if data_range:
        print(f"  数据范围: {data_range['min_date']} ~ {data_range['max_date']}")
        print(f"  交易天数: {data_range['total_days']} 天")
    else:
        print("  数据: 无记录")
    print_divider()


# ======== 主入口 ========

def main():
    parser = argparse.ArgumentParser(
        description="Fin-R1 量化回溯工具 - 基于PostgreSQL历史数据计算交易盈亏",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 单笔交易 - 按数量
  python -m backtest.cli trade 000001 --buy 2025-01-02 --sell 2025-06-30 --qty 1000

  # 单笔交易 - 按金额
  python -m backtest.cli trade 600519 --buy 2025-03-01 --sell 2025-09-01 --amount 100000

  # 批量交易 (从JSON文件)
  python -m backtest.cli portfolio trades.json

  # 交互式模式
  python -m backtest.cli interactive

  # 查看股票数据范围
  python -m backtest.cli info 000001
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # trade 子命令
    p_trade = subparsers.add_parser("trade", help="单笔交易回溯")
    p_trade.add_argument("code", help="股票代码, 如 000001")
    p_trade.add_argument("--buy", required=True, help="买入日期 YYYY-MM-DD")
    p_trade.add_argument("--sell", required=True, help="卖出日期 YYYY-MM-DD")
    p_trade.add_argument("--qty", type=int, help="买入数量(股)")
    p_trade.add_argument("--amount", type=float, help="买入金额(元)")
    p_trade.add_argument("--commission", type=float, help="佣金费率 (默认0.000115, 万1.15)")
    p_trade.add_argument("--stamp-tax", type=float, help="印花税率 (默认0.0005, 千0.5)")
    p_trade.add_argument("--json", action="store_true", help="同时输出JSON格式")
    p_trade.set_defaults(func=cmd_trade)

    # portfolio 子命令
    p_port = subparsers.add_parser("portfolio", help="多笔交易批量回溯")
    p_port.add_argument("file", help="交易记录JSON文件")
    p_port.add_argument("--json", action="store_true", help="同时输出JSON格式")
    p_port.set_defaults(func=cmd_portfolio)

    # interactive 子命令
    p_inter = subparsers.add_parser("interactive", help="交互式输入交易")
    p_inter.set_defaults(func=cmd_interactive)

    # info 子命令
    p_info = subparsers.add_parser("info", help="查看股票数据范围")
    p_info.add_argument("code", help="股票代码")
    p_info.set_defaults(func=cmd_info)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(0)

    args.func(args)


if __name__ == "__main__":
    main()
