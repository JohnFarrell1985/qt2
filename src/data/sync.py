"""数据同步调度

统一管理所有数据的下载与同步流程。
使用 DownloadEngine 提供分批、限流、断点续传、重试能力。

各周期默认数据范围 (通过 .env 配置):
- 日线/周线:  DL_START_1D  (默认 20160101, ~10年)
- 5分钟线:    DL_START_5M  (默认 20230101, ~3年)
- 1分钟线:    DL_START_1M  (默认 20250101, ~1年, 数据量巨大)
- tick:        DL_START_TICK (默认最近1个月)
"""
from datetime import datetime, timedelta
from typing import List, Optional

from src.common.logger import get_logger
from src.data.qmt_client import QMTClient
from src.data.market_data import MarketDataSync
from src.data.factor_data import FactorDataManager
from src.data.financial_data import FinancialDataSync
from src.data.download_engine import get_default_start

logger = get_logger(__name__)


class DataSyncManager:
    """数据同步总调度"""

    def __init__(self, client: Optional[QMTClient] = None):
        self.client = client or QMTClient()
        self.market_sync = MarketDataSync(self.client)
        self.factor_mgr = FactorDataManager(self.client)
        self.financial_sync = FinancialDataSync(self.client)

    def download_base_data(self) -> None:
        """下载基础静态数据 (板块/节假日/指数权重)

        建议按周/按日定期调用, 数据量小, 无需分批。
        """
        logger.info("开始下载基础静态数据...")
        for fn_name, fn in [
            ("板块分类", self.client.download_sector_data),
            ("节假日", self.client.download_holiday_data),
            ("指数权重", self.client.download_index_weight),
        ]:
            try:
                fn()
                logger.info(f"{fn_name}数据已下载")
            except Exception as e:
                logger.warning(f"{fn_name}数据下载失败: {e}")

    def full_sync(
        self,
        start_date: str = "",
        end_date: str = "",
        sync_minute: bool = False,
        minute_periods: Optional[List[str]] = None,
        incremental: bool = True,
    ) -> dict:
        """执行全量数据同步

        start_date: 为空则每种周期使用各自的默认起始日期
        incremental: True=增量续传(推荐), False=全量重下
        minute_periods: 要同步的分钟周期列表, 默认 ["5m"]
        """
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        if minute_periods is None:
            minute_periods = ["5m"]

        results = {}
        logger.info(f"===== 全量同步开始 (end={end_date}, incremental={incremental}) =====")

        self.download_base_data()

        stock_list = self.client.get_stock_list_in_sector("沪深A股")
        logger.info(f"沪深A股共 {len(stock_list)} 只")

        results["stocks"] = self.market_sync.sync_stock_list()

        daily_start = start_date or get_default_start("1d")
        results["daily"] = self.market_sync.sync_daily_data(
            stock_list, daily_start, end_date, incremental=incremental,
        )

        if sync_minute:
            for mp in minute_periods:
                mp_start = start_date or get_default_start(mp)
                results[f"minute_{mp}"] = self.market_sync.sync_minute_data(
                    stock_list, mp, mp_start, end_date, incremental=incremental,
                )

        idx_start = start_date or get_default_start("1d")
        results["index"] = self.market_sync.sync_index_data(
            idx_start, end_date, incremental=incremental,
        )

        results["factors_meta"] = self.factor_mgr.init_factor_meta()
        results["factors"] = self.factor_mgr.sync_factors(
            stock_list, start_time=daily_start, end_time=end_date,
        )

        results["financial_reports"] = self.financial_sync.sync_reports(
            stock_list, start_time=daily_start, end_time=end_date,
        )
        results["financial_indicators"] = self.financial_sync.sync_indicators(
            stock_list, start_time=daily_start, end_time=end_date,
        )

        logger.info(f"===== 全量同步完成: {results} =====")
        return results

    def incremental_sync(self, days_back: int = 5) -> dict:
        """增量同步最近N天数据

        始终使用增量模式, 仅补充缺失数据。
        """
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")

        self.download_base_data()

        stock_list = self.client.get_stock_list_in_sector("沪深A股")
        results = {}

        results["daily"] = self.market_sync.sync_daily_data(
            stock_list, start_date, end_date, incremental=True,
        )
        results["index"] = self.market_sync.sync_index_data(
            start_date, end_date, incremental=True,
        )
        results["factors"] = self.factor_mgr.sync_factors(
            stock_list, start_time=start_date, end_time=end_date,
        )
        results["financial_indicators"] = self.financial_sync.sync_indicators(
            stock_list, start_time=start_date, end_time=end_date,
        )

        logger.info(f"增量同步完成 ({start_date}~{end_date}): {results}")
        return results

    def sync_specific(
        self,
        stock_list: List[str],
        data_types: List[str],
        start_date: str = "",
        end_date: str = "",
        incremental: bool = True,
    ) -> dict:
        """按需同步指定数据类型

        data_types 可选:
          daily, minute_1m, minute_5m, minute_15m, minute_30m, minute_1h,
          index, factors, reports, indicators
        start_date: 空则使用各周期默认值
        """
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")

        results = {}
        for dt in data_types:
            try:
                if dt == "daily":
                    sd = start_date or get_default_start("1d")
                    results[dt] = self.market_sync.sync_daily_data(
                        stock_list, sd, end_date, incremental=incremental,
                    )
                elif dt.startswith("minute_"):
                    period = dt.replace("minute_", "")
                    sd = start_date or get_default_start(period)
                    results[dt] = self.market_sync.sync_minute_data(
                        stock_list, period, sd, end_date, incremental=incremental,
                    )
                elif dt == "index":
                    sd = start_date or get_default_start("1d")
                    results[dt] = self.market_sync.sync_index_data(
                        sd, end_date, incremental=incremental,
                    )
                elif dt == "factors":
                    sd = start_date or get_default_start("1d")
                    results[dt] = self.factor_mgr.sync_factors(
                        stock_list, start_time=sd, end_time=end_date,
                    )
                elif dt == "reports":
                    sd = start_date or get_default_start("1d")
                    results[dt] = self.financial_sync.sync_reports(
                        stock_list, start_time=sd, end_time=end_date,
                    )
                elif dt == "indicators":
                    sd = start_date or get_default_start("1d")
                    results[dt] = self.financial_sync.sync_indicators(
                        stock_list, start_time=sd, end_time=end_date,
                    )
                else:
                    logger.warning(f"未知数据类型: {dt}")
            except Exception as e:
                logger.error(f"同步 {dt} 失败: {e}")
                results[dt] = f"error: {e}"

        return results
