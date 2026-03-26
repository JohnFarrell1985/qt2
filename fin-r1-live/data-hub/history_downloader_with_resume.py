"""
Fin-R1 Data Hub - History Downloader with Resume Support
支持断点续传的历史数据下载器

特性:
1. 每个股票的下载进度独立记录
2. 中断后可以从断点继续下载
3. 支持失败重试（最多3次）
4. 实时显示下载进度和统计
5. 下载完成后自动验证数据完整性

使用:
    python history_downloader_with_resume.py              # 全新下载
    python history_downloader_with_resume.py --resume   # 断点续传
    python history_downloader_with_resume.py --status   # 查看下载状态
    python history_downloader_with_resume.py --retry    # 重试失败的任务
"""
import asyncio
import akshare as ak
import pandas as pd
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional, Tuple
import logging
import argparse
from tqdm.asyncio import tqdm

from database import (
    get_db_session, init_database,
    StockDAO, StockDailyDAO, DataSyncLog, StockDownloadProgressDAO,
    Stock, StockDaily, StockDownloadProgress
)

# 配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

import os

START_DATE = date(2024, 1, 1)
BATCH_SIZE = 1000

# 从环境变量读取配置，使用默认值
CONCURRENT_DOWNLOADS = int(os.getenv('CONCURRENT_DOWNLOADS', '1'))  # 串行下载，避免触发限流
AKSHARE_TIMEOUT = int(os.getenv('AKSHARE_TIMEOUT', '90'))  # 增加超时时间
REQUEST_DELAY = float(os.getenv('REQUEST_DELAY', '2.0'))  # 每只股票的请求间隔（秒）
BATCH_PAUSE = int(os.getenv('BATCH_PAUSE', '10'))  # 每批次完成后的暂停时间（秒）
BATCH_SIZE_DOWNLOAD = int(os.getenv('BATCH_SIZE_DOWNLOAD', '20'))  # 每批次下载的股票数量（更小的批次）
MAX_DOWNLOAD_RETRIES = int(os.getenv('MAX_DOWNLOAD_RETRIES', '3'))  # 单只股票下载最大重试次数


class ResumableHistoryDownloader:
    """支持断点续传的历史数据下载器"""

    def __init__(self, sync_type: str = 'history_full'):
        self.sync_type = sync_type
        self.downloaded_count = 0
        self.failed_stocks: List[str] = []
        self.skipped_count = 0

    async def _run_sync(self, func, *args, timeout: int = AKSHARE_TIMEOUT, **kwargs):
        """在线程池中运行同步函数，带超时控制"""
        loop = asyncio.get_event_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(None, lambda: func(*args, **kwargs)),
            timeout=timeout
        )

    async def fetch_stock_list(self, max_retries: int = 3) -> List[Dict]:
        """获取所有A股股票列表"""
        logger.info("正在获取股票列表...")

        for attempt in range(max_retries):
            try:
                df = await self._run_sync(ak.stock_info_a_code_name)

                if len(df) < 4000:
                    logger.warning(f"股票列表可能不完整: 仅返回 {len(df)} 只")
                    if attempt < max_retries - 1:
                        await asyncio.sleep(1)
                        continue

                stocks = []
                for _, row in df.iterrows():
                    code = str(row['code'])
                    name = str(row['name'])

                    if not code.isdigit() or len(code) != 6:
                        continue

                    if code.startswith('6'):
                        exchange = 'SH'
                    elif code.startswith('0') or code.startswith('3'):
                        exchange = 'SZ'
                    elif code.startswith('4') or code.startswith('8'):
                        exchange = 'BJ'
                    else:
                        exchange = 'OTHER'

                    stocks.append({'code': code, 'name': name, 'exchange': exchange})

                logger.info(f"✅ 成功获取 {len(stocks)} 只股票")
                return stocks

            except Exception as e:
                logger.error(f"获取股票列表失败 (尝试 {attempt + 1}/{max_retries}): {e}")
                if attempt < max_retries - 1:
                    await asyncio.sleep(1)

        return []

    async def fetch_stock_history(
        self,
        code: str,
        start_date: date = START_DATE,
        end_date: Optional[date] = None,
        max_retries: int = 3
    ) -> Tuple[List[Dict], Optional[str]]:
        """
        下载单只股票的历史日线数据（带指数退避重试）

        Returns:
            (data_list, error_message)
        """
        if end_date is None:
            end_date = date.today()

        last_error = None
        for attempt in range(max_retries):
            try:
                # 添加请求间隔（除第一次外）
                if attempt > 0:
                    delay = min(2 ** attempt, 30)  # 指数退避: 2, 4, 8... 最大30秒
                    logger.debug(f"{code} 第 {attempt + 1} 次尝试，等待 {delay} 秒...")
                    await asyncio.sleep(delay)

                df = await self._run_sync(
                    ak.stock_zh_a_hist,
                    symbol=code,
                    period="daily",
                    start_date=start_date.strftime("%Y%m%d"),
                    end_date=end_date.strftime("%Y%m%d"),
                    adjust="qfq"
                )

                if df.empty:
                    return [], None

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

                return history, None

            except Exception as e:
                last_error = str(e)
                error_type = type(e).__name__

                # 检查是否为连接断开错误
                if "RemoteDisconnected" in last_error or "Connection aborted" in last_error:
                    logger.warning(f"{code} 连接被断开 (尝试 {attempt + 1}/{max_retries})，将重试...")
                    if attempt < max_retries - 1:
                        continue  # 继续重试
                elif "timeout" in last_error.lower():
                    logger.warning(f"{code} 请求超时 (尝试 {attempt + 1}/{max_retries})，将重试...")
                    if attempt < max_retries - 1:
                        continue
                else:
                    # 其他错误，记录并跳出
                    logger.error(f"下载{code}历史数据失败: {last_error}")
                    break

        # 所有重试都失败
        self.failed_stocks.append(code)
        return [], last_error

    def init_download_progress(self, stocks: List[Dict], start_date: date, end_date: date):
        """初始化所有股票的下载进度记录"""
        logger.info(f"初始化 {len(stocks)} 只股票的下载进度记录...")

        # 计算预期交易日数（粗略估计）
        days = (end_date - start_date).days
        expected_records = int(days * 0.7)  # 约70%为交易日

        with get_db_session() as session:
            for stock in stocks:
                StockDownloadProgressDAO.init_progress(
                    session=session,
                    code=stock['code'],
                    sync_type=self.sync_type,
                    start_date=start_date,
                    end_date=end_date,
                    expected_count=expected_records
                )

        logger.info(f"✅ 已初始化 {len(stocks)} 条进度记录")

    async def download_single_stock(
        self,
        code: str,
        start_date: date,
        end_date: date
    ) -> Tuple[int, Optional[str]]:
        """下载单只股票，并更新进度"""

        # 1. 标记为正在运行
        with get_db_session() as session:
            StockDownloadProgressDAO.update_progress(
                session=session,
                code=code,
                sync_type=self.sync_type,
                records_count=0,
                status='running'
            )

        # 2. 下载数据（使用环境变量配置的重试次数）
        data, error = await self.fetch_stock_history(code, start_date, end_date, max_retries=MAX_DOWNLOAD_RETRIES)

        if error:
            # 下载失败
            with get_db_session() as session:
                StockDownloadProgressDAO.mark_failed(
                    session=session,
                    code=code,
                    sync_type=self.sync_type,
                    error_message=error
                )
            return 0, error

        if not data:
            # 没有数据（可能是新股或停牌）
            with get_db_session() as session:
                StockDownloadProgressDAO.update_progress(
                    session=session,
                    code=code,
                    sync_type=self.sync_type,
                    records_count=0,
                    status='success'
                )
            return 0, None

        # 3. 保存到数据库
        try:
            with get_db_session() as session:
                count = StockDailyDAO.bulk_insert_daily_data(session, data)

                # 更新进度为成功
                actual_start = min(d['trade_date'] for d in data)
                actual_end = max(d['trade_date'] for d in data)

                StockDownloadProgressDAO.update_progress(
                    session=session,
                    code=code,
                    sync_type=self.sync_type,
                    records_count=count,
                    actual_start=actual_start,
                    actual_end=actual_end,
                    status='success'
                )

                return count, None

        except Exception as e:
            error_msg = f"保存数据失败: {str(e)}"
            with get_db_session() as session:
                StockDownloadProgressDAO.mark_failed(
                    session=session,
                    code=code,
                    sync_type=self.sync_type,
                    error_message=error_msg
                )
            return 0, error_msg

    async def download_all_with_resume(
        self,
        stocks: List[Dict],
        start_date: date = START_DATE,
        resume: bool = False
    ) -> int:
        """
        批量下载所有股票历史数据，支持断点续传

        Args:
            stocks: 股票列表
            start_date: 开始日期
            resume: 是否断点续传（只下载未完成的）
        """
        end_date = date.today()
        total_records = 0

        # 1. 初始化进度记录（如果不是续传）
        if not resume:
            self.init_download_progress(stocks, start_date, end_date)
            target_stocks = stocks
        else:
            # 获取未完成的股票
            with get_db_session() as session:
                incomplete = StockDownloadProgressDAO.get_incomplete_stocks(session, self.sync_type)
                target_codes = {p.code for p in incomplete}
                target_stocks = [s for s in stocks if s['code'] in target_codes]

            logger.info(f"断点续传: {len(target_stocks)} 只股票需要下载")

        if not target_stocks:
            logger.info("✅ 所有股票数据已下载完成")
            return 0

        # 2. 创建并发控制
        semaphore = asyncio.Semaphore(CONCURRENT_DOWNLOADS)

        async def download_with_limit(stock):
            async with semaphore:
                code = stock['code']
                count, error = await self.download_single_stock(code, start_date, end_date)

                # 添加请求间隔，避免触发限流
                if REQUEST_DELAY > 0:
                    await asyncio.sleep(REQUEST_DELAY)

                if error:
                    return code, 0, error
                return code, count, None

        # 3. 记录同步日志
        with get_db_session() as session:
            sync_log = DataSyncLog(
                sync_type=self.sync_type,
                status='running',
                message=f'开始下载 {len(target_stocks)} 只股票（{"断点续传" if resume else "全新下载"}）'
            )
            session.add(sync_log)
            session.flush()
            log_id = sync_log.id

        # 4. 分批并发下载
        logger.info(f"开始下载 {len(target_stocks)} 只股票（并发={CONCURRENT_DOWNLOADS}, 批次大小={BATCH_SIZE_DOWNLOAD}）...")

        completed = 0
        failed = 0

        # 分批处理
        for batch_start in range(0, len(target_stocks), BATCH_SIZE_DOWNLOAD):
            batch_end = min(batch_start + BATCH_SIZE_DOWNLOAD, len(target_stocks))
            batch = target_stocks[batch_start:batch_end]

            logger.info(f"📦 批次 {batch_start//BATCH_SIZE_DOWNLOAD + 1}/{(len(target_stocks)-1)//BATCH_SIZE_DOWNLOAD + 1}: 下载 {len(batch)} 只股票 ({batch_start+1}-{batch_end})")

            # 创建批次任务
            tasks = [download_with_limit(stock) for stock in batch]

            # 执行批次下载
            for i, task in enumerate(tqdm.as_completed(
                tasks,
                total=len(tasks),
                desc=f"批次 {batch_start//BATCH_SIZE_DOWNLOAD + 1}"
            )):
                try:
                    code, count, error = await task

                    if error:
                        failed += 1
                        logger.warning(f"[{batch_start+i+1}/{len(target_stocks)}] {code} 下载失败: {error}")
                    else:
                        completed += 1
                        total_records += count

                except Exception as e:
                    logger.error(f"处理下载结果失败: {e}")
                    failed += 1

            # 批次完成后显示进度
            self._show_progress_summary()

            # 批次间暂停（如果不是最后一批）
            if batch_end < len(target_stocks) and BATCH_PAUSE > 0:
                logger.info(f"⏸️ 批次完成，暂停 {BATCH_PAUSE} 秒...")
                await asyncio.sleep(BATCH_PAUSE)

        # 5. 更新同步日志
        with get_db_session() as session:
            sync_log = session.query(DataSyncLog).get(log_id)
            sync_log.end_time = datetime.now()
            sync_log.status = 'success' if failed == 0 else 'partial'
            sync_log.records_count = total_records
            sync_log.message = f'完成，成功: {completed}, 失败: {failed}'

        logger.info(f"✅ 下载完成: {total_records} 条记录，成功: {completed} 只，失败: {failed} 只")
        return total_records

    def _show_progress_summary(self):
        """显示当前进度汇总"""
        with get_db_session() as session:
            summary = StockDownloadProgressDAO.get_download_summary(session, self.sync_type)

            logger.info(
                f"进度: {summary['completion_rate']:.1f}% | "
                f"成功: {summary['success']}/{summary['total']} | "
                f"失败: {summary['failed']} | "
                f"记录: {summary['total_records']:,}"
            )

    def get_download_status(self) -> Dict[str, Any]:
        """获取当前下载状态"""
        with get_db_session() as session:
            summary = StockDownloadProgressDAO.get_download_summary(session, self.sync_type)

            # 获取失败的列表
            failed_stocks = StockDownloadProgressDAO.get_failed_stocks(session, self.sync_type)

            return {
                'summary': summary,
                'failed_stocks': [
                    {
                        'code': p.code,
                        'retry_count': p.retry_count,
                        'max_retries': p.max_retries,
                        'error': p.error_message
                    }
                    for p in failed_stocks
                ],
                'can_resume': summary['pending'] > 0 or (summary['failed'] > 0 and any(
                    p.retry_count < p.max_retries for p in failed_stocks
                ))
            }

    def retry_failed(self) -> int:
        """重试失败的任务"""
        with get_db_session() as session:
            count = StockDownloadProgressDAO.reset_failed_progress(session, self.sync_type)
            logger.info(f"已重置 {count} 个失败任务，可以重新下载")
            return count


def print_status_table(status: Dict[str, Any]):
    """打印状态表格"""
    summary = status['summary']

    print("\n" + "=" * 80)
    print("下载状态汇总")
    print("=" * 80)
    print(f"总计: {summary['total']} 只股票")
    print(f"完成: {summary['success']} 只 ({summary['completion_rate']:.1f}%)")
    print(f"待下载: {summary['pending']} 只")
    print(f"下载中: {summary['running']} 只")
    print(f"失败: {summary['failed']} 只")
    print(f"总记录数: {summary['total_records']:,}")

    if status['failed_stocks']:
        print("\n失败的股票（最多显示10只）:")
        for s in status['failed_stocks'][:10]:
            print(f"  {s['code']}: 重试 {s['retry_count']}/{s['max_retries']}, 错误: {s['error'][:50]}")

    if status['can_resume']:
        print("\n✅ 可以执行断点续传: python history_downloader_with_resume.py --resume")
    else:
        print("\n✅ 所有股票下载完成或已达到最大重试次数")
    print("=" * 80)


async def main():
    """主入口"""
    parser = argparse.ArgumentParser(description='支持断点续传的历史数据下载器')
    parser.add_argument('--resume', action='store_true', help='断点续传（只下载未完成的）')
    parser.add_argument('--status', action='store_true', help='查看下载状态')
    parser.add_argument('--retry', action='store_true', help='重置失败任务并重新下载')
    parser.add_argument('--sample', type=int, help='只下载指定数量的股票（测试用）')
    parser.add_argument('--init-only', action='store_true', help='只初始化进度记录，不下载')

    args = parser.parse_args()

    # 初始化数据库
    init_database()

    downloader = ResumableHistoryDownloader(sync_type='history_full')

    # 查看状态
    if args.status:
        status = downloader.get_download_status()
        print_status_table(status)
        return

    # 重试失败任务
    if args.retry:
        count = downloader.retry_failed()
        if count > 0:
            logger.info(f"已重置 {count} 个失败任务，开始重新下载...")
            args.resume = True
        else:
            logger.info("没有可重试的失败任务")
            return

    # 获取股票列表
    stocks = await downloader.fetch_stock_list()
    if not stocks:
        logger.error("获取股票列表失败")
        return

    # 测试模式：只下载部分股票
    if args.sample:
        stocks = stocks[:args.sample]
        logger.info(f"测试模式: 只下载前 {args.sample} 只股票")

    # 只初始化进度记录
    if args.init_only:
        downloader.init_download_progress(stocks, START_DATE, date.today())
        logger.info("✅ 进度记录初始化完成，可以开始下载")
        return

    # 执行下载
    total = await downloader.download_all_with_resume(
        stocks,
        start_date=START_DATE,
        resume=args.resume
    )

    # 显示最终状态
    logger.info("\n最终状态:")
    status = downloader.get_download_status()
    print_status_table(status)


if __name__ == "__main__":
    asyncio.run(main())
