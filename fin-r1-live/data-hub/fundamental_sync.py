"""
Fin-R1 Data Hub - Fundamental Data Sync Module
公司基本面数据同步模块

功能:
1. 定期同步财务报表数据
2. 定期同步财务分析指标
3. 支持全量和增量更新
4. 数据质量检查

使用:
    python fundamental_sync.py              # 同步所有股票的最新财报
    python fundamental_sync.py --code 000001  # 同步单只股票
    python fundamental_sync.py --batch 100  # 分批同步，每批100只
"""
import asyncio
import argparse
import logging
from datetime import datetime, date
from typing import List, Optional

from database import get_db_session, init_database, Stock, DataSyncLog
from fundamental_fetcher import fundamental_fetcher

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class FundamentalDataSync:
    """基本面数据同步管理器"""

    def __init__(self, batch_size: int = 50):
        self.batch_size = batch_size
        self.success_count = 0
        self.fail_count = 0
        self.total_reports = 0
        self.total_indicators = 0

    async def sync_single_stock(self, code: str) -> bool:
        """
        同步单只股票的基本面数据

        Returns:
            是否成功
        """
        try:
            logger.info(f"📊 开始同步 {code} 基本面数据...")

            result = await fundamental_fetcher.download_fundamental_data(code)

            if result['financial_reports'] > 0 or result['indicators'] > 0:
                logger.info(
                    f"✅ {code} 同步完成: "
                    f"财报 {result['financial_reports']} 条, "
                    f"指标 {result['indicators']} 条"
                )
                self.success_count += 1
                self.total_reports += result['financial_reports']
                self.total_indicators += result['indicators']
                return True
            else:
                logger.warning(f"⚠️  {code} 无基本面数据")
                return False

        except Exception as e:
            logger.error(f"❌ {code} 同步失败: {e}")
            self.fail_count += 1
            return False

    async def sync_all_stocks(self, max_stocks: Optional[int] = None):
        """
        同步所有股票的基本面数据

        Args:
            max_stocks: 最大同步股票数，None表示全部
        """
        logger.info("=" * 60)
        logger.info("开始全量基本面数据同步")
        logger.info("=" * 60)

        # 获取所有股票代码
        with get_db_session() as session:
            stocks = session.query(Stock.code).all()
            stock_codes = [s[0] for s in stocks]

        if max_stocks:
            stock_codes = stock_codes[:max_stocks]

        total = len(stock_codes)
        logger.info(f"总共需要同步 {total} 只股票")

        # 分批处理
        for i in range(0, total, self.batch_size):
            batch = stock_codes[i:i + self.batch_size]
            logger.info(f"\n📦 处理批次 {i//self.batch_size + 1}/{(total-1)//self.batch_size + 1} ({len(batch)} 只)")

            # 并发处理批次内的股票
            tasks = [self.sync_single_stock(code) for code in batch]
            await asyncio.gather(*tasks, return_exceptions=True)

            # 批次间隔，避免请求过快
            if i + self.batch_size < total:
                logger.info("⏳ 等待 5 秒后继续...")
                await asyncio.sleep(5)

        # 生成报告
        logger.info("\n" + "=" * 60)
        logger.info("同步完成!")
        logger.info(f"成功: {self.success_count} 只")
        logger.info(f"失败: {self.fail_count} 只")
        logger.info(f"财报数据: {self.total_reports} 条")
        logger.info(f"指标数据: {self.total_indicators} 条")
        logger.info("=" * 60)

    async def sync_latest_reports(self, codes: Optional[List[str]] = None):
        """
        同步最新一期的财务报表（增量更新）

        适用于定期更新，只获取最新报告期的数据
        """
        if codes is None:
            # 获取所有股票
            with get_db_session() as session:
                codes = [s[0] for s in session.query(Stock.code).all()]

        logger.info(f"同步 {len(codes)} 只股票的最新财报...")

        for code in codes:
            await self.sync_single_stock(code)
            await asyncio.sleep(1)  # 避免请求过快

    async def sync_hot_stocks(self):
        """
        同步热门股票的基本面数据

        优先同步大盘蓝筹股、热门概念股
        """
        # 定义重点股票池
        hot_stocks = [
            # 金融
            '000001', '600000', '601398', '601288', '601939',
            # 白酒
            '600519', '000858', '000568', '000596',
            # 科技
            '002594', '300750', '000725', '600584',
            # 医药
            '600276', '000538', '600436',
            # 新能源
            '601012', '601669', '600438',
            # 消费
            '000333', '002415', '000651'
        ]

        logger.info(f"同步 {len(hot_stocks)} 只热门股票...")

        for code in hot_stocks:
            await self.sync_single_stock(code)
            await asyncio.sleep(1)


async def main():
    """主入口"""
    parser = argparse.ArgumentParser(description='公司基本面数据同步')
    parser.add_argument('--code', type=str, help='同步单只股票，如: 000001')
    parser.add_argument('--batch', type=int, default=50, help='批次大小 (默认50)')
    parser.add_argument('--max', type=int, help='最大同步股票数')
    parser.add_argument('--hot', action='store_true', help='只同步热门股票')
    parser.add_argument('--init', action='store_true', help='初始化数据库表')

    args = parser.parse_args()

    # 初始化数据库
    if args.init:
        logger.info("初始化数据库表...")
        init_database()
        logger.info("✅ 数据库表初始化完成")
        return

    # 创建同步管理器
    sync = FundamentalDataSync(batch_size=args.batch)

    if args.code:
        # 同步单只股票
        success = await sync.sync_single_stock(args.code)
        exit(0 if success else 1)

    elif args.hot:
        # 同步热门股票
        await sync.sync_hot_stocks()

    else:
        # 全量同步
        await sync.sync_all_stocks(max_stocks=args.max)


if __name__ == "__main__":
    asyncio.run(main())
