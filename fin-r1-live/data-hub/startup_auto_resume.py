"""
Fin-R1 Data Hub - Docker 启动脚本（自动断点续传版）
每次启动自动检测并执行断点续传

特点:
1. 每次启动自动检测缺失数据
2. 自动初始化进度记录（如果是全新下载）
3. 自动执行断点续传（如果有未完成的）
4. 自动重试失败的任务
5. 增量更新最新数据（如果数据已完整）

退出策略:
- 数据下载完成后正常退出（exit 0）
- Docker restart: on-failure 会在失败时自动重启
- 下次启动自动从断点继续

使用:
    python startup_auto_resume.py        # 自动检测并下载
    python startup_auto_resume.py --full # 强制重新下载所有数据
"""
import os
import sys
import time
import asyncio
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional, List

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('/app/logs/startup.log', mode='a')
    ]
)
logger = logging.getLogger(__name__)

from database import (
    init_database, get_db_session, DATABASE_URL,
    Stock, StockDaily, StockDownloadProgress, DataSyncLog,
    StockDAO, StockDownloadProgressDAO
)
from history_downloader_with_resume import ResumableHistoryDownloader, START_DATE
from sqlalchemy import create_engine, text


class AutoResumeStartupManager:
    """自动断点续传启动管理器"""

    def __init__(self):
        self.downloader = ResumableHistoryDownloader(sync_type='history_full')
        self.max_retries = 5
        self.retry_delay = 10

    def ensure_database_exists(self) -> bool:
        """
        自动创建数据库（如果不存在）
        连接到 postgres 系统数据库，检查并创建目标数据库
        """
        try:
            # 解析 DATABASE_URL，连接到 postgres 系统数据库
            # 将 URL 中的数据库名替换为 postgres
            system_url = DATABASE_URL.rsplit('/', 1)[0] + '/postgres'
            db_name = DATABASE_URL.rsplit('/', 1)[1].split('?')[0]

            logger.info(f"🔍 检查数据库 '{db_name}' 是否存在...")

            # 创建到系统数据库的连接引擎
            system_engine = create_engine(system_url, pool_pre_ping=True)

            with system_engine.connect() as conn:
                # 需要在 autocommit 模式下执行 CREATE DATABASE
                conn.execution_options(isolation_level="AUTOCOMMIT")

                # 检查数据库是否存在
                result = conn.execute(
                    text("SELECT 1 FROM pg_database WHERE datname = :db_name"),
                    {"db_name": db_name}
                )
                exists = result.fetchone() is not None

                if not exists:
                    logger.info(f"📝 数据库 '{db_name}' 不存在，正在创建...")
                    # 创建数据库（使用参数化查询防止 SQL 注入，但 CREATE DATABASE 不支持参数）
                    # 这里 db_name 是从配置解析的，视为可信
                    conn.execute(text(f'CREATE DATABASE "{db_name}"'))
                    logger.info(f"✅ 数据库 '{db_name}' 创建成功")
                else:
                    logger.info(f"✅ 数据库 '{db_name}' 已存在")

            system_engine.dispose()
            return True

        except Exception as e:
            logger.error(f"❌ 检查/创建数据库失败: {e}")
            # 如果是权限错误，给出明确的提示
            if "permission denied" in str(e).lower():
                logger.error("   提示: 请确保数据库用户有创建数据库的权限")
                logger.error("   可以手动创建: CREATE DATABASE finr1_data;")
            return False

    def wait_for_database(self, timeout: int = 300) -> bool:
        """等待数据库连接就绪（自动创建数据库）"""
        # 首先确保数据库存在
        if not self.ensure_database_exists():
            logger.error("❌ 无法确保数据库存在")
            return False

        logger.info("⏳ 等待数据库连接...")
        start_time = time.time()
        attempt = 0

        while time.time() - start_time < timeout:
            attempt += 1
            try:
                with get_db_session() as session:
                    from sqlalchemy import text
                    session.execute(text("SELECT 1"))
                    logger.info(f"✅ 数据库连接成功（尝试 {attempt} 次）")
                    return True
            except Exception as e:
                logger.warning(f"数据库连接失败（尝试 {attempt}/{self.max_retries}）: {e}")
                if attempt >= self.max_retries:
                    logger.error("❌ 数据库连接失败，已达到最大重试次数")
                    return False
                time.sleep(self.retry_delay)

        logger.error(f"❌ 数据库连接超时（{timeout}秒）")
        return False

    def initialize_tables(self) -> bool:
        """初始化数据库表结构"""
        logger.info("🔧 初始化数据库表结构...")
        try:
            init_database()
            logger.info("✅ 数据库表初始化完成")
            return True
        except Exception as e:
            logger.error(f"❌ 数据库表初始化失败: {e}")
            return False

    def check_data_status(self) -> Dict[str, Any]:
        """检查当前数据状态"""
        logger.info("🔍 检查当前数据状态...")

        try:
            with get_db_session() as session:
                # 检查股票列表
                stock_count = session.query(Stock).count()

                # 检查日线数据
                daily_count = session.query(StockDaily).count()

                # 获取日期范围
                from sqlalchemy import func
                min_date = session.query(func.min(StockDaily.trade_date)).scalar()
                max_date = session.query(func.max(StockDaily.trade_date)).scalar()

                # 检查下载进度记录
                progress_count = session.query(StockDownloadProgress).count()

                today = date.today()

                # 判断数据状态
                has_data = stock_count > 0 and daily_count > 0
                is_complete = False
                needs_update = False
                missing_days = 0

                if has_data and max_date:
                    if max_date >= today:
                        is_complete = True
                    else:
                        needs_update = True
                        missing_days = (today - max_date).days

                # 检查是否有未完成的下载任务
                incomplete_count = session.query(StockDownloadProgress).filter(
                    StockDownloadProgress.status.in_(['pending', 'running'])
                ).count()

                failed_count = session.query(StockDownloadProgress).filter(
                    StockDownloadProgress.status == 'failed',
                    StockDownloadProgress.retry_count < StockDownloadProgress.max_retries
                ).count()

                status = {
                    'stock_count': stock_count,
                    'daily_count': daily_count,
                    'date_range': {
                        'min': str(min_date) if min_date else None,
                        'max': str(max_date) if max_date else None
                    },
                    'has_progress_records': progress_count > 0,
                    'incomplete_tasks': incomplete_count,
                    'failed_tasks': failed_count,
                    'is_complete': is_complete,
                    'needs_update': needs_update,
                    'missing_days': missing_days
                }

                logger.info(f"  股票数: {stock_count}")
                logger.info(f"  日线记录: {daily_count}")
                logger.info(f"  日期范围: {status['date_range']['min']} ~ {status['date_range']['max']}")
                logger.info(f"  进度记录: {progress_count}")
                logger.info(f"  未完成任务: {incomplete_count}")
                logger.info(f"  可重试失败: {failed_count}")

                return status

        except Exception as e:
            logger.error(f"❌ 检查数据状态失败: {e}")
            return {
                'stock_count': 0,
                'daily_count': 0,
                'has_progress_records': False,
                'error': str(e)
            }

    async def download_with_resume(self, force_full: bool = False) -> bool:
        """
        执行带断点续传的下载

        Args:
            force_full: 是否强制重新下载所有数据

        Returns:
            是否成功
        """
        try:
            # 1. 获取股票列表
            stocks = await self.downloader.fetch_stock_list()
            if not stocks:
                logger.error("❌ 获取股票列表失败")
                return False

            logger.info(f"✅ 获取到 {len(stocks)} 只股票")

            # 2. 初始化进度记录（如果是全新下载或强制全量）
            if force_full:
                logger.info("🔄 强制全量下载模式，重置所有进度记录...")
                with get_db_session() as session:
                    StockDownloadProgressDAO.clear_progress(session, 'history_full')
                self.downloader.init_download_progress(stocks, START_DATE, date.today())

            # 3. 检查是否需要初始化进度记录
            with get_db_session() as session:
                progress_count = session.query(StockDownloadProgress).count()

            if progress_count == 0:
                logger.info("📝 初始化下载进度记录...")
                self.downloader.init_download_progress(stocks, START_DATE, date.today())

            # 4. 执行断点续传下载
            logger.info("📥 开始下载（支持断点续传）...")
            total = await self.downloader.download_all_with_resume(
                stocks,
                start_date=START_DATE,
                resume=True  # 始终使用断点续传模式
            )

            logger.info(f"✅ 下载完成: {total} 条记录")
            return True

        except Exception as e:
            logger.error(f"❌ 下载失败: {e}")
            return False

    async def incremental_update(self) -> bool:
        """执行增量更新（只下载最新数据）"""
        logger.info("📈 执行增量更新...")

        try:
            with get_db_session() as session:
                stocks = session.query(Stock).all()
                today = date.today()
                updated = 0

                for stock in stocks:
                    code = stock.code

                    # 获取该股票最新日期
                    from sqlalchemy import func
                    max_date = session.query(func.max(StockDaily.trade_date)).filter(
                        StockDaily.code == code
                    ).scalar()

                    if max_date and max_date >= today:
                        continue

                    start_date = max_date + timedelta(days=1) if max_date else START_DATE
                    if start_date > today:
                        continue

                    # 下载并保存
                    data, error = await self.downloader.fetch_stock_history(code, start_date, today)

                    if data:
                        StockDailyDAO.bulk_insert_daily_data(session, data)
                        updated += len(data)

                logger.info(f"✅ 增量更新完成: 新增 {updated} 条记录")
                return True

        except Exception as e:
            logger.error(f"❌ 增量更新失败: {e}")
            return False

    def check_final_data_quality(self) -> Dict[str, Any]:
        """检查最终数据质量"""
        logger.info("🔍 检查最终数据质量...")

        try:
            with get_db_session() as session:
                from sqlalchemy import func

                stock_count = session.query(Stock).count()
                daily_count = session.query(StockDaily).count()
                min_date = session.query(func.min(StockDaily.trade_date)).scalar()
                max_date = session.query(func.max(StockDaily.trade_date)).scalar()

                # 计算完成率
                progress_summary = StockDownloadProgressDAO.get_download_summary(
                    session, 'history_full'
                )
                completion_rate = progress_summary.get('completion_rate', 0)

                status = {
                    'stock_count': stock_count,
                    'daily_count': daily_count,
                    'date_range': {
                        'min': str(min_date) if min_date else None,
                        'max': str(max_date) if max_date else None
                    },
                    'completion_rate': completion_rate,
                    'progress_summary': progress_summary
                }

                # 判断数据质量
                if completion_rate >= 95 and stock_count >= 5000:
                    status['quality'] = 'excellent'
                elif completion_rate >= 80 and stock_count >= 4000:
                    status['quality'] = 'good'
                elif stock_count > 0 and daily_count > 0:
                    status['quality'] = 'partial'
                else:
                    status['quality'] = 'insufficient'

                return status

        except Exception as e:
            logger.error(f"❌ 检查数据质量失败: {e}")
            return {'quality': 'error', 'error': str(e)}

    async def run(self, force_full: bool = False) -> int:
        """
        执行自动断点续传启动流程

        Args:
            force_full: 是否强制重新下载所有数据

        Returns:
            退出码 (0=成功, 1=失败)
        """
        logger.info("=" * 80)
        logger.info(" Fin-R1 Data Hub 自动断点续传启动流程")
        logger.info("=" * 80)
        logger.info(f"启动时间: {datetime.now().isoformat()}")
        logger.info(f"启动模式: {'强制全量' if force_full else '自动检测/断点续传'}")
        logger.info("=" * 80)

        # 步骤 1: 等待数据库连接
        if not self.wait_for_database():
            logger.error("❌ 启动失败: 无法连接数据库")
            return 1

        # 步骤 2: 初始化表结构
        if not self.initialize_tables():
            logger.error("❌ 启动失败: 数据库表初始化失败")
            return 1

        # 步骤 3: 检查当前数据状态
        status = self.check_data_status()

        # 步骤 4: 根据状态决定下载策略
        success = False

        if force_full:
            # 强制全量下载
            logger.info("🔄 执行强制全量下载...")
            success = await self.download_with_resume(force_full=True)

        elif status.get('incomplete_tasks', 0) > 0 or status.get('failed_tasks', 0) > 0:
            # 有未完成的下载任务，执行断点续传
            logger.info(f"📥 发现 {status['incomplete_tasks']} 个未完成任务，执行断点续传...")
            success = await self.download_with_resume(force_full=False)

        elif status.get('needs_update', False):
            # 数据需要增量更新
            logger.info(f"📈 数据需要更新（缺失 {status['missing_days']} 天），执行增量更新...")
            success = await self.incremental_update()

        elif status.get('is_complete', False):
            # 数据已是最新
            logger.info("✅ 数据已是最新，无需下载")
            success = True

        else:
            # 全新下载
            logger.info("🆕 首次下载，初始化所有数据...")
            success = await self.download_with_resume(force_full=False)

        if not success:
            logger.error("❌ 数据下载失败")
            return 1

        # 步骤 5: 检查最终数据质量
        final_status = self.check_final_data_quality()
        logger.info("=" * 80)
        logger.info(" 最终数据质量报告")
        logger.info("=" * 80)
        logger.info(f"  股票数量: {final_status['stock_count']}")
        logger.info(f"  日线记录: {final_status['daily_count']:,}")
        logger.info(f"  日期范围: {final_status['date_range']['min']} ~ {final_status['date_range']['max']}")
        logger.info(f"  完成率: {final_status['completion_rate']:.1f}%")
        logger.info(f"  数据质量: {final_status['quality']}")

        # 步骤 6: 打印下载进度汇总
        if final_status.get('progress_summary'):
            summary = final_status['progress_summary']
            logger.info("=" * 80)
            logger.info(" 下载进度汇总")
            logger.info("=" * 80)
            logger.info(f"  总计: {summary['total']} 只")
            logger.info(f"  成功: {summary['success']} 只")
            logger.info(f"  失败: {summary['failed']} 只")
            logger.info(f"  待下载: {summary['pending']} 只")

        # 根据数据质量返回退出码
        if final_status['quality'] in ['excellent', 'good']:
            logger.info("=" * 80)
            logger.info(" ✅ 启动完成: 数据质量良好，容器正常退出")
            logger.info(" 📌 下次启动会自动检查并下载最新数据")
            logger.info("=" * 80)
            return 0
        elif final_status['quality'] == 'partial':
            logger.warning("=" * 80)
            logger.info(" ⚠️ 启动完成: 数据部分可用")
            logger.info(" 📌 部分股票可能下载失败，下次启动会尝试重试")
            logger.info("=" * 80)
            return 0
        else:
            logger.error("=" * 80)
            logger.error(" ❌ 启动失败: 数据质量不足")
            logger.error(" 🔄 Docker 会根据 restart: on-failure 策略自动重启")
            logger.error(" 📌 下次启动会从断点继续下载")
            logger.info("=" * 80)
            return 1


async def main():
    """主入口"""
    parser = argparse.ArgumentParser(description='Fin-R1 Data Hub 自动断点续传启动脚本')
    parser.add_argument('--full', action='store_true',
                        help='强制全量下载（重置所有进度并重新下载）')
    parser.add_argument('--status', action='store_true',
                        help='仅检查状态，不下载')
    parser.add_argument('--wait-db', type=int, default=300,
                        help='等待数据库连接的最大时间（秒）')

    args = parser.parse_args()

    # 仅检查状态
    if args.status:
        manager = AutoResumeStartupManager()
        if manager.wait_for_database() and manager.initialize_tables():
            status = manager.check_data_status()
            print("\n当前数据状态:")
            for key, value in status.items():
                print(f"  {key}: {value}")
        return 0

    # 执行自动断点续传启动流程
    startup = AutoResumeStartupManager()
    startup.max_retries = args.wait_db // 10

    exit_code = await startup.run(force_full=args.full)

    return exit_code


if __name__ == "__main__":
    try:
        exit_code = asyncio.run(main())
        sys.exit(exit_code)
    except KeyboardInterrupt:
        logger.info("🛑 用户中断启动")
        sys.exit(130)
    except Exception as e:
        logger.error(f"💥 启动异常: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
