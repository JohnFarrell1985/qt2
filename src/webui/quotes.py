"""行情报价提供器 — 为模拟盘估值与市价撮合提供最新价

多级降级, 保证无网络/无实时源时仍可用:
  1. ``stock_realtime`` 最新快照 (若近期有数据)
  2. ``stock_daily`` / ``etf_daily`` / ``cb_daily`` 最新收盘价
  3. (可选) akshare 实时快照 — 最佳努力, 失败即忽略
  4. 缓存的上一次已知价

代码统一以 6 位 (A 股) 或 5 位 (港股) 纯数字在库中检索。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, Optional

from sqlalchemy import text

from src.common.logger import get_logger
from src.trading import market_rules

logger = get_logger(__name__)


@dataclass
class Quote:
    code: str                 # 带市场后缀的证券代码, 如 600519.SH
    name: str = ""
    price: float = 0.0        # 最新价
    pre_close: float = 0.0    # 昨收
    ts: float = field(default_factory=time.time)

    @property
    def change_pct(self) -> float:
        if self.pre_close and self.pre_close > 0:
            return round((self.price - self.pre_close) / self.pre_close * 100, 2)
        return 0.0

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "price": round(self.price, 3),
            "pre_close": round(self.pre_close, 3),
            "change_pct": self.change_pct,
        }


def _bare(code: str) -> str:
    """纯数字代码 (去后缀), A 股 6 位 / 港股 5 位。"""
    s = str(code or "").strip().upper()
    if "." in s:
        s = s.split(".", 1)[0]
    for pre in ("SH", "SZ", "BJ", "HK"):
        if s.startswith(pre) and s[len(pre):].isdigit():
            s = s[len(pre):]
            break
    return s


class QuoteProvider:
    """行情报价提供器 (带内存缓存)。"""

    def __init__(self, cache_ttl: float = 3.0, enable_live: bool = False):
        self._cache: Dict[str, Quote] = {}
        self._cache_ttl = cache_ttl
        self._enable_live = enable_live
        self._names: Dict[str, str] = {}

    # ------------------------------------------------------------------
    def get(self, code: str, force: bool = False) -> Optional[Quote]:
        """获取单只标的最新价。"""
        qmt_code = market_rules.normalize_qmt_code(code)
        cached = self._cache.get(qmt_code)
        if cached and not force and (time.time() - cached.ts) < self._cache_ttl:
            return cached

        quote = self._fetch(qmt_code)
        if quote is None and cached is not None:
            return cached  # 降级: 用上一次已知价
        if quote is not None:
            self._cache[qmt_code] = quote
        return quote

    def get_many(self, codes, force: bool = False) -> Dict[str, Quote]:
        return {c: q for c in codes if (q := self.get(c, force=force)) is not None}

    def set_manual(self, code: str, price: float) -> Quote:
        """手动置价 (无行情源时兜底)。"""
        qmt_code = market_rules.normalize_qmt_code(code)
        name = self._names.get(_bare(qmt_code), "")
        q = Quote(code=qmt_code, name=name, price=price, pre_close=price)
        self._cache[qmt_code] = q
        return q

    # ------------------------------------------------------------------
    def _fetch(self, qmt_code: str) -> Optional[Quote]:
        bare = _bare(qmt_code)
        name = self._lookup_name(bare)

        # 1) 实时快照
        rt = self._from_realtime(bare)
        if rt is not None:
            rt.code, rt.name = qmt_code, name or rt.name
            return rt

        # 2) 日线收盘
        daily = self._from_daily(bare, qmt_code)
        if daily is not None:
            daily.code, daily.name = qmt_code, name or daily.name
            return daily

        # 3) 实时源 (可选, 最佳努力)
        if self._enable_live:
            live = self._from_live(bare)
            if live is not None:
                live.code, live.name = qmt_code, name or live.name
                return live

        return None

    def _lookup_name(self, bare: str) -> str:
        if bare in self._names:
            return self._names[bare]
        try:
            with _session() as s:
                row = s.execute(
                    text("SELECT name FROM stocks WHERE code = :c OR code = :c2 LIMIT 1"),
                    {"c": bare, "c2": bare.zfill(6)},
                ).fetchone()
                name = row[0] if row else ""
        except Exception:
            name = ""
        self._names[bare] = name
        return name

    def _from_realtime(self, bare: str) -> Optional[Quote]:
        try:
            with _session() as s:
                row = s.execute(
                    text(
                        "SELECT price, change_pct FROM stock_realtime "
                        "WHERE code = :c ORDER BY timestamp DESC LIMIT 1"
                    ),
                    {"c": bare},
                ).fetchone()
        except Exception:
            return None
        if not row or not row[0]:
            return None
        price = float(row[0])
        chg = float(row[1] or 0)
        pre = price / (1 + chg / 100) if chg else price
        return Quote(code=bare, price=price, pre_close=pre)

    def _from_daily(self, bare: str, qmt_code: str) -> Optional[Quote]:
        board = market_rules.infer_board(qmt_code)
        if board == market_rules.Board.FUND:
            tables = ["etf_daily", "stock_daily"]
        elif board == market_rules.Board.BOND:
            tables = ["cb_daily", "stock_daily"]
        else:
            tables = ["stock_daily"]

        for tbl in tables:
            try:
                with _session() as s:
                    row = s.execute(
                        text(
                            f"SELECT close, pre_close FROM {tbl} "
                            "WHERE code = :c OR code = :c2 "
                            "ORDER BY trade_date DESC LIMIT 1"
                        ),
                        {"c": bare, "c2": bare.zfill(6)},
                    ).fetchone()
            except Exception:
                row = None
            if row and row[0]:
                close = float(row[0])
                pre = float(row[1]) if len(row) > 1 and row[1] else close
                return Quote(code=bare, price=close, pre_close=pre)
        return None

    def _from_live(self, bare: str) -> Optional[Quote]:
        try:
            import akshare as ak  # noqa

            df = ak.stock_zh_a_spot_em()
            hit = df[df["代码"] == bare.zfill(6)]
            if not hit.empty:
                price = float(hit.iloc[0]["最新价"])
                pct = float(hit.iloc[0].get("涨跌幅", 0) or 0)
                pre = price / (1 + pct / 100) if pct else price
                return Quote(code=bare, price=price, pre_close=pre)
        except Exception as e:  # noqa: BLE001
            logger.debug("live 报价失败 %s: %s", bare, e)
        return None


def _session():
    """延迟导入 get_session, 便于测试与无 DB 场景。"""
    from src.common.db import get_session

    return get_session(readonly=True)


@dataclass
class DayBar:
    """某交易日的日线 OHLC (用于按日回测式撮合)。"""
    code: str
    date: str
    name: str = ""
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    close: float = 0.0
    pre_close: float = 0.0

    @property
    def change_pct(self) -> float:
        if self.pre_close and self.pre_close > 0:
            return round((self.close - self.pre_close) / self.pre_close * 100, 2)
        return 0.0

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "date": self.date,
            "name": self.name,
            "open": round(self.open, 3),
            "high": round(self.high, 3),
            "low": round(self.low, 3),
            "close": round(self.close, 3),
            "pre_close": round(self.pre_close, 3),
            "change_pct": self.change_pct,
        }


class DayBarProvider:
    """按 (代码, 交易日) 从本地 PostgreSQL 读取日线 OHLC 与交易日历。

    支持 stock_daily / etf_daily / cb_daily。无 pre_close 列的表以「上一交易日收盘」推算。
    """

    def __init__(self, cache_ttl: float = 600.0):
        self._cache: Dict[str, DayBar] = {}
        self._name_cache: Dict[str, str] = {}

    def _tables(self, qmt_code: str):
        board = market_rules.infer_board(qmt_code)
        if board == market_rules.Board.FUND:
            return ["etf_daily", "stock_daily"]
        if board == market_rules.Board.BOND:
            return ["cb_daily", "stock_daily"]
        return ["stock_daily"]

    def _name(self, bare: str, qmt_code: str = "") -> str:
        key = qmt_code or bare
        if key in self._name_cache:
            return self._name_cache[key]
        name = ""
        try:
            with _session() as s:
                row = s.execute(
                    text(
                        "SELECT name FROM stocks WHERE code = :c OR code = :c2 OR code = :c3 LIMIT 1"
                    ),
                    {"c": bare, "c2": bare.zfill(6), "c3": qmt_code or bare},
                ).fetchone()
                name = row[0] if row else ""
                if not name and qmt_code:
                    # ETF 名称在 etf_info (代码为带后缀形式)
                    row = s.execute(
                        text("SELECT name FROM etf_info WHERE code = :c LIMIT 1"),
                        {"c": qmt_code},
                    ).fetchone()
                    name = row[0] if row else ""
        except Exception:
            name = ""
        self._name_cache[key] = name
        return name

    def get_bar(self, code: str, date_str: str) -> Optional[DayBar]:
        qmt_code = market_rules.normalize_qmt_code(code)
        key = f"{qmt_code}|{date_str}"
        if key in self._cache:
            return self._cache[key]

        bare = _bare(qmt_code)
        params = {"c": bare, "c2": bare.zfill(6), "c3": qmt_code}
        bar = None
        for tbl in self._tables(qmt_code):
            try:
                with _session() as s:
                    row = s.execute(
                        text(
                            f"SELECT open, high, low, close FROM {tbl} "
                            "WHERE code IN (:c, :c2, :c3) AND trade_date = :d LIMIT 1"
                        ),
                        {**params, "d": date_str},
                    ).fetchone()
                    if not row or row[3] is None:
                        continue
                    prev = s.execute(
                        text(
                            f"SELECT close FROM {tbl} "
                            "WHERE code IN (:c, :c2, :c3) AND trade_date < :d "
                            "ORDER BY trade_date DESC LIMIT 1"
                        ),
                        {**params, "d": date_str},
                    ).fetchone()
            except Exception:
                continue
            o, h, low_, c = (float(row[0] or 0), float(row[1] or 0),
                             float(row[2] or 0), float(row[3]))
            pre = float(prev[0]) if prev and prev[0] else o
            bar = DayBar(code=qmt_code, date=date_str, name=self._name(bare, qmt_code),
                         open=o, high=h, low=low_, close=c, pre_close=pre)
            break

        if bar is not None:
            self._cache[key] = bar
        return bar

    def latest_trading_day(self) -> Optional[str]:
        try:
            with _session() as s:
                row = s.execute(text("SELECT MAX(trade_date) FROM stock_daily")).fetchone()
            if row and row[0]:
                return row[0].isoformat()
        except Exception:
            pass
        return None

    def step_trading_day(self, date_str: str, direction: str) -> Optional[str]:
        """返回相邻交易日 (direction: prev/next), 以库中实际有数据的日为准。"""
        op, order = (("<", "DESC") if direction == "prev" else (">", "ASC"))
        try:
            with _session() as s:
                row = s.execute(
                    text(
                        f"SELECT trade_date FROM stock_daily WHERE trade_date {op} :d "
                        f"ORDER BY trade_date {order} LIMIT 1"
                    ),
                    {"d": date_str},
                ).fetchone()
            if row and row[0]:
                return row[0].isoformat()
        except Exception:
            pass
        return None

    def trading_days(self, start: str, end: str) -> list[str]:
        """区间内有数据的交易日列表 (升序)。"""
        try:
            with _session() as s:
                rows = s.execute(
                    text(
                        "SELECT DISTINCT trade_date FROM stock_daily "
                        "WHERE trade_date BETWEEN :s AND :e ORDER BY trade_date"
                    ),
                    {"s": start, "e": end},
                ).fetchall()
            return [r[0].isoformat() for r in rows if r[0]]
        except Exception:
            return []
