"""迅投QMT数据客户端封装

完整封装 xtquant.xtdata 行情数据接口。
API 参考: http://dict.thinktrader.net/nativeApi/xtdata.html

支持标准 QMT 终端和 MiniQMT 极简版两种模式:
  - 标准 QMT: 启动交易终端 (行情+交易) 后外部 Python 通过 xtquant 连接
  - MiniQMT: 启动极简客户端 (XtMiniQmt.exe) 后连接
两种模式使用相同 xtquant API, 本模块自动探测并连接。
"""
from typing import List, Dict, Any, Optional, Callable

from src.common.logger import get_logger
from src.common.config import settings

logger = get_logger(__name__)


class QMTClient:
    """迅投QMT数据客户端

    所有方法按官方文档分类:
    1. 行情接口 (订阅/获取/下载)
    2. 财务数据接口
    3. 基础信息接口 (合约/板块/指数/日历)
    4. 特色数据接口 (可转债/ETF/IPO)
    """

    def __init__(self, qmt_path: str = ""):
        self._path = qmt_path or settings.qmt.qmt_path
        self._xtdata = None

    @property
    def xtdata(self):
        if self._xtdata is None:
            try:
                import xtquant.xtdata as xtdata
                self._xtdata = xtdata
                xtdata.enable_hello = False
                if self._path:
                    xtdata.data_dir = self._path
                logger.info("xtquant.xtdata 模块加载成功")
                self._connect(xtdata)
            except ImportError:
                raise ImportError(
                    "xtquant 未安装。请 pip install xtquant 或从 QMT 客户端目录复制"
                )
        return self._xtdata

    @staticmethod
    def _connect(xtdata):
        """连接 QMT 数据服务, 自动探测可用端口.

        端口优先级:
          1. 自动扫描 (xtdata.connect() 默认行为)
          2. 58610 — MiniQMT / 独立交易模式
          3. 58600 — 标准 QMT 主终端
        """
        for port in (None, 58610, 58600):
            try:
                if port is None:
                    xtdata.connect()
                else:
                    xtdata.connect(port=port)
                logger.info("xtdata 连接成功 (port=%s)", port or "auto")
                return
            except Exception:
                continue
        logger.warning("xtdata 未能连接到任何 QMT 服务端, 部分 API 可能不可用")

    # ================================================================
    # 1. 行情接口
    # ================================================================

    def subscribe_quote(
        self,
        stock_code: str,
        period: str = "1d",
        start_time: str = "",
        end_time: str = "",
        count: int = 0,
        callback: Optional[Callable] = None,
    ) -> int:
        """订阅单股行情

        返回订阅号, >0 成功, -1 失败。单股订阅数量建议不超过50。
        """
        seq = self.xtdata.subscribe_quote(
            stock_code, period=period,
            start_time=start_time, end_time=end_time,
            count=count, callback=callback,
        )
        logger.info("已订阅 %s (%s), seq=%s", stock_code, period, seq)
        return seq

    def subscribe_whole_quote(
        self,
        code_list: List[str],
        callback: Optional[Callable] = None,
    ) -> int:
        """订阅全推行情

        code_list 可传市场代码 ['SH','SZ'] 或合约代码列表。
        """
        seq = self.xtdata.subscribe_whole_quote(code_list, callback=callback)
        logger.info("已订阅全推行情, %d 个标的, seq=%s", len(code_list), seq)
        return seq

    def unsubscribe_quote(self, seq: int) -> None:
        """反订阅行情"""
        self.xtdata.unsubscribe_quote(seq)

    def run(self) -> None:
        """阻塞运行, 保持实时数据连接 (订阅行情后调用)"""
        self.xtdata.run()

    def get_market_data_ex(
        self,
        stock_list: List[str],
        period: str = "1d",
        start_time: str = "",
        end_time: str = "",
        count: int = -1,
        dividend_type: str = "front",
        fill_data: bool = True,
    ) -> Dict[str, Any]:
        """获取行情数据 (推荐使用的新版接口)

        支持周期: tick, 1m, 5m, 15m, 30m, 1h, 1d, 1w, 1mon, 1q, 1hy, 1y
        Returns: {stock_code: DataFrame}
        """
        return self.xtdata.get_market_data_ex(
            field_list=[],
            stock_list=stock_list,
            period=period,
            start_time=start_time,
            end_time=end_time,
            count=count,
            dividend_type=dividend_type,
            fill_data=fill_data,
        )

    def get_market_data(
        self,
        stock_list: List[str],
        period: str = "1d",
        start_time: str = "",
        end_time: str = "",
        count: int = -1,
        dividend_type: str = "front",
        fill_data: bool = True,
    ) -> Dict[str, Any]:
        """获取行情数据 (旧版接口, 返回格式不同)

        Returns: {field: DataFrame(index=stock, columns=time)}
        """
        return self.xtdata.get_market_data(
            field_list=[],
            stock_list=stock_list,
            period=period,
            start_time=start_time,
            end_time=end_time,
            count=count,
            dividend_type=dividend_type,
            fill_data=fill_data,
        )

    def get_local_data(
        self,
        stock_list: List[str],
        period: str = "1d",
        start_time: str = "",
        end_time: str = "",
        count: int = -1,
        dividend_type: str = "front",
        fill_data: bool = True,
    ) -> Dict[str, Any]:
        """从本地数据文件获取行情 (无需连接, 速度快)

        仅用于获取 level1 数据。需先 download_history_data 下载。
        """
        return self.xtdata.get_local_data(
            field_list=[],
            stock_list=stock_list,
            period=period,
            start_time=start_time,
            end_time=end_time,
            count=count,
            dividend_type=dividend_type,
            fill_data=fill_data,
        )

    def get_full_tick(self, code_list: List[str]) -> Dict[str, Any]:
        """获取全推数据 (最新 tick 快照)

        code_list 可传 ['SH','SZ'] 获取全市场, 或传具体合约列表。
        """
        return self.xtdata.get_full_tick(code_list)

    def get_full_kline(
        self,
        stock_list: List[str],
        period: str = "1m",
        count: int = 1,
    ) -> Dict[str, Any]:
        """获取最新交易日K线全推数据

        仅支持最新一个交易日, 不含历史。
        """
        return self.xtdata.get_full_kline(
            field_list=[],
            stock_list=stock_list,
            period=period,
            count=count,
        )

    def get_divid_factors(
        self, stock_code: str, start_time: str = "", end_time: str = ""
    ) -> Any:
        """获取除权因子数据

        Returns: DataFrame (interest, stockBonus, stockGift, allotNum, allotPrice, gugai, dr)
        """
        return self.xtdata.get_divid_factors(stock_code, start_time, end_time)

    def download_history_data(
        self,
        stock_code: str,
        period: str = "1d",
        start_time: str = "",
        end_time: str = "",
        incrementally: Optional[bool] = None,
    ) -> None:
        """下载单只合约历史行情到本地 (同步阻塞)

        incrementally: True=增量, False=全量, None=由start_time决定
        """
        self.xtdata.download_history_data(
            stock_code, period,
            start_time=start_time, end_time=end_time,
            incrementally=incrementally,
        )

    def download_history_data2(
        self,
        stock_list: List[str],
        period: str = "1d",
        start_time: str = "",
        end_time: str = "",
        callback: Optional[Callable] = None,
        incrementally: Optional[bool] = None,
    ) -> None:
        """批量下载历史行情到本地 (同步阻塞, 带进度回调)"""
        logger.info(
            "开始下载历史数据: %d 只, period=%s, %s~%s",
            len(stock_list), period, start_time, end_time,
        )
        self.xtdata.download_history_data2(
            stock_list=stock_list,
            period=period,
            start_time=start_time,
            end_time=end_time,
            callback=callback,
            incrementally=incrementally,
        )

    def download_history_contracts(self) -> None:
        """下载过期(退市)合约信息"""
        logger.info("下载退市合约信息...")
        self.xtdata.download_history_contracts()

    # ================================================================
    # 2. 财务数据接口
    # ================================================================

    def get_financial_data(
        self,
        stock_list: List[str],
        table_list: List[str],
        start_time: str = "",
        end_time: str = "",
        report_type: str = "announce_time",
    ) -> Dict[str, Any]:
        """获取财务数据

        table_list 可选:
        - Balance        资产负债表
        - Income         利润表
        - CashFlow       现金流量表
        - Capital        股本表
        - Holdernum      股东数
        - Top10holder    十大股东
        - Top10flowholder 十大流通股东
        - Pershareindex  每股指标

        report_type: 'announce_time'按公告日 / 'report_time'按报告截止日
        Returns: {table_name: DataFrame}
        """
        return self.xtdata.get_financial_data(
            stock_list=stock_list,
            table_list=table_list,
            start_time=start_time,
            end_time=end_time,
            report_type=report_type,
        )

    def download_financial_data(
        self,
        stock_list: List[str],
        table_list: Optional[List[str]] = None,
    ) -> None:
        """下载财务数据到本地 (同步阻塞)

        必须先下载, get_financial_data 才能获取到数据。
        table_list 为空则下载全部表。
        """
        if table_list is None:
            table_list = []
        logger.info("下载财务数据: %d 只, tables=%s", len(stock_list), table_list or "全部")
        self.xtdata.download_financial_data(stock_list, table_list)

    def download_financial_data2(
        self,
        stock_list: List[str],
        table_list: Optional[List[str]] = None,
        start_time: str = "",
        end_time: str = "",
        callback: Optional[Callable] = None,
    ) -> None:
        """批量下载财务数据 (带进度回调)"""
        if table_list is None:
            table_list = []
        logger.info("批量下载财务数据: %d 只, %s~%s", len(stock_list), start_time, end_time)
        self.xtdata.download_financial_data2(
            stock_list, table_list,
            start_time=start_time, end_time=end_time,
            callback=callback,
        )

    # ================================================================
    # 3. 基础信息接口
    # ================================================================

    def get_instrument_detail(self, stock_code: str, iscomplete: bool = False) -> Dict[str, Any]:
        """获取合约基础信息

        iscomplete=True 返回全部字段, False 返回基础字段。
        """
        result = self.xtdata.get_instrument_detail(stock_code, iscomplete)
        return result if result else {}

    def get_instrument_type(self, stock_code: str) -> Dict[str, bool]:
        """获取合约类型

        Returns: {'index': False, 'stock': True, 'fund': False, 'etf': False}
        """
        result = self.xtdata.get_instrument_type(stock_code)
        return result if result else {}

    def get_sector_list(self) -> List[str]:
        """获取所有板块名称列表"""
        return self.xtdata.get_sector_list()

    def get_stock_list_in_sector(self, sector_name: str = "沪深A股") -> List[str]:
        """获取板块成分股列表

        常用 sector_name:
        '沪深A股', '上证A股', '深证A股', '创业板', '科创板', '北交所',
        '沪深300', '中证500', '中证1000', '上证50' 等。
        """
        return self.xtdata.get_stock_list_in_sector(sector_name)

    def download_sector_data(self) -> None:
        """下载板块分类信息"""
        logger.info("下载板块分类信息...")
        self.xtdata.download_sector_data()

    def get_index_weight(self, index_code: str) -> Dict[str, float]:
        """获取指数成分权重

        Returns: {stock_code: weight, ...}
        需先调用 download_index_weight 下载。
        """
        return self.xtdata.get_index_weight(index_code)

    def download_index_weight(self) -> None:
        """下载指数成分权重信息"""
        logger.info("下载指数成分权重...")
        self.xtdata.download_index_weight()

    def get_trading_dates(
        self,
        market: str = "SH",
        start_time: str = "",
        end_time: str = "",
        count: int = -1,
    ) -> List:
        """获取交易日列表"""
        return self.xtdata.get_trading_dates(
            market, start_time=start_time, end_time=end_time, count=count,
        )

    def get_trading_calendar(
        self,
        market: str = "SH",
        start_time: str = "",
        end_time: str = "",
    ) -> List:
        """获取交易日历 (完整交易日列表)"""
        return self.xtdata.get_trading_calendar(
            market, start_time=start_time, end_time=end_time,
        )

    def get_holidays(self) -> List[str]:
        """获取截止到当年的节假日日期列表

        Returns: ['20240101', '20240210', ...]
        """
        return self.xtdata.get_holidays()

    def download_holiday_data(self) -> None:
        """下载节假日数据"""
        logger.info("下载节假日数据...")
        self.xtdata.download_holiday_data()

    def get_period_list(self) -> List[str]:
        """获取可用周期列表"""
        return self.xtdata.get_period_list()

    # ================================================================
    # 4. 特色数据 (可转债 / ETF / IPO)
    # ================================================================

    def download_cb_data(self) -> None:
        """下载全部可转债基础信息"""
        logger.info("下载可转债信息...")
        self.xtdata.download_cb_data()

    def get_cb_info(self, stock_code: str) -> Dict[str, Any]:
        """获取指定可转债信息 (需先 download_cb_data)"""
        return self.xtdata.get_cb_info(stock_code)

    def download_etf_info(self) -> None:
        """下载所有ETF申赎清单信息"""
        logger.info("下载ETF申赎清单...")
        self.xtdata.download_etf_info()

    def get_etf_info(self) -> Dict[str, Any]:
        """获取所有ETF申赎清单信息 (需先 download_etf_info)"""
        return self.xtdata.get_etf_info()

    def get_ipo_info(self, start_time: str = "", end_time: str = "") -> List[Dict[str, Any]]:
        """获取新股申购信息

        Returns: [{'securityCode':..., 'codeName':..., 'publishPrice':..., ...}]
        """
        return self.xtdata.get_ipo_info(start_time, end_time)

    # ================================================================
    # 5. 连接管理
    # ================================================================

    def reconnect(self, ip: str = "", port: int = 0) -> None:
        """重连到指定 ip:port 的 QMT 数据服务"""
        if ip and port:
            self.xtdata.reconnect(ip, port)
            logger.info("已重连 QMT (%s:%s)", ip, port)
        else:
            self.xtdata.reconnect()
            logger.info("已重连 QMT (自动)")
