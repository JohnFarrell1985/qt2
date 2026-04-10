"""迅投QMT交易客户端封装

封装XtTrader的下单、撤单、查询接口。
API 参考: https://dict.thinktrader.net/nativeApi/xttrader.html

支持标准 QMT 终端和 MiniQMT 极简版:
  - 通过 QMT 安装目录的 userdata_mini 路径与终端建立通信
  - 使用前需先手动登录 QMT 终端 (行情+交易模式)
模拟盘和实盘使用相同API，仅账户类型不同。
"""
import time
from typing import Optional, List, Dict, Any, Callable

from src.common.logger import get_logger
from src.common.config import settings

logger = get_logger(__name__)


class TraderCallback:
    """交易回调基类"""

    def on_disconnected(self):
        logger.warning("交易连接断开")

    def on_stock_order(self, order):
        logger.info("委托回报: %s %s", order.stock_code, order.order_status)

    def on_stock_trade(self, trade):
        logger.info("成交回报: %s 价%s 量%s", trade.stock_code, trade.traded_price, trade.traded_volume)

    def on_order_error(self, error):
        logger.error("委托报错: %s", error.error_msg)

    def on_order_stock_async_response(self, response):
        logger.info("异步委托回调: seq=%s", response.seq)


class QMTTrader:
    """迅投QMT交易客户端"""

    def __init__(
        self,
        account_id: str = "",
        qmt_path: str = "",
        account_type: str = "STOCK",
        session_id: Optional[int] = None,
    ):
        self._account_id = account_id or settings.qmt.account_id
        self._path = qmt_path or settings.qmt.qmt_path
        self._account_type = account_type or settings.qmt.account_type
        self._session_id = session_id or int(time.time())
        self._trader = None
        self._account = None
        self._connected = False

    def connect(self) -> bool:
        """建立交易连接"""
        try:
            from xtquant.xttrader import XtQuantTrader, XtQuantTraderCallback
            from xtquant.xttype import StockAccount

            self._trader = XtQuantTrader(self._path, self._session_id)
            self._account = StockAccount(self._account_id, self._account_type)

            callback = TraderCallback()
            self._trader.register_callback(callback)
            self._trader.start()

            result = self._trader.connect()
            if result == 0:
                sub_result = self._trader.subscribe(self._account)
                self._connected = sub_result == 0
                logger.info("交易连接成功, 账户: %s", self._account_id)
                return True
            else:
                logger.error("交易连接失败: %s", result)
                return False
        except ImportError:
            raise ImportError("xtquant 未安装，无法使用交易功能")
        except Exception as e:
            logger.error("交易连接异常: %s", e)
            return False

    def order_stock(
        self,
        code: str,
        direction: str,
        quantity: int,
        price_type: str = "LATEST_PRICE",
        price: float = 0,
        strategy_name: str = "",
        order_remark: str = "",
    ) -> int:
        """同步下单

        Args:
            code: 股票代码 如 "600519.SH"
            direction: "buy" 或 "sell"
            quantity: 数量
            price_type: "FIX_PRICE"定价 / "LATEST_PRICE"最新价
            price: 指定价格(定价时)
        Returns:
            order_id
        """
        from xtquant import xtconstant

        if not self._connected:
            raise ConnectionError("未连接交易服务")

        xt_direction = xtconstant.STOCK_BUY if direction == "buy" else xtconstant.STOCK_SELL
        xt_price_type = xtconstant.FIX_PRICE if price_type == "FIX_PRICE" else xtconstant.LATEST_PRICE

        order_id = self._trader.order_stock(
            self._account, code, xt_direction, quantity,
            xt_price_type, price, strategy_name, order_remark,
        )
        logger.info("下单: %s %s x%d @ %s, order_id=%s", direction, code, quantity, price_type, order_id)
        return order_id

    def order_stock_async(
        self,
        code: str,
        direction: str,
        quantity: int,
        price_type: str = "LATEST_PRICE",
        price: float = 0,
        strategy_name: str = "",
        order_remark: str = "",
    ) -> int:
        """异步下单，返回序号"""
        from xtquant import xtconstant

        if not self._connected:
            raise ConnectionError("未连接交易服务")

        xt_direction = xtconstant.STOCK_BUY if direction == "buy" else xtconstant.STOCK_SELL
        xt_price_type = xtconstant.FIX_PRICE if price_type == "FIX_PRICE" else xtconstant.LATEST_PRICE

        seq = self._trader.order_stock_async(
            self._account, code, xt_direction, quantity,
            xt_price_type, price, strategy_name, order_remark,
        )
        return seq

    def cancel_order(self, order_id: int) -> int:
        """撤单"""
        if not self._connected:
            raise ConnectionError("未连接交易服务")
        return self._trader.cancel_order_stock(self._account, order_id)

    def query_asset(self) -> Dict[str, Any]:
        """查询资产"""
        if not self._connected:
            raise ConnectionError("未连接交易服务")
        asset = self._trader.query_stock_asset(self._account)
        if asset:
            return {
                "total_asset": asset.total_asset,
                "cash": asset.cash,
                "market_value": asset.market_value,
                "frozen_cash": asset.frozen_cash,
            }
        return {}

    def query_positions(self) -> List[Dict[str, Any]]:
        """查询持仓"""
        if not self._connected:
            raise ConnectionError("未连接交易服务")
        positions = self._trader.query_stock_positions(self._account)
        if positions is None:
            return []
        result = []
        for p in positions:
            if p.volume > 0:
                result.append({
                    "code": p.stock_code,
                    "volume": p.volume,
                    "can_use_volume": p.can_use_volume,
                    "open_price": p.open_price,
                    "avg_price": getattr(p, "avg_price", 0),
                    "market_value": p.market_value,
                    "frozen_volume": getattr(p, "frozen_volume", 0),
                })
        return result

    def query_orders(self, cancelable_only: bool = False) -> List[Dict[str, Any]]:
        """查询当日委托

        cancelable_only: True 仅返回可撤委托
        """
        if not self._connected:
            raise ConnectionError("未连接交易服务")
        orders = self._trader.query_stock_orders(self._account, cancelable_only)
        if orders is None:
            return []
        from xtquant import xtconstant
        return [
            {
                "order_id": o.order_id,
                "code": o.stock_code,
                "direction": "buy" if o.order_type == xtconstant.STOCK_BUY else "sell",
                "quantity": o.order_volume,
                "price": o.price,
                "status": o.order_status,
                "traded_volume": o.traded_volume,
            }
            for o in orders
        ]

    @property
    def is_connected(self) -> bool:
        return self._connected
