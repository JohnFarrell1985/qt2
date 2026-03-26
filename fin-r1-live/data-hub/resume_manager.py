"""
Fin-R1 Data Hub - Resume Download Manager
断点续传管理器

功能:
1. 查看每个股票的下载状态
2. 断点续传：从中断处继续下载
3. 重试失败的任务
4. 导出下载进度报告
5. 清理进度记录

使用:
    python resume_manager.py status           # 查看状态
    python resume_manager.py resume           # 执行断点续传
    python resume_manager.py retry            # 重试失败任务
    python resume_manager.py report           # 导出进度报告
    python resume_manager.py reset --code 000001  # 重置单个股票
    python resume_manager.py reset-all        # 重置所有进度
"""
import os
import sys
import argparse
import json
from datetime import datetime, date
from typing import Dict, List, Any, Optional
from collections import defaultdict

from database import (
    get_db_session, init_database,
    StockDownloadProgressDAO, StockDAO,
    StockDownloadProgress, Stock, StockDaily
)


def print_header(title: str):
    """打印标题"""
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80)


def show_status():
    """显示下载状态"""
    print_header("股票下载进度状态")

    with get_db_session() as session:
        # 获取所有进度记录
        progress_list = session.query(StockDownloadProgress).order_by(
            StockDownloadProgress.code
        ).all()

        if not progress_list:
            print("\n暂无下载进度记录")
            print("请先运行: python history_downloader_with_resume.py --init-only")
            return

        # 按状态分组
        by_status = defaultdict(list)
        for p in progress_list:
            by_status[p.status].append(p)

        # 打印汇总
        print(f"\n总股票数: {len(progress_list)}")
        print(f"  ✅ 已完成 (success): {len(by_status.get('success', []))}")
        print(f"  ⏳ 待下载 (pending): {len(by_status.get('pending', []))}")
        print(f"  🔄 下载中 (running): {len(by_status.get('running', []))}")
        print(f"  ❌ 失败 (failed): {len(by_status.get('failed', []))}")

        # 计算完成率
        completed = len(by_status.get('success', []))
        completion_rate = completed / len(progress_list) * 100 if progress_list else 0
        print(f"\n完成率: {completion_rate:.2f}%")

        # 显示最近更新的20条记录
        print("\n最近更新（前20条，按股票代码排序）:")
        print(f"{'代码':<10}{'类型':<15}{'状态':<12}{'记录数':<10}{'进度':<10}{'重试':<8}{'更新时间'}")
        print("-" * 80)

        for p in progress_list[:20]:
            progress_pct = 0
            if p.expected_count and p.expected_count > 0:
                progress_pct = min(100, p.records_count / p.expected_count * 100)

            status_icon = {
                'success': '✅',
                'pending': '⏳',
                'running': '🔄',
                'failed': '❌'
            }.get(p.status, '?')

            update_time = p.updated_at.strftime("%m-%d %H:%M") if p.updated_at else "-"

            print(
                f"{p.code:<10}"
                f"{p.sync_type:<15}"
                f"{status_icon} {p.status:<8}"
                f"{p.records_count:<10}"
                f"{progress_pct:>6.1f}%"
                f"{p.retry_count:>4}/{p.max_retries}"
                f"  {update_time}"
            )

        # 显示失败的记录
        if by_status.get('failed'):
            print("\n❌ 失败的股票列表（可以重试）:")
            for p in by_status['failed']:
                can_retry = "✅ 可重试" if p.retry_count < p.max_retries else "❌ 已达上限"
                print(f"  {p.code}: 重试 {p.retry_count}/{p.max_retries} {can_retry}")
                if p.error_message:
                    print(f"    错误: {p.error_message[:60]}")


def resume_download():
    """执行断点续传"""
    print_header("执行断点续传")

    import asyncio
    from history_downloader_with_resume import ResumableHistoryDownloader

    async def do_resume():
        downloader = ResumableHistoryDownloader()

        # 检查状态
        status = downloader.get_download_status()
        summary = status['summary']

        if summary['pending'] == 0 and not status['can_resume']:
            print("\n✅ 没有需要续传的任务")
            if summary['failed'] > 0:
                print(f"   有 {summary['failed']} 个失败任务，可以使用 --retry 重试")
            return

        print(f"\n待下载: {summary['pending']} 只")
        print(f"可重试: {len([s for s in status['failed_stocks'] if s['retry_count'] < s['max_retries']])} 只")
        print(f"\n开始断点续传...\n")

        # 获取股票列表
        stocks = await downloader.fetch_stock_list()
        if not stocks:
            print("❌ 获取股票列表失败")
            return

        # 执行断点续传
        total = await downloader.download_all_with_resume(stocks, resume=True)

        print(f"\n✅ 断点续传完成，共下载 {total} 条记录")

    asyncio.run(do_resume())


def retry_failed():
    """重试失败的任务"""
    print_header("重试失败的任务")

    with get_db_session() as session:
        failed_stocks = StockDownloadProgressDAO.get_failed_stocks(session, 'history_full')

        if not failed_stocks:
            print("\n✅ 没有失败的任务需要重试")
            return

        retryable = [p for p in failed_stocks if p.retry_count < p.max_retries]

        print(f"\n失败任务总数: {len(failed_stocks)}")
        print(f"可重试任务数: {len(retryable)}")

        if not retryable:
            print("\n⚠️  所有失败任务都已达到最大重试次数")
            return

        print(f"\n重置 {len(retryable)} 个任务的状态...")
        count = StockDownloadProgressDAO.reset_failed_progress(session, 'history_full')
        print(f"✅ 已重置 {count} 个任务")

        # 询问是否立即重试
        response = input("\n是否立即开始重试? (y/n): ")
        if response.lower() == 'y':
            resume_download()


def export_report(format: str = 'text'):
    """导出进度报告"""
    print_header("导出进度报告")

    with get_db_session() as session:
        progress_list = session.query(StockDownloadProgress).order_by(
            StockDownloadProgress.code
        ).all()

        if format == 'json':
            # JSON格式
            data = [p.to_dict() for p in progress_list]
            filename = f"download_progress_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f"\n✅ 报告已导出到: {filename}")

        elif format == 'csv':
            # CSV格式
            filename = f"download_progress_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
            with open(filename, 'w', encoding='utf-8') as f:
                f.write("代码,类型,状态,记录数,预期数,进度%,重试次数,最大重试,更新时间,错误信息\n")
                for p in progress_list:
                    progress_pct = 0
                    if p.expected_count and p.expected_count > 0:
                        progress_pct = min(100, p.records_count / p.expected_count * 100)

                    update_time = p.updated_at.strftime("%Y-%m-%d %H:%M:%S") if p.updated_at else ""
                    error = (p.error_message or "").replace(',', ';')

                    f.write(f"{p.code},{p.sync_type},{p.status},{p.records_count},{p.expected_count},"
                           f"{progress_pct:.2f},{p.retry_count},{p.max_retries},{update_time},{error}\n")
            print(f"\n✅ 报告已导出到: {filename}")

        else:
            # 文本格式（直接打印）
            show_status()


def reset_progress(code: Optional[str] = None, sync_type: str = 'history_full', all_progress: bool = False):
    """重置下载进度"""
    print_header("重置下载进度")

    with get_db_session() as session:
        if all_progress:
            # 重置所有进度
            confirm = input(f"⚠️  确定要重置所有 '{sync_type}' 的进度记录吗? (yes/no): ")
            if confirm.lower() == 'yes':
                StockDownloadProgressDAO.clear_progress(session, sync_type)
                print(f"\n✅ 已清除所有 '{sync_type}' 的进度记录")
            else:
                print("\n已取消")

        elif code:
            # 重置单个股票
            progress = StockDownloadProgressDAO.get_progress(session, code, sync_type)
            if progress:
                progress.status = 'pending'
                progress.records_count = 0
                progress.retry_count = 0
                progress.error_message = None
                progress.updated_at = datetime.now()
                session.commit()
                print(f"\n✅ 已重置 {code} 的下载进度")
            else:
                print(f"\n⚠️  找不到 {code} 的进度记录")

        else:
            print("\n请指定 --code 股票代码 或 --all 重置所有")


def compare_with_database():
    """对比进度记录和实际数据"""
    print_header("进度记录与实际数据对比")

    with get_db_session() as session:
        # 获取所有进度记录
        progress_list = session.query(StockDownloadProgress).filter(
            StockDownloadProgress.sync_type == 'history_full'
        ).all()

        if not progress_list:
            print("\n暂无进度记录")
            return

        # 获取所有股票
        stocks = session.query(Stock).all()
        stock_codes = {s.code for s in stocks}

        # 对比
        missing_in_db = []  # 有进度记录但没有日线数据的
        inconsistent = []   # 记录数和实际数据不一致的

        for p in progress_list:
            if p.status != 'success':
                continue

            # 检查是否有日线数据
            actual_count = session.query(StockDaily).filter_by(code=p.code).count()

            if actual_count == 0 and p.records_count > 0:
                missing_in_db.append({
                    'code': p.code,
                    'progress_records': p.records_count,
                    'actual_records': actual_count
                })
            elif abs(actual_count - p.records_count) > 10:  # 允许10条的误差
                inconsistent.append({
                    'code': p.code,
                    'progress_records': p.records_count,
                    'actual_records': actual_count,
                    'diff': actual_count - p.records_count
                })

        print(f"\n总进度记录: {len(progress_list)}")
        print(f"缺失日线数据: {len(missing_in_db)} 只")
        print(f"数据不一致: {len(inconsistent)} 只")

        if missing_in_db:
            print("\n❌ 以下股票进度显示成功但实际无数据:")
            for item in missing_in_db[:10]:
                print(f"  {item['code']}: 进度记录 {item['progress_records']} 条，实际 {item['actual_records']} 条")

        if inconsistent:
            print("\n⚠️  以下股票数据量不一致:")
            for item in inconsistent[:10]:
                print(f"  {item['code']}: 进度 {item['progress_records']} 条，实际 {item['actual_records']} 条，差异 {item['diff']:+d} 条")


def main():
    """主入口"""
    parser = argparse.ArgumentParser(description='断点续传管理器')
    subparsers = parser.add_subparsers(dest='command', help='可用命令')

    # status 命令
    status_parser = subparsers.add_parser('status', help='查看下载状态')

    # resume 命令
    resume_parser = subparsers.add_parser('resume', help='执行断点续传')

    # retry 命令
    retry_parser = subparsers.add_parser('retry', help='重试失败的任务')

    # report 命令
    report_parser = subparsers.add_parser('report', help='导出进度报告')
    report_parser.add_argument('--format', choices=['text', 'json', 'csv'], default='text',
                               help='报告格式')

    # reset 命令
    reset_parser = subparsers.add_parser('reset', help='重置下载进度')
    reset_parser.add_argument('--code', type=str, help='重置指定股票代码')
    reset_parser.add_argument('--type', type=str, default='history_full', help='同步类型')
    reset_parser.add_argument('--all', action='store_true', dest='all_progress',
                              help='重置所有进度')

    # verify 命令
    verify_parser = subparsers.add_parser('verify', help='验证进度与实际数据一致性')

    args = parser.parse_args()

    # 初始化数据库
    init_database()

    if args.command == 'status':
        show_status()
    elif args.command == 'resume':
        resume_download()
    elif args.command == 'retry':
        retry_failed()
    elif args.command == 'report':
        export_report(args.format)
    elif args.command == 'reset':
        reset_progress(args.code, args.type, args.all_progress)
    elif args.command == 'verify':
        compare_with_database()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
