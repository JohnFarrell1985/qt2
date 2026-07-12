"""A 股 / 港股交易市场规则

将证券代码统一为 QMT 委托所需的带市场后缀格式, 并封装各板块的下单规则:
  - 交易所推断 (上交所 SH / 深交所 SZ / 北交所 BJ / 港股通 HK)
  - 板块推断 (主板 / 中小板 / 创业板 / 科创板 / 北交所 / ETF基金 / 可转债 / 港股通)
  - 最小申报单位与递增单位 (每手股数, 买入下限)
  - 最小报价单位 (价格 tick) 与价格规整
  - 市价委托的交易所路由 (沪/深/北 市价类型不同)

本模块为纯函数, **不依赖 xtquant**, 便于单元测试与被 QMTTrader 复用。
代码后缀与迅投 xttrader 文档保持一致 (如 "600519.SH"、"00700.HK")。
"""
from __future__ import annotations

from enum import Enum


class Exchange(str, Enum):
    """交易市场."""

    SH = "SH"          # 上海证券交易所
    SZ = "SZ"          # 深圳证券交易所
    BJ = "BJ"          # 北京证券交易所
    HK = "HK"          # 港股通 (沪/深港通)


class Board(str, Enum):
    """证券板块 / 品种."""

    MAIN_SH = "main_sh"        # 沪市主板 (60/601/603/605)
    MAIN_SZ = "main_sz"        # 深市主板 (000/001)
    SME = "sme"                # 中小板 (002/003, 已并入深市主板)
    GEM = "gem"                # 创业板 (300/301)
    STAR = "star"              # 科创板 (688/689)
    BSE = "bse"                # 北交所 (4/8/920)
    HK_CONNECT = "hk_connect"  # 港股通 (00700.HK)
    FUND = "fund"              # 场内基金 ETF/LOF (51/56/58/15/16/159...)
    BOND = "bond"              # 可转债 / 可交换债 (11x/12x)


# QMT 委托后缀 <- 常见别名后缀
_SUFFIX_ALIAS = {
    "SH": "SH", "SS": "SH", "XSHG": "SH", "SHA": "SH",
    "SZ": "SZ", "XSHE": "SZ", "SZA": "SZ",
    "BJ": "BJ", "BSE": "BJ", "XBSE": "BJ",
    "HK": "HK", "XHKG": "HK",
}

# 前缀 <- 交易市场 (交易所字母开头, 如 "sh600519")
_PREFIX_ALIAS = {"SH": "SH", "SZ": "SZ", "BJ": "BJ", "HK": "HK"}


def _split_code(code: str) -> tuple[str, str | None]:
    """拆分为 (纯代码, 市场后缀|None), 兼容多种券商/数据源写法."""
    s = str(code or "").strip().upper().replace(" ", "")
    if not s:
        return "", None

    # 带点后缀: 600519.SH / 600519.XSHG
    if "." in s:
        num, suf = s.split(".", 1)
        return num, _SUFFIX_ALIAS.get(suf, suf)

    # 字母前缀: SH600519 / sz000001 / HK00700
    for pre, mkt in _PREFIX_ALIAS.items():
        if s.startswith(pre) and s[len(pre):].isdigit():
            return s[len(pre):], mkt

    return s, None


def infer_exchange(code: str) -> Exchange:
    """推断证券所属交易市场."""
    bare, suf = _split_code(code)

    if suf in ("SH", "SZ", "BJ", "HK"):
        return Exchange(suf)

    # 港股通: 5 位 (或更短) 数字
    if bare.isdigit() and len(bare) <= 5:
        return Exchange.HK

    if not bare:
        return Exchange.SH

    # 北交所: 4/8 开头 6 位, 或 920 段
    if bare.startswith("920") or (bare[0] in ("4", "8") and len(bare) == 6):
        return Exchange.BJ

    # 上交所: 5/6/9 开头, 或 11 开头 (沪市可转债/企业债)
    if bare[0] in ("5", "6", "9") or bare.startswith("11"):
        return Exchange.SH

    # 其余 (0/1(非11)/2/3 开头) 归深交所
    return Exchange.SZ


def infer_board(code: str) -> Board:
    """推断证券板块 / 品种."""
    bare, _ = _split_code(code)
    exch = infer_exchange(code)

    if exch == Exchange.HK:
        return Board.HK_CONNECT
    if exch == Exchange.BJ:
        return Board.BSE

    if bare.startswith(("688", "689")):
        return Board.STAR
    if bare.startswith(("300", "301")):
        return Board.GEM
    if bare.startswith(("002", "003")):
        return Board.SME
    if bare.startswith(("11", "12", "110", "113", "118", "123", "127", "128")):
        return Board.BOND
    if bare.startswith(("51", "52", "56", "58", "159", "15", "16", "50")):
        return Board.FUND
    if exch == Exchange.SH:
        return Board.MAIN_SH
    return Board.MAIN_SZ


def normalize_qmt_code(code: str) -> str:
    """统一为 QMT 委托代码 (``NNNNNN.SH`` / ``NNNNNN.SZ`` / ``NNNNNN.BJ`` / ``NNNNN.HK``).

    已是标准格式的代码原样返回 (仅大写化)。无法识别的输入原样返回。
    """
    bare, _ = _split_code(code)
    if not bare or not bare.isdigit():
        return str(code or "").strip().upper()

    exch = infer_exchange(code)
    if exch == Exchange.HK:
        return f"{bare.zfill(5)}.HK"
    return f"{bare.zfill(6)}.{exch.value}"


# --- 数量规则 (每手 / 买入下限 / 递增单位) -------------------------------------

def min_buy_lot(code: str) -> int:
    """买入最小申报数量 (股).

    - 主板 / 中小板 / 基金 : 100 股整数倍
    - 创业板 / 北交所      : 100 股起, 1 股递增
    - 科创板               : 200 股起, 1 股递增
    - 可转债               : 10 张起 (按 10 张整数倍)
    - 港股通               : 每手股数随标的而定, 无法从代码推断, 默认 1
    """
    board = infer_board(code)
    if board == Board.STAR:
        return 200
    if board == Board.BOND:
        return 10
    if board == Board.HK_CONNECT:
        return 1
    return 100


def qty_step(code: str) -> int:
    """申报数量递增单位 (股)."""
    board = infer_board(code)
    if board in (Board.STAR, Board.GEM, Board.BSE):
        return 1
    if board == Board.BOND:
        return 10
    if board == Board.HK_CONNECT:
        return 1
    return 100  # 主板 / 中小板 / 基金: 100 股整数倍


def normalize_quantity(code: str, quantity: int | float, side: str = "buy") -> int:
    """按板块规则规整申报数量.

    买入: 不足最小申报量则抬升至下限, 并向下取整到递增单位。
    卖出: A 股允许一次性卖出零股尾数, 故仅取整不强制下限 (港股仍按整手)。
    """
    q = int(quantity)
    if q <= 0:
        return 0

    board = infer_board(code)
    step = qty_step(code)
    is_buy = str(side).lower() in ("buy", "credit_buy", "credit_fin_buy", "long")

    if not is_buy:
        # 卖出: 港股按整手向下取整, A 股允许零股尾数一次性卖出
        if board == Board.HK_CONNECT:
            return q
        return q

    lot = min_buy_lot(code)
    if q < lot:
        return lot
    # 向下取整到递增单位
    return (q // step) * step


# --- 价格规则 (最小变动价位) ---------------------------------------------------

def price_decimals(code: str) -> int:
    """报价最小变动价位对应的小数位数.

    - 股票 (主板/中小板/创业板/科创板/北交所): 0.01 元 → 2 位
    - 场内基金 / 可转债 / 港股通            : 0.001 元 → 3 位
    """
    board = infer_board(code)
    if board in (Board.FUND, Board.BOND, Board.HK_CONNECT):
        return 3
    return 2


def normalize_price(code: str, price: float) -> float:
    """将委托价格规整到最小变动价位; price<=0 (市价) 原样返回."""
    if price is None or price <= 0:
        return price
    return round(float(price), price_decimals(code))


def price_limit_pct(code: str) -> float:
    """日涨跌幅限制 (%), 仅供参考风控使用.

    - 科创板 / 创业板 : 20%
    - 北交所           : 30%
    - 港股通           : 无固定涨跌幅
    - 主板 / 中小板   : 10%
    """
    board = infer_board(code)
    if board in (Board.STAR, Board.GEM):
        return 20.0
    if board == Board.BSE:
        return 30.0
    if board == Board.HK_CONNECT:
        return 0.0
    return 10.0


# --- 市价委托路由 --------------------------------------------------------------

def supports_market_order(code: str) -> bool:
    """该标的是否支持市价委托 (港股通仅支持限价)."""
    return infer_board(code) != Board.HK_CONNECT


def market_price_type_alias(code: str) -> str:
    """返回该交易所推荐的市价委托类型别名 (对手方最优价格).

    沪/深/北交所股票均支持 ``MARKET_PEER_PRICE_FIRST`` (对手方最优价格委托),
    是最通用的市价方式。港股通不支持市价, 回退为限价 ``FIX_PRICE``。
    """
    if not supports_market_order(code):
        return "FIX_PRICE"
    return "MARKET_PEER_PRICE_FIRST"
