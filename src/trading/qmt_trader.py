"""迅投QMT交易客户端封装

封装XtTrader的下单、撤单、查询接口，覆盖全部 A 股板块与港股通:
  - 沪市主板 / 深市主板 / 中小板 / 创业板 / 科创板 / 北交所
  - 场内基金 (ETF/LOF) / 可转债
  - 港股通 (沪港通 / 深港通)

API 参考: https://dict.thinktrader.net/nativeApi/xttrader.html

支持标准 QMT 终端和 MiniQMT 极简版:
  - 通过 QMT 安装目录的 userdata_mini 路径与终端建立通信
  - 使用前需先手动登录 QMT 终端 (行情+交易模式)
模拟盘和实盘使用相同API，仅账户类型不同。

账户类型 (account_type) 支持:
  STOCK 普通 / CREDIT 两融 / HUGANGTONG 沪港通 / SHENGANGTONG 深港通 / STOCK_OPTION 期权
报价类型 (price_type) 支持限价、最新价及沪/深/北各交易所市价委托 (见 ``_PRICE_TYPE_ALIASES``)。
委托类型 (order_type) 支持普通买卖及两融担保品/融资/融券系列 (见 ``_ORDER_TYPE_ALIASES``)。
"""
import time
from typing import Optional, List, Dict, Any

from src.common.logger import get_logger
from src.common.config import settings
from src.trading import market_rules

logger = get_logger(__name__)


# account_type 入参别名 -> QMT StockAccount 账户类型字符串
_ACCOUNT_TYPE_ALIASES = {
    "STOCK": "STOCK",
    "NORMAL": "STOCK",
    "CREDIT": "CREDIT",
    "MARGIN": "CREDIT",
    "RZRQ": "CREDIT",
    "FUTURE": "FUTURE",
    "STOCK_OPTION": "STOCK_OPTION",
    "OPTION": "STOCK_OPTION",
    "HUGANGTONG": "HUGANGTONG",
    "HGT": "HUGANGTONG",
    "SHENGANGTONG": "SHENGANGTONG",
    "SGT": "SHENGANGTONG",
    # 港股通泛指, 默认沪港通 (深市标的下单 QMT 会自动路由)
    "HK": "HUGANGTONG",
}

# price_type 别名 -> xtconstant 属性名 (报价类型)
_PRICE_TYPE_ALIASES = {
    "LATEST_PRICE": "LATEST_PRICE",
    "LATEST": "LATEST_PRICE",
    "FIX_PRICE": "FIX_PRICE",
    "FIX": "FIX_PRICE",
    "LIMIT": "FIX_PRICE",
    # 上交所 / 北交所 股票市价
    "MARKET_SH_CONVERT_5_CANCEL": "MARKET_SH_CONVERT_5_CANCEL",
    "MARKET_SH_CONVERT_5_LIMIT": "MARKET_SH_CONVERT_5_LIMIT",
    # 深交所 股票市价
    "MARKET_SZ_INSTBUSI_RESTCANCEL": "MARKET_SZ_INSTBUSI_RESTCANCEL",
    "MARKET_SZ_CONVERT_5_CANCEL": "MARKET_SZ_CONVERT_5_CANCEL",
    "MARKET_SZ_FULL_OR_CANCEL": "MARKET_SZ_FULL_OR_CANCEL",
    # 沪深通用市价 (对手方 / 本方最优)
    "MARKET_PEER_PRICE_FIRST": "MARKET_PEER_PRICE_FIRST",
    "MARKET_MINE_PRICE_FIRST": "MARKET_MINE_PRICE_FIRST",
}

# order_type 别名 -> xtconstant 属性名 (委托类型)
_ORDER_TYPE_ALIASES = {
    # 普通股票
    "BUY": "STOCK_BUY",
    "SELL": "STOCK_SELL",
    # 两融
    "CREDIT_BUY": "CREDIT_BUY",                 # 担保品买入
    "CREDIT_SELL": "CREDIT_SELL",               # 担保品卖出
    "CREDIT_FIN_BUY": "CREDIT_FIN_BUY",         # 融资买入
    "CREDIT_SLO_SELL": "CREDIT_SLO_SELL",       # 融券卖出
    "CREDIT_BUY_SECU_REPAY": "CREDIT_BUY_SECU_REPAY",       # 买券还券
    "CREDIT_DIRECT_SECU_REPAY": "CREDIT_DIRECT_SECU_REPAY", # 直接还券
    "CREDIT_SELL_SECU_REPAY": "CREDIT_SELL_SECU_REPAY",     # 卖券还款
    "CREDIT_DIRECT_CASH_REPAY": "CREDIT_DIRECT_CASH_REPAY", # 直接还款
}

# 买方向委托 (用于按板块规整申报数量时判定买/卖)
_BUY_ORDER_TYPES = {
    "BUY", "CREDIT_BUY", "CREDIT_FIN_BUY", "CREDIT_BUY_SECU_REPAY",
}


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

    def on_cancel_error(self, error):
        logger.error("撤单报错: %s", getattr(error, "error_msg", error))

    def on_order_stock_async_response(self, response):
        logger.info("异步委托回调: seq=%s", response.seq)

    def on_account_status(self, status):
        logger.info("账户状态: %s %s", status.account_id, status.status)


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

    # ------------------------------------------------------------------
    # 连接
    # ------------------------------------------------------------------
    def connect(self) -> bool:
        """建立交易连接"""
        try:
            from xtquant.xttrader import XtQuantTrader
            from xtquant.xttype import StockAccount

            self._trader = XtQuantTrader(self._path, self._session_id)
            acct_type = self._resolve_account_type(self._account_type)
            self._account = StockAccount(self._account_id, acct_type)

            callback = TraderCallback()
            self._trader.register_callback(callback)
            self._trader.start()

            result = self._trader.connect()
            if result == 0:
                sub_result = self._trader.subscribe(self._account)
                self._connected = sub_result == 0
                logger.info(
                    "交易连接成功, 账户: %s (%s)", self._account_id, acct_type
                )
                return True
            else:
                logger.error("交易连接失败: %s", result)
                return False
        except ImportError:
            raise ImportError("xtquant 未安装，无法使用交易功能")
        except Exception as e:
            logger.error("交易连接异常: %s", e)
            return False

    # ------------------------------------------------------------------
    # 枚举解析
    # ------------------------------------------------------------------
    @staticmethod
    def _resolve_account_type(account_type: str) -> str:
        return _ACCOUNT_TYPE_ALIASES.get(str(account_type).upper(), str(account_type).upper())

    @staticmethod
    def _resolve_order_type(direction: str, order_type: Optional[str]):
        """解析委托类型枚举值 (股票买卖 / 两融)."""
        from xtquant import xtconstant

        key = (order_type or direction or "buy").upper()
        attr = _ORDER_TYPE_ALIASES.get(key)
        if attr is None:
            # 允许直接传 xtconstant 属性名, 未知则回退买/卖
            attr = key if hasattr(xtconstant, key) else (
                "STOCK_BUY" if str(direction).lower() == "buy" else "STOCK_SELL"
            )
        return getattr(xtconstant, attr), key

    def _resolve_price_type(self, code: str, price_type: str):
        """解析报价类型枚举值; ``MARKET`` 自动按交易所路由为对手方最优。"""
        from xtquant import xtconstant

        alias = str(price_type or "LATEST_PRICE").upper()
        if alias in ("MARKET", "MARKET_ORDER", "MKT"):
            alias = market_rules.market_price_type_alias(code)

        # 港股通不支持市价委托
        if not market_rules.supports_market_order(code) and alias not in (
            "FIX_PRICE", "FIX", "LIMIT",
        ):
            logger.warning("港股通标的 %s 仅支持限价委托, 已按限价处理", code)
            alias = "FIX_PRICE"

        attr = _PRICE_TYPE_ALIASES.get(alias, alias)
        value = getattr(xtconstant, attr, None)
        if value is None:
            logger.warning("未知报价类型 %s, 回退最新价", price_type)
            value = xtconstant.LATEST_PRICE
        return value

    # ------------------------------------------------------------------
    # 下单 / 撤单
    # ------------------------------------------------------------------
    def order_stock(
        self,
        code: str,
        direction: str = "buy",
        quantity: int = 0,
        price_type: str = "LATEST_PRICE",
        price: float = 0,
        strategy_name: str = "",
        order_remark: str = "",
        order_type: Optional[str] = None,
        normalize: bool = True,
    ) -> int:
        """同步下单 (适用于全部 A 股板块与港股通)

        Args:
            code: 证券代码, 支持多种写法 (``600519`` / ``600519.SH`` / ``sh600519`` / ``00700.HK``)
            direction: ``buy`` 或 ``sell`` (两融请用 order_type)
            quantity: 委托数量 (股 / 债券为张)
            price_type: 报价类型别名, 见 ``_PRICE_TYPE_ALIASES``;
                        ``LATEST_PRICE`` 最新价 / ``FIX_PRICE`` 限价 / ``MARKET`` 市价(对手方最优)
            price: 委托价格 (限价必填, 市价填 0)
            order_type: 委托类型别名, 见 ``_ORDER_TYPE_ALIASES`` (两融/还券等), 传入则覆盖 direction
            normalize: 是否按板块规则规整代码/数量/价格 (默认 True)
        Returns:
            order_id (>0 成功, -1 失败)
        """
        if not self._connected:
            raise ConnectionError("未连接交易服务")

        qmt_code = market_rules.normalize_qmt_code(code) if normalize else code
        xt_order_type, order_key = self._resolve_order_type(direction, order_type)
        xt_price_type = self._resolve_price_type(qmt_code, price_type)

        qty = int(quantity)
        px = price
        if normalize:
            side = "buy" if order_key in _BUY_ORDER_TYPES else "sell"
            qty = market_rules.normalize_quantity(qmt_code, quantity, side)
            px = market_rules.normalize_price(qmt_code, price)

        order_id = self._trader.order_stock(
            self._account, qmt_code, xt_order_type, qty,
            xt_price_type, px, strategy_name, order_remark,
        )
        logger.info(
            "下单: %s %s x%d @ %s(px=%s), order_id=%s",
            order_key.lower(), qmt_code, qty, price_type, px, order_id,
        )
        return order_id

    def order_stock_async(
        self,
        code: str,
        direction: str = "buy",
        quantity: int = 0,
        price_type: str = "LATEST_PRICE",
        price: float = 0,
        strategy_name: str = "",
        order_remark: str = "",
        order_type: Optional[str] = None,
        normalize: bool = True,
    ) -> int:
        """异步下单，返回请求序号 seq (与 order_stock 参数一致)"""
        if not self._connected:
            raise ConnectionError("未连接交易服务")

        qmt_code = market_rules.normalize_qmt_code(code) if normalize else code
        xt_order_type, order_key = self._resolve_order_type(direction, order_type)
        xt_price_type = self._resolve_price_type(qmt_code, price_type)

        qty = int(quantity)
        px = price
        if normalize:
            side = "buy" if order_key in _BUY_ORDER_TYPES else "sell"
            qty = market_rules.normalize_quantity(qmt_code, quantity, side)
            px = market_rules.normalize_price(qmt_code, price)

        seq = self._trader.order_stock_async(
            self._account, qmt_code, xt_order_type, qty,
            xt_price_type, px, strategy_name, order_remark,
        )
        return seq

    def cancel_order(self, order_id: int) -> int:
        """撤单 (0 成功, -1 失败)"""
        if not self._connected:
            raise ConnectionError("未连接交易服务")
        return self._trader.cancel_order_stock(self._account, order_id)

    def cancel_order_async(self, order_id: int) -> int:
        """异步撤单，返回请求序号 seq"""
        if not self._connected:
            raise ConnectionError("未连接交易服务")
        return self._trader.cancel_order_stock_async(self._account, order_id)

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
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

    def query_trades(self) -> List[Dict[str, Any]]:
        """查询当日成交"""
        if not self._connected:
            raise ConnectionError("未连接交易服务")
        trades = self._trader.query_stock_trades(self._account)
        if trades is None:
            return []
        return [
            {
                "order_id": t.order_id,
                "code": t.stock_code,
                "traded_id": getattr(t, "traded_id", ""),
                "traded_price": t.traded_price,
                "traded_volume": t.traded_volume,
                "traded_amount": getattr(t, "traded_amount", 0),
            }
            for t in trades
        ]

    def query_new_purchase_limit(self) -> Dict[str, Any]:
        """查询新股申购额度 ({'KCB':.., 'SH':.., 'SZ':..})"""
        if not self._connected:
            raise ConnectionError("未连接交易服务")
        return self._trader.query_new_purchase_limit(self._account) or {}

    def query_credit_detail(self) -> List[Dict[str, Any]]:
        """查询两融信用账户资产 (需 account_type=CREDIT)"""
        if not self._connected:
            raise ConnectionError("未连接交易服务")
        datas = self._trader.query_credit_detail(self._account)
        if not datas:
            return []
        out = []
        for d in datas:
            out.append({
                "total_asset": getattr(d, "m_dBalance", 0),
                "available": getattr(d, "m_dAvailable", 0),
                "total_debt": getattr(d, "m_dTotalDebt", 0),
                "assure_ratio": getattr(d, "m_dPerAssurescaleValue", 0),
                "net_asset": getattr(d, "m_dAssureAsset", 0),
            })
        return out

    @property
    def is_connected(self) -> bool:
        return self._connected
