"""
Fin-R1 Data Hub - Historical Data Downloader
历史数据下载模块

功能:
1. 下载2024年1月1日至今的所有A股日线数据
2. 下载股票基础信息
3. 下载大盘指数历史数据
4. 数据批量写入PostgreSQL
5. 支持增量更新

使用:
    python history_downloader.py              # 初始全量下载
    python history_downloader.py update       # 增量更新
"""
import asyncio
import akshare as ak
import pandas as pd
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
import logging
from tqdm.asyncio import tqdm

from database import (
    get_db_session, init_database,
    StockDAO, StockDailyDAO, DataSyncLog,
    Stock, StockDaily
)

# 配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

START_DATE = date(2024, 1, 1)
BATCH_SIZE = 1000
CONCURRENT_DOWNLOADS = 5
AKSHARE_TIMEOUT = 60  # API调用超时（秒）


class HistoryDownloader:
    """历史数据下载器"""

    def __init__(self):
        self.downloaded_count = 0
        self.failed_stocks = []

    async def _run_sync(self, func, *args, timeout: int = AKSHARE_TIMEOUT, **kwargs):
        """在线程池中运行同步函数，带超时控制"""
        loop = asyncio.get_event_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(None, lambda: func(*args, **kwargs)),
            timeout=timeout
        )

    async def fetch_stock_list(self, max_retries: int = 3) -> List[Dict]:
        """
        获取所有A股股票列表

        注意: 会验证数据完整性，确保获取到完整股票列表（约5000+只）
        """
        logger.info("正在获取股票列表...")

        for attempt in range(max_retries):
            try:
                df = await self._run_sync(ak.stock_info_a_code_name)

                # 验证数据完整性
                if len(df) < 4000:  # A股约有5000+只股票
                    logger.warning(f"股票列表可能不完整: 仅返回 {len(df)} 只 (期望4000+)")
                    if attempt < max_retries - 1:
                        logger.info(f"第 {attempt + 1} 次重试获取股票列表...")
                        await asyncio.sleep(1)
                        continue

                stocks = []
                for _, row in df.iterrows():
                    code = str(row['code'])
                    name = str(row['name'])

                    # 验证股票代码格式
                    if not code.isdigit() or len(code) != 6:
                        logger.warning(f"跳过无效股票代码: {code}")
                        continue

                    # 判断交易所
                    if code.startswith('6'):
                        exchange = 'SH'
                    elif code.startswith('0') or code.startswith('3'):
                        exchange = 'SZ'
                    elif code.startswith('4') or code.startswith('8'):
                        exchange = 'BJ'  # 北交所
                    else:
                        exchange = 'OTHER'

                    stocks.append({'code': code, 'name': name, 'exchange': exchange})

                logger.info(f"✅ 成功获取 {len(stocks)} 只股票")

                # 记录交易所分布
                exchange_counts = {}
                for s in stocks:
                    exchange_counts[s['exchange']] = exchange_counts.get(s['exchange'], 0) + 1
                logger.info(f"交易所分布: {exchange_counts}")

                return stocks

            except Exception as e:
                logger.error(f"获取股票列表失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)
                else:
                    logger.error("无法获取股票列表，所有重试均失败")
                    return []

        return []

    async def fetch_stock_history(
        self,
        code: str,
        start_date: date = START_DATE,
        end_date: Optional[date] = None
    ) -> List[Dict]:
        """下载单只股票的历史日线数据"""
        if end_date is None:
            end_date = date.today()

        try:
            df = await self._run_sync(
                ak.stock_zh_a_hist,
                symbol=code,
                period="daily",
                start_date=start_date.strftime("%Y%m%d"),
                end_date=end_date.strftime("%Y%m%d"),
                adjust="qfq"
            )

            if df.empty:
                return []

            history = []
            for _, row in df.iterrows():
                try:
                    history.append({
                        'code': code,
                        'trade_date': datetime.strptime(str(row['日期']), "%Y-%m-%d").date(),
                        'open': float(row['开盘']) if pd.notna(row['开盘']) else 0,
                        'high': float(row['最高']) if pd.notna(row['最高']) else 0,
                        'low': float(row['最低']) if pd.notna(row['最低']) else 0,
                        'close': float(row['收盘']) if pd.notna(row['收盘']) else 0,
                        'volume': int(float(row['成交量'])) if pd.notna(row['成交量']) else 0,
                        'amount': float(row['成交额']) if pd.notna(row['成交额']) else 0,
                        'change': float(row.get('涨跌额', 0)) if pd.notna(row.get('涨跌额')) else None,
                        'change_pct': float(row.get('涨跌幅', 0)) if pd.notna(row.get('涨跌幅')) else None,
                        'turnover_rate': float(row.get('换手率', 0)) if pd.notna(row.get('换手率')) else None,
                        'amplitude': float(row.get('振幅', 0)) if pd.notna(row.get('振幅')) else None
                    })
                except Exception as e:
                    logger.warning(f"处理{code}的行数据失败: {e}")
                    continue

            return history

        except Exception as e:
            logger.error(f"下载{code}历史数据失败: {e}")
            self.failed_stocks.append(code)
            return []

    async def download_all_history(
        self,
        stock_codes: List[str],
        start_date: date = START_DATE
    ) -> int:
        """批量下载所有股票历史数据"""
        total_records = 0
        semaphore = asyncio.Semaphore(CONCURRENT_DOWNLOADS)

        async def download_with_limit(code):
            async with semaphore:
                return await self.fetch_stock_history(code, start_date)

        # 记录同步开始
        with get_db_session() as session:
            sync_log = DataSyncLog(
                sync_type='history_full',
                status='running',
                message=f'开始全量下载 {len(stock_codes)} 只股票'
            )
            session.add(sync_log)
            session.flush()
            log_id = sync_log.id

        try:
            tasks = [download_with_limit(code) for code in stock_codes]

            for i, task in enumerate(tqdm.as_completed(tasks, total=len(tasks), desc="下载历史数据")):
                try:
                    data = await task
                    if data:
                        with get_db_session() as session:
                            count = StockDailyDAO.bulk_insert_daily_data(session, data)
                            total_records += count
                except Exception as e:
                    logger.error(f"处理下载结果失败: {e}")

            # 更新日志
            with get_db_session() as session:
                sync_log = session.query(DataSyncLog).get(log_id)
                sync_log.end_time = datetime.now()
                sync_log.status = 'success'
                sync_log.records_count = total_records
                sync_log.message = f'完成，成功: {len(stock_codes)-len(self.failed_stocks)}, 失败: {len(self.failed_stocks)}'

            logger.info(f"全量下载完成: {total_records} 条记录")
            return total_records

        except Exception as e:
            with get_db_session() as session:
                sync_log = session.query(DataSyncLog).get(log_id)
                sync_log.end_time = datetime.now()
                sync_log.status = 'failed'
                sync_log.message = str(e)[:500]
            raise

    async def incremental_update(self) -> Dict[str, int]:
        """增量更新（只下载缺失的最新数据）"""
        logger.info("开始增量更新...")

        result = {'updated': 0, 'added': 0, 'failed': 0}

        with get_db_session() as session:
            all_codes = StockDAO.get_all_stock_codes(session)

        if not all_codes:
            logger.warning("数据库中没有股票列表")
            return result

        today = date.today()

        for code in tqdm(all_codes, desc="增量更新"):
            try:
                with get_db_session() as session:
                    latest_date = StockDailyDAO.get_latest_trade_date(session, code)

                    if latest_date and latest_date >= today:
                        continue

                    start_date = latest_date + timedelta(days=1) if latest_date else START_DATE
                    if start_date > today:
                        continue

                    data = await self.fetch_stock_history(code, start_date, today)

                    if data:
                        StockDailyDAO.bulk_insert_daily_data(session, data)
                        result['added'] += len(data)
                        result['updated'] += 1

            except Exception as e:
                logger.error(f"增量更新{code}失败: {e}")
                result['failed'] += 1

        logger.info(f"增量更新完成: {result}")
        return result


async def run_full_download(sample_size: Optional[int] = None):
    """运行全量下载"""
    logger.info("=" * 60)
    logger.info("开始全量历史数据下载")
    logger.info("=" * 60)

    downloader = HistoryDownloader()

    # 获取股票列表
    stocks = await downloader.fetch_stock_list()
    if not stocks:
        logger.error("获取股票列表失败")
        return

    # 保存股票基础信息
    with get_db_session() as session:
        StockDAO.bulk_upsert_stocks(session, stocks)
        logger.info(f"已保存 {len(stocks)} 只股票基础信息")

    # 确定下载范围
    codes = [s['code'] for s in stocks]

    if sample_size:
        codes = codes[:sample_size]
        logger.info(f"下载前 {sample_size} 只股票（测试模式）")

    # 下载历史数据
    total = await downloader.download_all_history(codes, START_DATE)

    logger.info("=" * 60)
    logger.info(f"下载完成！共 {total} 条日线记录")
    logger.info("=" * 60)


if __name__ == "__main__":
    import sys

    # 初始化数据库
    init_database()

    if len(sys.argv) > 1 and sys.argv[1] == 'update':
        # 增量更新
        asyncio.run(HistoryDownloader().incremental_update())
    elif len(sys.argv) > 1 and sys.argv[1] == 'test':
        # 测试模式（只下载50只）
        asyncio.run(run_full_download(sample_size=50))
    else:
        # 全量下载（全部股票）
        asyncio.run(run_full_download())
