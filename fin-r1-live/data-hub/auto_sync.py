"""
Fin-R1 Data Hub - Auto Sync Module
自动数据同步模块

功能:
1. 启动时检查数据库中是否有从2024-01-01开始的数据
2. 如果没有完整数据，自动下载全部历史数据
3. 如果有部分数据，自动补全从上次日期到今天的数据
4. 支持定时增量更新（可用于cron任务）

启动流程:
1. 检查数据库连接
2. 检查 stock_daily 表中最小和最大日期
3. 如果最小日期 > 2024-01-01 或表为空 -> 全量下载
4. 如果最大日期 < 今天 -> 增量下载缺失部分
"""
import asyncio
import os
import sys
import time
import logging
from datetime import date, datetime, timedelta
from typing import Optional, Dict, Any

from database import (
    init_database, get_db_session,
    StockDAO, StockDailyDAO, DataSyncLog,
    Stock, StockDaily
)
from history_downloader import HistoryDownloader

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 配置
START_DATE = date(2024, 1, 1)  # 历史数据起始日期
FULL_DOWNLOAD_THRESHOLD_DAYS = 30  # 如果缺失超过30天，视为需要全量下载


class AutoSyncManager:
    """自动同步管理器"""

    def __init__(self):
        self.downloader = HistoryDownloader()

    def check_database_status(self) -> Dict[str, Any]:
        """
        检查数据库状态
        返回: {
            "has_data": bool,           # 是否有数据
            "min_date": date|None,      # 最早日期
            "max_date": date|None,      # 最晚日期
            "total_stocks": int,        # 股票数量
            "total_records": int,       # 日线记录数
            "need_full_download": bool, # 是否需要全量下载
            "need_incremental": bool,   # 是否需要增量
            "missing_days": int         # 缺失天数
        }
        """
        try:
            with get_db_session() as session:
                # 检查股票列表
                stock_count = session.query(Stock).count()

                # 检查日线数据
                daily_count = session.query(StockDaily).count()

                # 获取日期范围
                min_date_row = session.query(StockDaily.trade_date).order_by(
                    StockDaily.trade_date.asc()
                ).first()

                max_date_row = session.query(StockDaily.trade_date).order_by(
                    StockDaily.trade_date.desc()
                ).first()

                min_date = min_date_row[0] if min_date_row else None
                max_date = max_date_row[0] if max_date_row else None

                today = date.today()

                # 判断是否需要全量下载
                need_full = False
                missing_days = 0

                if not min_date or not max_date:
                    # 完全没有数据
                    need_full = True
                    missing_days = (today - START_DATE).days
                elif min_date > START_DATE:
                    # 起始日期晚于2024-01-01，需要全量下载
                    need_full = True
                    missing_days = (min_date - START_DATE).days
                    logger.info(f"数据库起始日期 {min_date} 晚于 {START_DATE}，需要全量下载")

                # 判断是否需要增量
                need_incremental = False
                if max_date and max_date < today:
                    # 数据不是最新的
                    if not need_full:  # 只有在不需要全量时才做增量
                        need_incremental = True
                        missing_days = (today - max_date).days

                # 如果缺失天数超过阈值，也视为需要全量
                if missing_days > FULL_DOWNLOAD_THRESHOLD_DAYS and not need_full:
                    logger.info(f"缺失 {missing_days} 天数据，超过阈值，执行全量下载")
                    need_full = True
                    need_incremental = False

                return {
                    "has_data": daily_count > 0,
                    "min_date": min_date,
                    "max_date": max_date,
                    "total_stocks": stock_count,
                    "total_records": daily_count,
                    "need_full_download": need_full,
                    "need_incremental": need_incremental,
                    "missing_days": missing_days,
                    "today": today
                }

        except Exception as e:
            logger.error(f"检查数据库状态失败: {e}")
            return {
                "has_data": False,
                "min_date": None,
                "max_date": None,
                "total_stocks": 0,
                "total_records": 0,
                "need_full_download": True,
                "need_incremental": False,
                "missing_days": (date.today() - START_DATE).days,
                "today": date.today()
            }

    async def run_full_download(self) -> int:
        """执行全量下载"""
        logger.info("=" * 60)
        logger.info("开始全量历史数据下载")
        logger.info(f"起始日期: {START_DATE}")
        logger.info("=" * 60)

        # 1. 获取股票列表
        stocks = await self.downloader.fetch_stock_list()
        if not stocks:
            logger.error("获取股票列表失败")
            return 0

        # 保存股票基础信息
        with get_db_session() as session:
            StockDAO.bulk_upsert_stocks(session, stocks)
            logger.info(f"已保存 {len(stocks)} 只股票基础信息")

        # 2. 下载历史数据
        codes = [s['code'] for s in stocks]
        total = await self.downloader.download_all_history(codes, START_DATE)

        logger.info("=" * 60)
        logger.info(f"全量下载完成！共 {total} 条日线记录")
        logger.info("=" * 60)

        return total

    async def run_incremental_sync(self, status: Dict) -> Dict[str, int]:
        """执行增量同步"""
        max_date = status.get("max_date")
        today = status.get("today", date.today())

        if not max_date:
            logger.error("无法获取最大日期，跳过增量同步")
            return {"updated": 0, "added": 0, "failed": 0}

        # 从下一天开始
        start_date = max_date + timedelta(days=1)

        if start_date > today:
            logger.info(f"数据已是最新 (最新: {max_date}, 今天: {today})")
            return {"updated": 0, "added": 0, "failed": 0}

        logger.info("=" * 60)
        logger.info(f"开始增量同步: {start_date} 到 {today}")
        logger.info("=" * 60)

        # 获取所有股票代码
        with get_db_session() as session:
            all_codes = StockDAO.get_all_stock_codes(session)

        if not all_codes:
            logger.warning("数据库中没有股票列表")
            return {"updated": 0, "added": 0, "failed": 0}

        result = {'updated': 0, 'added': 0, 'failed': 0}

        # 使用信号量控制并发数，避免过多请求
        semaphore = asyncio.Semaphore(5)

        async def download_one(code):
            async with semaphore:
                try:
                    data = await self.downloader.fetch_stock_history(code, start_date, today)
                    if data:
                        with get_db_session() as session:
                            StockDailyDAO.bulk_insert_daily_data(session, data)
                            return len(data), 1  # (added_count, updated_count)
                    return 0, 0
                except Exception as e:
                    logger.error(f"增量更新 {code} 失败: {e}")
                    return 0, -1  # -1表示失败

        # 并发执行下载任务
        tasks = [download_one(code) for code in all_codes]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 统计结果
        for r in results:
            if isinstance(r, Exception):
                result['failed'] += 1
                continue
            added, status = r
            if status == 1:
                result['added'] += added
                result['updated'] += 1
            elif status == -1:
                result['failed'] += 1

        logger.info("=" * 60)
        logger.info(f"增量同步完成: {result}")
        logger.info("=" * 60)

        return result

    async def run(self):
        """
        主运行函数
        自动判断并执行全量或增量下载
        """
        logger.info("🚀 Fin-R1 Data Hub 自动同步启动")

        # 1. 初始化数据库（创建表）
        try:
            init_database()
            logger.info("✅ 数据库表结构检查完成")
        except Exception as e:
            logger.error(f"数据库初始化失败: {e}")
            return False

        # 2. 检查当前数据状态
        logger.info("🔍 检查数据库数据状态...")
        status = self.check_database_status()

        logger.info(f"数据库状态:")
        logger.info(f"  - 股票数: {status['total_stocks']}")
        logger.info(f"  - 记录数: {status['total_records']}")
        logger.info(f"  - 最早日期: {status['min_date']}")
        logger.info(f"  - 最晚日期: {status['max_date']}")
        logger.info(f"  - 需要全量下载: {status['need_full_download']}")
        logger.info(f"  - 需要增量同步: {status['need_incremental']}")
        logger.info(f"  - 缺失天数: {status['missing_days']}")

        # 3. 根据状态执行相应操作
        if status['need_full_download']:
            logger.info("📥 执行全量历史数据下载...")
            total = await self.run_full_download()
            logger.info(f"✅ 全量下载完成: {total} 条记录")

        elif status['need_incremental']:
            logger.info("📥 执行增量数据同步...")
            result = await self.run_incremental_sync(status)
            logger.info(f"✅ 增量同步完成: 更新 {result['updated']} 只股票, 新增 {result['added']} 条记录")

        else:
            logger.info("✅ 数据已是最新，无需下载")

        return True

    async def run_loop(self, interval_hours: int = 24):
        """
        持续运行模式（用于后台服务）
        每隔指定小时数检查并同步一次
        """
        logger.info(f"🔄 进入持续同步模式，间隔: {interval_hours}小时")

        while True:
            try:
                await self.run()
                logger.info(f"⏳ 等待 {interval_hours} 小时后再次检查...")
                await asyncio.sleep(interval_hours * 3600)
            except Exception as e:
                logger.error(f"同步循环异常: {e}")
                logger.info("⏳ 1小时后重试...")
                await asyncio.sleep(3600)


def main():
    """主入口"""
    import argparse

    parser = argparse.ArgumentParser(description='Fin-R1 Data Hub Auto Sync')
    parser.add_argument('--loop', action='store_true', help='持续运行模式（每24小时同步一次）')
    parser.add_argument('--interval', type=int, default=24, help='同步间隔（小时，默认24）')
    parser.add_argument('--status', action='store_true', help='仅检查状态，不下载')

    args = parser.parse_args()

    manager = AutoSyncManager()

    if args.status:
        # 仅检查状态
        status = manager.check_database_status()
        print("\n数据库状态:")
        for key, value in status.items():
            print(f"  {key}: {value}")
        return

    if args.loop:
        # 持续运行模式
        asyncio.run(manager.run_loop(args.interval))
    else:
        # 单次运行模式
        success = asyncio.run(manager.run())
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
