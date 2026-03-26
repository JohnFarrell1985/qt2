"""
Fin-R1 Data Hub - Data Inventory & Completeness Check
数据清单和完整性检查模块

功能:
1. 列出所有数据表和字段
2. 检查数据下载完整性
3. 按股票代码排序显示下载状态
4. 生成数据缺失报告
5. 推荐未下载的数据类型

使用:
    python data_inventory.py              # 完整数据清单
    python data_inventory.py --check      # 检查完整性
    python data_inventory.py --missing    # 显示缺失数据
    python data_inventory.py --sort       # 按股票代码排序
"""
import os
import sys
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional, Any, Tuple
from collections import defaultdict, OrderedDict

from database import (
    get_db_session, init_database,
    Stock, StockDaily, StockRealtime, MarketIndex, SectorData,
    StockFinancialReport, StockFinancialIndicator, DataSyncLog
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class DataInventory:
    """数据清单管理器"""

    # 定义所有数据表及其重要性
    DATA_TABLES = {
        'stocks': {
            'name': '股票基础信息',
            'required': True,
            'description': '所有A股股票列表和基础信息',
            'source': 'akshare.stock_info_a_code_name',
            'fields': ['code', 'name', 'exchange', 'industry', 'pe_ttm', 'pb']
        },
        'stock_daily': {
            'name': '日线历史数据',
            'required': True,
            'description': '2024年至今的日线K线数据',
            'source': 'akshare.stock_zh_a_hist',
            'fields': ['code', 'trade_date', 'open', 'high', 'low', 'close', 'volume', 'amount', 'change', 'change_pct', 'turnover_rate', 'amplitude']
        },
        'stock_realtime': {
            'name': '实时行情数据',
            'required': False,
            'description': '盘中实时行情（缓存）',
            'source': 'akshare.stock_zh_a_spot_em',
            'fields': ['code', 'timestamp', 'price', 'change', 'volume', 'turnover_rate', 'amplitude', 'pe', 'pb', 'market_cap']
        },
        'market_index': {
            'name': '大盘指数数据',
            'required': False,
            'description': '上证指数、深证成指等主要指数',
            'source': 'akshare.index_zh_a_hist',
            'fields': ['index_code', 'trade_date', 'open', 'high', 'low', 'close', 'change', 'change_pct']
        },
        'sector_data': {
            'name': '板块行业数据',
            'required': False,
            'description': '行业板块涨跌幅和资金流向',
            'source': 'akshare.stock_sector_fund_flow_rank',
            'fields': ['sector_name', 'trade_date', 'change_pct', 'net_inflow']
        },
        'stock_financial_report': {
            'name': '财务报表数据',
            'required': False,
            'description': '资产负债表、利润表、现金流量表',
            'source': 'akshare.stock_balance_sheet_by_report_em',
            'fields': ['code', 'report_date', 'total_assets', 'total_liabilities', 'total_revenue', 'net_profit']
        },
        'stock_financial_indicator': {
            'name': '财务分析指标',
            'required': False,
            'description': '盈利能力、偿债能力等30+指标',
            'source': 'akshare.stock_financial_analysis_indicator',
            'fields': ['code', 'report_date', 'roe', 'eps', 'debt_ratio']
        },
        'data_sync_log': {
            'name': '数据同步日志',
            'required': True,
            'description': '数据下载和同步记录',
            'fields': ['sync_type', 'start_time', 'status', 'records_count']
        }
    }

    # 推荐但未实现的数据类型
    RECOMMENDED_DATA_SOURCES = {
        'stock_news': {
            'name': '个股新闻',
            'source': 'akshare.stock_news_em',
            'description': '个股相关新闻资讯',
            'priority': 'medium',
            'use_case': '舆情分析、事件驱动'
        },
        'stock_lhb': {
            'name': '龙虎榜数据',
            'source': 'akshare.stock_lhb_detail_daily',
            'description': '每日龙虎榜交易明细',
            'priority': 'medium',
            'use_case': '追踪游资动向'
        },
        'stock_fund_flow': {
            'name': '资金流向数据',
            'source': 'akshare.stock_fund_flow',
            'description': '个股主力资金流向',
            'priority': 'high',
            'use_case': '判断主力意图'
        },
        'stock_gdfx': {
            'name': '机构持股数据',
            'source': 'akshare.stock_gdfx_free_top_10_em',
            'description': '机构持股变动',
            'priority': 'medium',
            'use_case': '跟踪机构动向'
        },
        'stock_dzjy': {
            'name': '大宗交易数据',
            'source': 'akshare.stock_dzjy_mrmx',
            'description': '大宗交易明细',
            'priority': 'low',
            'use_case': '机构交易行为'
        },
        'stock_zycw': {
            'name': '主要财务指标',
            'source': 'akshare.stock_main_stock',
            'description': '主营收入、净利润等',
            'priority': 'high',
            'use_case': '基本面快速筛选'
        }
    }

    def __init__(self):
        self.check_results = {}

    def get_table_stats(self, table_name: str) -> Dict[str, Any]:
        """获取单个表的统计信息"""
        try:
            with get_db_session() as session:
                model = globals()[table_name]
                count = session.query(model).count()

                # 获取日期范围（如果表有日期字段）
                date_range = None
                if hasattr(model, 'trade_date'):
                    min_date = session.query(model.trade_date).order_by(model.trade_date.asc()).first()
                    max_date = session.query(model.trade_date).order_by(model.trade_date.desc()).first()
                    if min_date and max_date:
                        date_range = {
                            'min': min_date[0].isoformat() if hasattr(min_date[0], 'isoformat') else str(min_date[0]),
                            'max': max_date[0].isoformat() if hasattr(max_date[0], 'isoformat') else str(max_date[0])
                        }

                return {
                    'table_name': table_name,
                    'record_count': count,
                    'date_range': date_range,
                    'status': 'exists'
                }
        except Exception as e:
            return {
                'table_name': table_name,
                'record_count': 0,
                'status': 'error',
                'error': str(e)
            }

    def check_all_tables(self) -> Dict[str, Any]:
        """检查所有数据表状态"""
        results = {
            'timestamp': datetime.now().isoformat(),
            'tables': {},
            'summary': {
                'total_tables': len(self.DATA_TABLES),
                'existing_tables': 0,
                'empty_tables': 0,
                'error_tables': 0,
                'missing_tables': []
            }
        }

        for table_name, table_info in self.DATA_TABLES.items():
            stats = self.get_table_stats(table_name)
            results['tables'][table_name] = {**table_info, **stats}

            if stats['status'] == 'exists':
                if stats['record_count'] > 0:
                    results['summary']['existing_tables'] += 1
                else:
                    results['summary']['empty_tables'] += 1
            else:
                results['summary']['error_tables'] += 1

            # 检查是否缺少必要数据
            if table_info['required'] and stats['record_count'] == 0:
                results['summary']['missing_tables'].append(table_name)

        return results

    def get_stock_download_status(self, sorted_by: str = 'code') -> List[Dict]:
        """
        获取每只股票的数据下载状态

        Args:
            sorted_by: 'code' 按代码排序, 'name' 按名称排序, 'completeness' 按完整度排序
        """
        try:
            with get_db_session() as session:
                # 获取所有股票
                stocks = session.query(Stock).all()

                stock_status = []
                for stock in stocks:
                    code = stock.code

                    # 统计各表数据量
                    daily_count = session.query(StockDaily).filter_by(code=code).count()
                    realtime_count = session.query(StockRealtime).filter_by(code=code).count()
                    financial_count = session.query(StockFinancialReport).filter_by(code=code).count()
                    indicator_count = session.query(StockFinancialIndicator).filter_by(code=code).count()

                    # 计算完整度百分比
                    expected_daily = 250  # 假设应有约250个交易日数据
                    completeness = min(100, (daily_count / expected_daily) * 100)

                    status = {
                        'code': code,
                        'name': stock.name,
                        'exchange': stock.exchange,
                        'daily_records': daily_count,
                        'realtime_records': realtime_count,
                        'financial_records': financial_count,
                        'indicator_records': indicator_count,
                        'completeness': round(completeness, 2),
                        'status': 'complete' if completeness >= 90 else 'partial' if completeness >= 50 else 'insufficient'
                    }
                    stock_status.append(status)

                # 排序
                if sorted_by == 'code':
                    stock_status.sort(key=lambda x: x['code'])
                elif sorted_by == 'name':
                    stock_status.sort(key=lambda x: x['name'])
                elif sorted_by == 'completeness':
                    stock_status.sort(key=lambda x: x['completeness'], reverse=True)

                return stock_status

        except Exception as e:
            logger.error(f"获取股票下载状态失败: {e}")
            return []

    def check_missing_data(self) -> Dict[str, Any]:
        """检查缺失的数据"""
        results = {
            'missing_tables': [],
            'incomplete_stocks': [],
            'recommended_sources': []
        }

        # 1. 检查缺失的必要表
        table_check = self.check_all_tables()
        for table_name, table_info in table_check['tables'].items():
            if table_info['required'] and table_info['record_count'] == 0:
                results['missing_tables'].append({
                    'table': table_name,
                    'name': table_info['name'],
                    'source': table_info['source'],
                    'description': table_info['description']
                })

        # 2. 检查数据不完整的股票
        stock_status = self.get_stock_download_status()
        for status in stock_status:
            if status['status'] != 'complete':
                results['incomplete_stocks'].append(status)

        # 3. 推荐的数据源
        results['recommended_sources'] = list(self.RECOMMENDED_DATA_SOURCES.values())

        return results

    def generate_inventory_report(self) -> str:
        """生成数据清单报告"""
        check_results = self.check_all_tables()
        stock_status = self.get_stock_download_status(sorted_by='code')

        lines = []
        lines.append("=" * 80)
        lines.append("Fin-R1 数据清单报告")
        lines.append("=" * 80)
        lines.append(f"生成时间: {check_results['timestamp']}")
        lines.append("")

        # 1. 数据表统计
        lines.append("【数据表统计】")
        lines.append(f"总表数: {check_results['summary']['total_tables']}")
        lines.append(f"有数据表: {check_results['summary']['existing_tables']}")
        lines.append(f"空表: {check_results['summary']['empty_tables']}")
        lines.append(f"错误表: {check_results['summary']['error_tables']}")
        lines.append("")

        # 2. 各表详情
        lines.append("【各表详细情况】")
        for table_name, info in check_results['tables'].items():
            status_icon = "✅" if info['record_count'] > 0 else "❌"
            lines.append(f"{status_icon} {info['name']} ({table_name})")
            lines.append(f"   记录数: {info['record_count']:,}")
            if info.get('date_range'):
                lines.append(f"   日期范围: {info['date_range']['min']} ~ {info['date_range']['max']}")
            lines.append(f"   数据源: {info['source']}")
            lines.append("")

        # 3. 股票下载状态（前20只）
        if stock_status:
            lines.append("【股票下载状态（按代码排序前20只）】")
            lines.append(f"{'代码':<10}{'名称':<15}{'日线':<8}{'财务':<8}{'完整度':<10}{'状态'}")
            lines.append("-" * 80)

            for status in stock_status[:20]:
                status_icon = "✅" if status['status'] == 'complete' else "⚠️" if status['status'] == 'partial' else "❌"
                lines.append(
                    f"{status['code']:<10}"
                    f"{status['name']:<15}"
                    f"{status['daily_records']:<8}"
                    f"{status['financial_records']:<8}"
                    f"{status['completeness']:>6}%"
                    f"  {status_icon}"
                )

            # 统计汇总
            complete = sum(1 for s in stock_status if s['status'] == 'complete')
            partial = sum(1 for s in stock_status if s['status'] == 'partial')
            insufficient = sum(1 for s in stock_status if s['status'] == 'insufficient')

            lines.append("")
            lines.append(f"统计: 完整 {complete} 只, 部分 {partial} 只, 不足 {insufficient} 只")
            lines.append("")

        # 4. 推荐数据源
        lines.append("【推荐但未实现的数据源】")
        for source_name, source_info in self.RECOMMENDED_DATA_SOURCES.items():
            priority_icon = "🔴" if source_info['priority'] == 'high' else "🟡" if source_info['priority'] == 'medium' else "🟢"
            lines.append(f"{priority_icon} {source_info['name']}")
            lines.append(f"   接口: {source_info['source']}")
            lines.append(f"   用途: {source_info['use_case']}")
            lines.append(f"   描述: {source_info['description']}")
            lines.append("")

        lines.append("=" * 80)
        return "\n".join(lines)

    def export_stock_list(self, format: str = 'csv', sorted_by: str = 'code') -> str:
        """
        导出股票列表

        Args:
            format: 'csv' 或 'json'
            sorted_by: 排序方式
        """
        stock_status = self.get_stock_download_status(sorted_by=sorted_by)

        if format == 'csv':
            lines = ["代码,名称,交易所,日线记录数,财务记录数,实时记录数,完整度,状态"]
            for status in stock_status:
                lines.append(
                    f"{status['code']},{status['name']},{status['exchange']},"
                    f"{status['daily_records']},{status['financial_records']},"
                    f"{status['realtime_records']},{status['completeness']},{status['status']}"
                )
            return "\n".join(lines)

        elif format == 'json':
            import json
            return json.dumps(stock_status, ensure_ascii=False, indent=2)

        else:
            return "不支持的格式"


async def main():
    """主入口"""
    parser = argparse.ArgumentParser(description='数据清单和完整性检查')
    parser.add_argument('--check', action='store_true', help='检查数据完整性')
    parser.add_argument('--missing', action='store_true', help='显示缺失数据')
    parser.add_argument('--sort', type=str, default='code', choices=['code', 'name', 'completeness'],
                        help='股票排序方式')
    parser.add_argument('--export', type=str, choices=['csv', 'json'], help='导出股票列表')
    parser.add_argument('--limit', type=int, default=50, help='显示股票数量限制')
    parser.add_argument('--init', action='store_true', help='初始化数据库')

    args = parser.parse_args()

    # 初始化数据库
    if args.init:
        print("初始化数据库...")
        init_database()
        print("✅ 数据库表初始化完成")
        return

    # 创建清单管理器
    inventory = DataInventory()

    # 检查数据完整性
    if args.check:
        print(inventory.generate_inventory_report())
        return

    # 显示缺失数据
    if args.missing:
        missing = inventory.check_missing_data()

        print("=" * 80)
        print("缺失数据报告")
        print("=" * 80)

        if missing['missing_tables']:
            print("\n【缺失的必要表】")
            for item in missing['missing_tables']:
                print(f"❌ {item['name']} ({item['table']})")
                print(f"   数据源: {item['source']}")
                print(f"   描述: {item['description']}")

        if missing['incomplete_stocks']:
            print(f"\n【数据不完整的股票】({len(missing['incomplete_stocks'])} 只)")
            for item in missing['incomplete_stocks'][:20]:
                print(f"⚠️  {item['code']} {item['name']}: 完整度 {item['completeness']}%")

        if missing['recommended_sources']:
            print("\n【推荐添加的数据源】")
            for item in missing['recommended_sources']:
                print(f"📌 {item['name']}: {item['description']}")

        return

    # 导出股票列表
    if args.export:
        output = inventory.export_stock_list(format=args.export, sorted_by=args.sort)
        print(output)
        return

    # 默认：显示股票下载状态（排序）
    stock_status = inventory.get_stock_download_status(sorted_by=args.sort)

    print("=" * 80)
    print(f"股票下载状态（按 {args.sort} 排序）")
    print("=" * 80)
    print(f"{'代码':<10}{'名称':<15}{'日线':<8}{'财务':<8}{'完整度':<10}{'状态'}")
    print("-" * 80)

    for status in stock_status[:args.limit]:
        status_icon = "✅" if status['status'] == 'complete' else "⚠️" if status['status'] == 'partial' else "❌"
        print(
            f"{status['code']:<10}"
            f"{status['name']:<15}"
            f"{status['daily_records']:<8}"
            f"{status['financial_records']:<8}"
            f"{status['completeness']:>6}%"
            f"  {status_icon}"
        )

    print("-" * 80)
    print(f"显示 {min(args.limit, len(stock_status))}/{len(stock_status)} 只股票")
    print(f"完整报告请运行: python data_inventory.py --check")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
