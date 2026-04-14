"""迅投因子看板数据加载器

延迟导入 xtquant, CI 环境安全。

P1-21: 多源因子管线 — 迅投因子数据接入
"""

import pandas as pd

from src.common.config import settings
from src.common.logger import get_logger

logger = get_logger(__name__)


class XtFactorLoader:
    """迅投 xtquant 因子看板数据加载器

    xtquant 仅在本地 QMT 客户端可用, 所有调用均做 try/except ImportError 保护。
    """

    DEFAULT_CATEGORIES: list[str] = [
        "factor_growth",
        "factor_base_derivative",
        "factor_metrics",
        "factor_quality",
        "factor_momentum",
        "factor_risk",
        "factor_sentiment",
        "factor_technical",
    ]

    def __init__(self, categories: list[str] | None = None):
        if categories is None:
            raw = settings.factor_pipeline.xt_categories
            self.categories = [c.strip() for c in raw.split(",") if c.strip()]
        else:
            self.categories = categories

        self._xtdata = None
        self._available = self._try_import()

    def _try_import(self) -> bool:
        try:
            from xtquant import xtdata  # type: ignore[import-untyped]

            self._xtdata = xtdata
            logger.info("xtquant 加载成功")
            return True
        except ImportError:
            logger.warning("xtquant 不可用 — 迅投因子功能已禁用")
            return False

    @property
    def available(self) -> bool:
        return self._available

    def load_factor(
        self,
        stock_list: list[str],
        factor_category: str,
        start_date: str = "",
        end_date: str = "",
    ) -> pd.DataFrame:
        """加载单个因子类别数据

        Args:
            stock_list: 标的代码列表, 如 ['000001.SZ', '600000.SH']
            factor_category: 因子类别, 如 'factor_growth'
            start_date: 开始日期 YYYYMMDD
            end_date: 结束日期 YYYYMMDD

        Returns:
            DataFrame, 若 xtquant 不可用则返回空 DataFrame
        """
        if not self._available or self._xtdata is None:
            logger.warning("xtquant 不可用, 跳过 %s", factor_category)
            return pd.DataFrame()

        try:
            data = self._xtdata.get_factor_data(
                stock_list=stock_list,
                factor_list=[factor_category],
                start_time=start_date,
                end_time=end_date,
            )
            if data is None or (isinstance(data, pd.DataFrame) and data.empty):
                logger.warning("因子类别 %s 返回空数据", factor_category)
                return pd.DataFrame()
            if isinstance(data, dict):
                frames = []
                for code, df in data.items():
                    if isinstance(df, pd.DataFrame) and not df.empty:
                        df = df.copy()
                        df["stock_code"] = code
                        frames.append(df)
                return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
            return data if isinstance(data, pd.DataFrame) else pd.DataFrame()
        except Exception as e:
            logger.error("加载因子 %s 失败: %s", factor_category, e)
            return pd.DataFrame()

    def download_all(
        self,
        stock_list: list[str] | None = None,
        start_date: str = "",
        end_date: str = "",
    ) -> dict[str, pd.DataFrame]:
        """下载所有配置的因子类别数据

        Returns:
            {category: DataFrame} 字典
        """
        if not self._available:
            logger.warning("xtquant 不可用, download_all 返回空字典")
            return {}

        if stock_list is None:
            stock_list = self._get_stock_list()

        result: dict[str, pd.DataFrame] = {}
        for cat in self.categories:
            logger.info("下载迅投因子: %s (%d 只标的)", cat, len(stock_list))
            df = self.load_factor(stock_list, cat, start_date, end_date)
            if not df.empty:
                result[cat] = df
                logger.info("  %s: %d 行 x %d 列", cat, len(df), len(df.columns))
            else:
                logger.warning("  %s: 无数据", cat)

        logger.info("迅投因子下载完成: %d/%d 类别有数据", len(result), len(self.categories))
        return result

    def _get_stock_list(self) -> list[str]:
        """从 xtquant 获取全市场标的列表"""
        if not self._available or self._xtdata is None:
            return []
        try:
            stocks = self._xtdata.get_stock_list_in_sector("沪深A股")
            return stocks if isinstance(stocks, list) else []
        except Exception as e:
            logger.error("获取标的列表失败: %s", e)
            return []
