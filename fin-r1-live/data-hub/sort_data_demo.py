"""
数据排序演示脚本
展示如何按股票代码排序查询数据

功能:
1. 按股票代码排序显示所有股票
2. 按完整度排序显示下载状态
3. 按名称排序显示股票列表
4. 多字段排序（代码 + 日期）
"""
import os
import sys
import argparse
from datetime import datetime
from typing import List, Dict, Any

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import get_db_session, Stock, StockDaily, StockFinancialReport


def print_header(title: str):
    """打印标题"""
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80)


def get_all_stocks_sorted(order_by: str = 'code') -> List[Dict]:
    """
    获取所有股票并排序

    Args:
        order_by: 'code', 'name', 'exchange', 'list_date'
    """
    with get_db_session() as session:
        query = session.query(Stock)

        # 应用排序
        if order_by == 'code':
            query = query.order_by(Stock.code)
        elif order_by == 'name':
            query = query.order_by(Stock.name)
        elif order_by == 'exchange':
            query = query.order_by(Stock.exchange, Stock.code)
        elif order_by == 'list_date':
            query = query.order_by(Stock.list_date)

        stocks = query.all()

        return [
            {
                'code': s.code,
                'name': s.name,
                'exchange': s.exchange,
                'industry': s.industry,
                'pe_ttm': s.pe_ttm,
                'pb': s.pb,
                'market_cap': s.market_cap
            }
            for s in stocks
        ]


def get_stock_daily_sorted(code: str, order_by: str = 'date_desc') -> List[Dict]:
    """
    获取股票日线数据并排序

    Args:
        order_by: 'date_desc', 'date_asc', 'volume_desc', 'change_pct_desc'
    """
    with get_db_session() as session:
        query = session.query(StockDaily).filter_by(code=code)

        # 应用排序
        if order_by == 'date_desc':
            query = query.order_by(StockDaily.trade_date.desc())
        elif order_by == 'date_asc':
            query = query.order_by(StockDaily.trade_date.asc())
        elif order_by == 'volume_desc':
            query = query.order_by(StockDaily.volume.desc())
        elif order_by == 'change_pct_desc':
            query = query.order_by(StockDaily.change_pct.desc())

        daily = query.limit(20).all()

        return [
            {
                'date': d.trade_date.isoformat(),
                'open': d.open,
                'high': d.high,
                'low': d.low,
                'close': d.close,
                'volume': d.volume,
                'change_pct': d.change_pct,
                'turnover_rate': d.turnover_rate
            }
            for d in daily
        ]


def get_download_status_sorted(order_by: str = 'code') -> List[Dict]:
    """
    获取数据下载状态并排序

    Args:
        order_by: 'code', 'completeness', 'daily_count', 'financial_count'
    """
    with get_db_session() as session:
        # 获取所有股票
        stocks = session.query(Stock).order_by(Stock.code).all()

        status_list = []
        for stock in stocks:
            code = stock.code

            # 统计各表数据量
            daily_count = session.query(StockDaily).filter_by(code=code).count()
            financial_count = session.query(StockFinancialReport).filter_by(code=code).count()

            # 计算完整度（假设应有约250个交易日数据）
            expected_daily = 250
            completeness = min(100, (daily_count / expected_daily) * 100)

            status = {
                'code': code,
                'name': stock.name,
                'exchange': stock.exchange,
                'daily_count': daily_count,
                'financial_count': financial_count,
                'completeness': round(completeness, 2)
            }
            status_list.append(status)

        # 应用排序
        if order_by == 'code':
            status_list.sort(key=lambda x: x['code'])
        elif order_by == 'name':
            status_list.sort(key=lambda x: x['name'])
        elif order_by == 'completeness':
            status_list.sort(key=lambda x: x['completeness'], reverse=True)
        elif order_by == 'daily_count':
            status_list.sort(key=lambda x: x['daily_count'], reverse=True)
        elif order_by == 'financial_count':
            status_list.sort(key=lambda x: x['financial_count'], reverse=True)

        return status_list


def demo_sort_stocks():
    """演示按股票代码排序"""
    print_header("演示1: 按股票代码排序显示股票列表")

    stocks = get_all_stocks_sorted(order_by='code')

    print(f"\n总共 {len(stocks)} 只股票，按代码排序（前20只）:")
    print(f"{'代码':<10}{'名称':<15}{'交易所':<8}{'行业':<15}{'市值(亿)':<12}")
    print("-" * 80)

    for stock in stocks[:20]:
        market_cap = f"{stock['market_cap']:.2f}" if stock['market_cap'] else "-"
        print(
            f"{stock['code']:<10}"
            f"{stock['name']:<15}"
            f"{stock['exchange']:<8}"
            f"{stock['industry'] or '-':<15}"
            f"{market_cap:<12}"
        )


def demo_sort_by_name():
    """演示按名称排序"""
    print_header("演示2: 按股票名称排序显示")

    stocks = get_all_stocks_sorted(order_by='name')

    print(f"\n按名称排序（前20只）:")
    print(f"{'名称':<15}{'代码':<10}{'交易所':<8}{'行业':<15}")
    print("-" * 80)

    for stock in stocks[:20]:
        print(
            f"{stock['name']:<15}"
            f"{stock['code']:<10}"
            f"{stock['exchange']:<8}"
            f"{stock['industry'] or '-':<15}"
        )


def demo_sort_daily_data():
    """演示按日期排序日线数据"""
    print_header("演示3: 按日期排序显示日线数据（平安银行000001）")

    # 按日期降序（最新在前）
    daily_desc = get_stock_daily_sorted('000001', order_by='date_desc')

    print("\n按日期降序（最新10条）:")
    print(f"{'日期':<12}{'收盘':<10}{'涨跌%':<10}{'成交量':<15}{'换手%':<10}")
    print("-" * 80)

    for d in daily_desc[:10]:
        change_str = f"{d['change_pct']:+.2f}%" if d['change_pct'] else "-"
        print(
            f"{d['date']:<12}"
            f"{d['close']:<10.2f}"
            f"{change_str:<10}"
            f"{d['volume']:>15,}"
            f"{d['turnover_rate'] or 0:<10.2f}"
        )

    # 按日期升序（最旧在前）
    daily_asc = get_stock_daily_sorted('000001', order_by='date_asc')

    print("\n按日期升序（最旧10条）:")
    print(f"{'日期':<12}{'收盘':<10}{'涨跌%':<10}{'成交量':<15}{'换手%':<10}")
    print("-" * 80)

    for d in daily_asc[:10]:
        change_str = f"{d['change_pct']:+.2f}%" if d['change_pct'] else "-"
        print(
            f"{d['date']:<12}"
            f"{d['close']:<10.2f}"
            f"{change_str:<10}"
            f"{d['volume']:>15,}"
            f"{d['turnover_rate'] or 0:<10.2f}"
        )


def demo_sort_download_status():
    """演示按完整度排序下载状态"""
    print_header("演示4: 按数据完整度排序")

    status = get_download_status_sorted(order_by='completeness')

    print(f"\n按数据完整度排序（前20只）:")
    print(f"{'代码':<10}{'名称':<15}{'日线数':<10}{'财务数':<10}{'完整度':<12}{'状态'}")
    print("-" * 80)

    for s in status[:20]:
        if s['completeness'] >= 90:
            status_icon = "✅ 完整"
        elif s['completeness'] >= 50:
            status_icon = "⚠️  部分"
        else:
            status_icon = "❌ 不足"

        print(
            f"{s['code']:<10}"
            f"{s['name']:<15}"
            f"{s['daily_count']:<10}"
            f"{s['financial_count']:<10}"
            f"{s['completeness']:>6.2f}%"
            f"  {status_icon}"
        )

    # 显示统计
    complete = sum(1 for s in status if s['completeness'] >= 90)
    partial = sum(1 for s in status if 50 <= s['completeness'] < 90)
    insufficient = sum(1 for s in status if s['completeness'] < 50)

    print(f"\n统计: 完整 {complete} 只, 部分 {partial} 只, 不足 {insufficient} 只")


def demo_multi_field_sort():
    """演示多字段排序"""
    print_header("演示5: 多字段排序（交易所 + 股票代码）")

    with get_db_session() as session:
        # 先按交易所排序，再按股票代码排序
        stocks = session.query(Stock).order_by(
            Stock.exchange.asc(),
            Stock.code.asc()
        ).all()

        print(f"\n按交易所分组，再按代码排序（前30只）:")
        print(f"{'交易所':<8}{'代码':<10}{'名称':<15}{'行业':<15}")
        print("-" * 80)

        current_exchange = None
        for stock in stocks[:30]:
            # 当交易所变化时打印分隔线
            if stock.exchange != current_exchange:
                if current_exchange:
                    print("-" * 80)
                current_exchange = stock.exchange
                print(f"\n【{stock.exchange}交易所】")

            print(
                f"{'':8}"
                f"{stock.code:<10}"
                f"{stock.name:<15}"
                f"{stock.industry or '-':<15}"
            )


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description='数据排序演示')
    parser.add_argument('--demo', type=int, default=0,
                        help='运行指定演示 (1-5)，0表示运行所有')
    parser.add_argument('--limit', type=int, default=20,
                        help='显示记录数量限制')

    args = parser.parse_args()

    print("\n" + "=" * 80)
    print(" Fin-R1 数据排序演示")
    print("=" * 80)
    print(f"时间: {datetime.now().isoformat()}")

    demos = {
        1: demo_sort_stocks,
        2: demo_sort_by_name,
        3: demo_sort_daily_data,
        4: demo_sort_download_status,
        5: demo_multi_field_sort
    }

    if args.demo in demos:
        # 运行指定演示
        demos[args.demo]()
    else:
        # 运行所有演示
        for i in range(1, 6):
            try:
                demos[i]()
            except Exception as e:
                print(f"\n演示 {i} 出错: {e}")

    print("\n" + "=" * 80)
    print(" 演示结束")
    print("=" * 80)


if __name__ == "__main__":
    main()
