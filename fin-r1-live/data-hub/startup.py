"""
Fin-R1 Data Hub - Docker 启动脚本
健壮的启动流程，处理数据库连接、建表、数据下载全流程

特点:
1. 等待数据库连接就绪
2. 自动创建所有表结构
3. 检查并下载缺失的历史数据
4. 支持基本面数据同步（可选）
5. 详细的日志输出和错误处理
6. 退出码反映执行状态

使用:
    python startup.py              # 标准启动
    python startup.py --full       # 强制全量下载
    python startup.py --status     # 仅检查状态
    python startup.py --fundamental # 包含基本面数据
"""
import os
import sys
import time
import asyncio
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import Dict, Any, Optional

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

# 导入数据同步模块
from database import init_database, get_db_session, Stock, StockDaily, DataSyncLog
from auto_sync import AutoSyncManager, START_DATE

# 可选导入（基本面数据）
try:
    from fundamental_sync import FundamentalDataSync
    FUNDAMENTAL_AVAILABLE = True
except ImportError:
    FUNDAMENTAL_AVAILABLE = False
    logger.warning("基本面数据模块不可用")


class StartupManager:
    """启动管理器 - 协调整个启动流程"""

    def __init__(self):
        self.sync_manager = AutoSyncManager()
        self.max_retries = 5
        self.retry_delay = 10  # 秒

    def wait_for_database(self, timeout: int = 300) -> bool:
        """
        等待数据库连接就绪

        Args:
            timeout: 最大等待时间（秒）

        Returns:
            是否成功连接
        """
        logger.info("⏳ 等待数据库连接...")
        start_time = time.time()
        attempt = 0

        while time.time() - start_time < timeout:
            attempt += 1
            try:
                with get_db_session() as session:
                    # 简单查询测试连接
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

            # 验证表是否创建成功
            with get_db_session() as session:
                from sqlalchemy import inspect
                inspector = inspect(session.bind)
                tables = inspector.get_table_names()
                expected_tables = [
                    'stocks', 'stock_daily', 'stock_realtime',
                    'market_index', 'sector_data', 'data_sync_log',
                    'stock_financial_report', 'stock_financial_indicator'
                ]

                missing_tables = [t for t in expected_tables if t not in tables]
                if missing_tables:
                    logger.warning(f"⚠️  缺少表: {missing_tables}")
                    return False

                logger.info(f"✅ 已创建 {len(tables)} 个表: {tables}")
                return True

        except Exception as e:
            logger.error(f"❌ 数据库表初始化失败: {e}")
            return False

    async def sync_historical_data(self, force_full: bool = False) -> bool:
        """
        同步历史数据

        Args:
            force_full: 是否强制全量下载

        Returns:
            是否成功
        """
        logger.info("📊 开始历史数据同步...")

        try:
            if force_full:
                logger.info("🔄 强制全量下载模式")
                total = await self.sync_manager.run_full_download()
                logger.info(f"✅ 全量下载完成: {total} 条记录")
                return total > 0
            else:
                # 使用自动检测逻辑
                success = await self.sync_manager.run()
                return success

        except Exception as e:
            logger.error(f"❌ 历史数据同步失败: {e}")
            return False

    async def sync_fundamental_data(self, batch_size: int = 100) -> bool:
        """
        同步基本面数据（可选）

        Args:
            batch_size: 每批处理股票数量

        Returns:
            是否成功
        """
        if not FUNDAMENTAL_AVAILABLE:
            logger.info("⏭️  基本面数据模块不可用，跳过")
            return True

        logger.info("📈 开始基本面数据同步...")

        try:
            sync = FundamentalDataSync()

            # 获取热门股票列表
            with get_db_session() as session:
                # 优先同步市值前100的股票
                from sqlalchemy import text
                result = session.execute(
                    text("""
                    SELECT code FROM stocks
                    WHERE market_cap IS NOT NULL
                    ORDER BY market_cap DESC
                    LIMIT 100
                    """)
                )
                hot_codes = [row[0] for row in result]

            if not hot_codes:
                logger.warning("⚠️  没有找到热门股票列表")
                return True

            logger.info(f"🎯 同步 {len(hot_codes)} 只热门股票的基本面数据")
            result = await sync.sync_hot_stocks(hot_codes)

            logger.info(
                f"✅ 基本面数据同步完成: "
                f"成功 {result['success']}, "
                f"失败 {result['failed']}, "
                f"财务报告 {result['financial_reports']}, "
                f"指标 {result['indicators']}"
            )
            return result['failed'] == 0

        except Exception as e:
            logger.error(f"❌ 基本面数据同步失败: {e}")
            # 基本面数据是可选的，失败不影响整体流程
            return True

    def check_final_status(self) -> Dict[str, Any]:
        """检查最终数据状态"""
        logger.info("🔍 检查最终数据状态...")

        try:
            with get_db_session() as session:
                # 统计各表记录数
                from sqlalchemy import func
                stock_count = session.query(Stock).count()
                daily_count = session.query(StockDaily).count()

                # 获取日期范围
                min_date = session.query(func.min(StockDaily.trade_date)).scalar()
                max_date = session.query(func.max(StockDaily.trade_date)).scalar()

                status = {
                    'stocks_count': stock_count,
                    'daily_records': daily_count,
                    'date_range': {
                        'min': str(min_date) if min_date else None,
                        'max': str(max_date) if max_date else None
                    },
                    'coverage_days': (max_date - min_date).days if min_date and max_date else 0
                }

                # 判断数据质量
                if stock_count >= 5000 and daily_count >= 1000000:
                    status['quality'] = 'excellent'
                elif stock_count >= 4000 and daily_count >= 500000:
                    status['quality'] = 'good'
                elif stock_count > 0 and daily_count > 0:
                    status['quality'] = 'partial'
                else:
                    status['quality'] = 'insufficient'

                return status

        except Exception as e:
            logger.error(f"❌ 检查最终状态失败: {e}")
            return {'quality': 'error', 'error': str(e)}

    async def run(self, force_full: bool = False, sync_fundamental: bool = False) -> int:
        """
        执行完整启动流程

        Args:
            force_full: 是否强制全量下载
            sync_fundamental: 是否同步基本面数据

        Returns:
            退出码 (0=成功, 1=失败)
        """
        logger.info("=" * 80)
        logger.info(" Fin-R1 Data Hub 启动流程")
        logger.info("=" * 80)
        logger.info(f"启动时间: {datetime.now().isoformat()}")
        logger.info(f"启动模式: {'全量下载' if force_full else '自动检测'}")
        logger.info(f"数据库: {os.getenv('DATABASE_URL', '默认配置')}")
        logger.info("=" * 80)

        # 步骤 1: 等待数据库连接
        if not self.wait_for_database():
            logger.error("❌ 启动失败: 无法连接数据库")
            return 1

        # 步骤 2: 初始化表结构
        if not self.initialize_tables():
            logger.error("❌ 启动失败: 数据库表初始化失败")
            return 1

        # 步骤 3: 同步历史数据
        if not await self.sync_historical_data(force_full=force_full):
            logger.error("❌ 启动失败: 历史数据同步失败")
            return 1

        # 步骤 4: 同步基本面数据（可选）
        if sync_fundamental:
            await self.sync_fundamental_data()

        # 步骤 5: 检查最终状态
        final_status = self.check_final_status()
        logger.info("=" * 80)
        logger.info(" 最终数据状态")
        logger.info("=" * 80)
        for key, value in final_status.items():
            logger.info(f"  {key}: {value}")

        # 根据数据质量返回退出码
        if final_status.get('quality') in ['excellent', 'good']:
            logger.info("✅ 启动完成: 数据质量良好")
            return 0
        elif final_status.get('quality') == 'partial':
            logger.warning("⚠️  启动完成: 数据部分可用")
            return 0  # 部分数据也算成功启动
        else:
            logger.error("❌ 启动失败: 数据质量不足")
            return 1


async def main():
    """主入口"""
    parser = argparse.ArgumentParser(description='Fin-R1 Data Hub 启动脚本')
    parser.add_argument('--full', action='store_true',
                        help='强制全量下载（忽略已有数据）')
    parser.add_argument('--fundamental', action='store_true',
                        help='同步基本面数据')
    parser.add_argument('--status', action='store_true',
                        help='仅检查状态，不下载')
    parser.add_argument('--wait-db', type=int, default=300,
                        help='等待数据库连接的最大时间（秒）')

    args = parser.parse_args()

    # 仅检查状态
    if args.status:
        manager = AutoSyncManager()
        status = manager.check_database_status()
        print("\n数据库状态:")
        for key, value in status.items():
            print(f"  {key}: {value}")
        return 0

    # 执行完整启动流程
    startup = StartupManager()
    startup.max_retries = args.wait_db // 10

    exit_code = await startup.run(
        force_full=args.full,
        sync_fundamental=args.fundamental
    )

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
        sys.exit(1)
