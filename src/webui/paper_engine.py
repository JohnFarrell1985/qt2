"""自包含模拟盘 (paper trading) 撮合与账户引擎

**与 QMT 终端/MCP 无任何依赖** —— 不 import xtquant, 不调用 QMTTrader。
本地模拟 A 股 / 港股通交易, 并支持「按交易日回放」的手动回测:  - 华泰证券费率 (A 股佣金万1.15 最低5元 + 卖出印花税千0.5 + 沪市过户费万0.2;
    港股通佣金万3 最低5港元 + 印花税千1 + 交易费/征费/交收费), 复用 ``src/backtest/fees.py``
  - 交易日驱动 (state.trade_date): 可切换到任意有数据的历史交易日, 下单价格须落在
    当日 [最低价, 最高价] 区间内 (数据取自本地 PostgreSQL 日线), 否则挂单待后续交易日撮合。
    **跟盘模式** (模拟日 ≥ 日历当天): 当日下单不成交, ``effective_date`` 设为
    **下单日的下一交易日** (如 7/10→7/13, 跳过周末), 同步日 K 后按该日
    「最低价 < 挂单价」撮合; **历史回放** (模拟日 < 日历当天) 则可在当日线
    价区间内补录成交。
  - T+1 / T+0 以 **交易日** 为准: A 股 T+1 (当日买入次日可卖); 港股通、可转债、跨境 ETF 支持 T+0。
  - 卖出校验: 无持仓不可卖; 可用不足不可卖。
  - 多用户: 每个账户按用户名隔离, 状态与成交流水持久化到独立的 ``paper_*`` 表 (见 ``store.py``);
    绝不修改行情等真实业务表。
  - 用户可随时调整模拟资金 (存/取, 结果不得为负); 可逐条删除自己的成交记录。

供 FastAPI 服务层调用。
"""
from __future__ import annotations

import threading
from datetime import date, datetime
from typing import Any, Dict, Optional

from src.backtest import fees as fee_mod
from src.common.config import settings
from src.common.logger import get_logger
from src.trading import market_rules
from src.webui.quotes import DayBarProvider, QuoteProvider, _bare
from src.webui.store import PaperStore

logger = get_logger(__name__)


def _is_t0(qmt_code: str) -> bool:
    """该标的是否支持 T+0 (港股通 / 可转债 / 跨境 ETF)。"""
    try:
        from src.common.asset_types import AssetType, infer_asset_type

        t = infer_asset_type(qmt_code)
        return t in (
            AssetType.HK_CONNECT,
            AssetType.ETF_CROSS_BORDER,
            AssetType.CONVERTIBLE_BOND,
        )
    except Exception:  # noqa: BLE001
        return fee_mod.detect_market(_bare(qmt_code)) == "HK"


def _today_str() -> str:
    return date.today().isoformat()


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class PaperAccount:
    """单个用户的模拟盘账户 (状态与成交流水持久化到 ``paper_*`` 表)。"""

    def __init__(
        self,
        name: str = "default",
        initial_capital: float = 1_000_000.0,
        quote_provider: Optional[QuoteProvider] = None,
        bar_provider: Optional[DayBarProvider] = None,
        store=None,
    ):
        self.name = name                       # 用户名
        self.quotes = quote_provider or QuoteProvider()
        self.bars = bar_provider if bar_provider is not None else DayBarProvider()
        self.store = store if store is not None else PaperStore()
        self._lock = threading.RLock()
        self.state = self._load(initial_capital)
        self.state.setdefault("trade_date", _today_str())

    # ------------------------------------------------------------------
    # 持久化 (DB, 按用户名隔离)
    # ------------------------------------------------------------------
    def _default_state(self, initial_capital: float) -> Dict[str, Any]:
        return {
            "name": self.name,
            "initial_capital": initial_capital,
            "cash": initial_capital,
            "created_at": _now_str(),
            "trade_date": _today_str(),   # 当前模拟交易日 (可切换)
            "last_day": _today_str(),
            "day_start_asset": initial_capital,
            "seq": 0,
            "positions": {},   # qmt_code -> position dict
            "orders": [],      # 委托 (倒序展示); 成交流水存 paper_trades 表
        }

    def _load(self, initial_capital: float) -> Dict[str, Any]:
        try:
            st = self.store.load_state(self.name)
        except Exception as e:  # noqa: BLE001
            logger.warning("模拟盘状态读取失败, 重建: %s", e)
            st = None
        if st is None:
            st = self._default_state(initial_capital)
            try:
                self.store.save_state(self.name, st)
            except Exception as e:  # noqa: BLE001
                logger.warning("模拟盘状态初始化落库失败: %s", e)
        st.pop("trades", None)   # 历史遗留字段, 成交现由 paper_trades 表管理
        return st

    def _save(self) -> None:
        self.store.save_state(self.name, self.state)

    def _next_seq(self) -> int:
        self.state["seq"] += 1
        return self.state["seq"]

    # ------------------------------------------------------------------
    # 费用
    # ------------------------------------------------------------------
    @staticmethod
    def _calc_fees(bare: str, price: float, qty: int, direction: str):
        """返回 (总费用, 明细dict)。华泰 A 股 / 港股通费率。"""
        market = fee_mod.detect_market(bare)
        if market == "HK":
            cfg = fee_mod.HKFeeConfig()
            tf = (fee_mod.calc_hk_buy_fees if direction == "buy"
                  else fee_mod.calc_hk_sell_fees)(price, qty, bare, cfg)
            detail = {
                "commission": tf.commission,
                "stamp_tax": tf.stamp_tax,
                "trading_fee": tf.trading_fee,
                "transaction_levy": tf.transaction_levy,
                "frc_levy": tf.frc_levy,
                "settlement_fee": tf.settlement_fee,
            }
            return round(tf.total, 2), detail

        cfg = fee_mod.FeeConfig.from_settings(settings.backtest)
        tf = (fee_mod.calc_buy_fees if direction == "buy"
              else fee_mod.calc_sell_fees)(price, qty, bare, cfg)
        detail = {
            "commission": tf.commission,
            "stamp_tax": tf.stamp_tax,
            "transfer_fee": tf.transfer_fee,
        }
        return round(tf.total, 2), detail

    def estimate_fees(self, code: str, price: float, qty: int, direction: str) -> Dict[str, Any]:
        bare = _bare(market_rules.normalize_qmt_code(code))
        total, detail = self._calc_fees(bare, price, int(qty), direction)
        return {"total": total, "detail": detail}

    # ------------------------------------------------------------------
    # 交易日 / 换日滚动 (T+1 解冻)
    # ------------------------------------------------------------------
    def _cur_day(self) -> str:
        return self.state.get("trade_date") or _today_str()

    def _stamp(self) -> str:
        """以模拟交易日 + 真实时分秒 作为委托/成交时间戳。"""
        return f"{self._cur_day()} {datetime.now().strftime('%H:%M:%S')}"

    def _rollover(self) -> None:
        """当模拟交易日发生变化时: 解冻所有隔日持仓 (T+1), 重置当日起始资产。"""
        cur = self._cur_day()
        if self.state.get("last_day") != cur:
            for pos in self.state["positions"].values():
                pos["available"] = pos["volume"]
            self.state["last_day"] = cur
            self.state["day_start_asset"] = self._total_asset()

    def set_trade_date(self, date_str: str) -> Dict[str, Any]:
        """切换当前模拟交易日 (触发 T+1 解冻并对挂单重新撮合)。"""
        with self._lock:
            self.state["trade_date"] = str(date_str)
            self._rollover()
            self.match_pending()
            self._save()
            return self.snapshot(refresh=False)

    def settle_to_latest(self) -> Dict[str, Any]:
        """将模拟日推进到库内最新交易日, 逐步撮合挂单并刷新估值。"""
        try:
            latest = self.bars.latest_trading_day()
        except Exception:  # noqa: BLE001
            latest = None
        steps = 0
        while latest and self._cur_day() < latest:
            nxt = self.bars.step_trading_day(self._cur_day(), "next")
            if not nxt:
                break
            self.set_trade_date(nxt)
            steps += 1
        filled = self.match_pending()
        snap = self.snapshot(refresh=False)
        pending = sum(1 for o in self.state["orders"] if o.get("status") == "pending")
        return {
            "trade_date": self._cur_day(),
            "latest": latest,
            "steps": steps,
            "filled": filled,
            "pending_orders": pending,
            "summary": snap.get("summary"),
        }

    def _is_replay_mode(self) -> bool:
        """历史回放: 模拟日严格早于日历当天, 允许在当日线价区间内补录成交。"""
        return self._cur_day() < _today_str()

    def _should_defer_to_next_day(self) -> bool:
        """跟盘 (模拟日 ≥ 日历当天): 新委托一律次日生效, 等日 K 同步后再撮合。"""
        return not self._is_replay_mode()

    def _defer_effective_date(self) -> Optional[str]:
        try:
            return self.bars.step_trading_day(self._cur_day(), "next")
        except Exception:  # noqa: BLE001
            return None

    def _next_effective_date_if_needed(self, effective_date: Optional[str]) -> Optional[str]:
        if effective_date is not None:
            return effective_date
        if not self._should_defer_to_next_day():
            return None
        return self._defer_effective_date()

    def _day_bar(self, qmt_code: str):
        d = self.state.get("trade_date")
        if not d:
            return None
        try:
            return self.bars.get_bar(qmt_code, d)
        except Exception:  # noqa: BLE001
            return None

    def _bar_for_match(self, qmt_code: str, order: Dict[str, Any]):
        """撮合用 K 线。

        预约/选股买入 (``effective_date`` 已设定): 生效日已到后 **只取生效日** K 线,
        按该日最低价与挂单价比较 (例: 7/10 下单 → effective=7/13 → 查 7/13 的 low)。
        其余委托仍取当前模拟日 K 线。
        """
        eff = order.get("effective_date")
        if (
            order.get("direction") == "buy"
            and eff
            and self._cur_day() >= eff
        ):
            try:
                return self.bars.get_bar(qmt_code, eff)
            except Exception:  # noqa: BLE001
                return None
        return self._day_bar(qmt_code)

    def _price_info(self, qmt_code: str):
        """返回 (估值价, 涨跌幅%): 优先当日日线收盘, 退化到实时报价, 再退化到成本价。"""
        bar = self._day_bar(qmt_code)
        if bar is not None and bar.close > 0:
            return bar.close, bar.change_pct
        quote = self.quotes.get(qmt_code)
        if quote and quote.price > 0:
            return quote.price, quote.change_pct
        pos = self.state["positions"].get(qmt_code)
        return (pos["avg_cost"] if pos else 0.0), 0.0

    # ------------------------------------------------------------------
    # 撮合
    # ------------------------------------------------------------------
    def place_order(
        self,
        code: str,
        direction: str,
        quantity: int,
        price: float = 0.0,
        price_type: str = "limit",
        effective_date: Optional[str] = None,
        origin: str = "manual",
    ) -> Dict[str, Any]:
        """下单。direction: buy/sell; price_type: limit/market。

        **跟盘** (模拟日 ≥ 日历当天): ``effective_date`` = 下单日的 **下一交易日**,
        同步日 K 后按该日「最低价 < 挂单价」撮合 (非当前模拟日)。
        **回放** (模拟日 < 日历当天): 限价单可在当日线价区间 [最低, 最高] 内即时成交。
        ``origin="pick"`` 的买入在生效日按「最低价 < 挂单价」规则成交。
        """
        with self._lock:
            self._rollover()
            qmt_code = market_rules.normalize_qmt_code(code)
            direction = direction.lower()
            price_type = (price_type or "limit").lower()
            qty = market_rules.normalize_quantity(qmt_code, quantity, direction)

            order = {
                "order_id": f"P{self._next_seq():06d}",
                "code": qmt_code,
                "name": "",
                "direction": direction,
                "price_type": price_type,
                "price": round(float(price or 0), 3),
                "quantity": qty,
                "filled_qty": 0,
                "filled_price": 0.0,
                "fees": 0.0,
                "status": "pending",
                "note": "",
                "origin": origin,
                "effective_date": None,
                "trade_date": self._cur_day(),
                "created_at": self._stamp(),
            }

            eff = self._next_effective_date_if_needed(effective_date)
            if eff:
                order["effective_date"] = str(eff)

            if qty <= 0:
                order["status"] = "failed"
                order["note"] = "数量无效"
                self.state["orders"].insert(0, order)
                self._save()
                return order

            bar = self._day_bar(qmt_code)
            quote = self.quotes.get(qmt_code)
            order["name"] = (bar.name if bar and bar.name else
                             (quote.name if quote else ""))

            # 卖出前置校验: 必须持有 + 可用数量足够 (T+1)
            if direction == "sell":
                pos = self.state["positions"].get(qmt_code)
                if pos is None or pos["volume"] <= 0:
                    order["status"] = "failed"
                    order["note"] = "无持仓, 不可卖出"
                    self.state["orders"].insert(0, order)
                    self._save()
                    return order
                avail = pos["available"]
                if avail < qty:
                    order["status"] = "failed"
                    order["note"] = f"可用不足 (可用{avail}, T+1未解冻)"
                    self.state["orders"].insert(0, order)
                    self._save()
                    return order

            self._match_one(order, force=False)
            self.state["orders"].insert(0, order)
            self._save()
            return order

    def place_picks(self, items, screen_date: Optional[str] = None) -> Dict[str, Any]:
        """批量下达「选股挂单」: 于 ``screen_date`` 的下一交易日生效的限价买入。

        ``items``: [{code, price, quantity}]; 到达生效交易日后, 若当日最低价 < 挂单价则成交。
        """
        with self._lock:
            screen_date = screen_date or self._cur_day()
            try:
                eff = self.bars.step_trading_day(screen_date, "next")
            except Exception:  # noqa: BLE001
                eff = None
            placed = []
            for it in items or []:
                code = it.get("code")
                price = float(it.get("price") or 0)
                qty = int(it.get("quantity") or 0)
                if not code or price <= 0 or qty <= 0:
                    placed.append({"code": code, "status": "failed", "note": "参数无效"})
                    continue
                order = self.place_order(
                    code=code, direction="buy", quantity=qty, price=price,
                    price_type="limit", effective_date=eff, origin="pick",
                )
                placed.append(order)
            return {"effective_date": eff, "orders": placed}

    def _match_one(self, order: Dict[str, Any], force: bool = False) -> None:
        """撮合单笔委托。有当日日线时按 [最低,最高] 区间校验并成交, 否则用实时报价撮合。"""
        qmt_code = order["code"]
        direction = order["direction"]
        qty = order["quantity"]

        # 预约单: 未到生效交易日前保持挂单
        eff = order.get("effective_date")
        if eff and self._cur_day() < eff:
            order["note"] = f"预约 {eff} 撮合 (该日最低<挂单价则成交)"
            return

        bar = self._bar_for_match(qmt_code, order)

        if bar is not None and bar.high > 0 and bar.low > 0:
            if order["price_type"] == "market":
                fill_price = bar.close
            else:
                price = order["price"]
                if price <= 0:
                    order["status"] = "failed"
                    order["note"] = "限价单价格无效"
                    return
                is_pick_buy = order.get("origin") == "pick" and direction == "buy"
                deferred_buy = (
                    direction == "buy"
                    and eff
                    and self._cur_day() >= eff
                )
                if is_pick_buy and not eff:
                    order["note"] = "选股挂单缺少生效日"
                    return
                if deferred_buy or is_pick_buy:
                    # 下一交易日买入: 生效日最低价 < 挂单价 → 成交价 = min(挂单价, 当日最高)
                    if bar.low < price - 1e-9:
                        fill_price = min(price, bar.high)
                    else:
                        order["note"] = (
                            f"{eff}最低{bar.low:g}≥挂单价{price:g}, 继续挂单"
                        )
                        return
                elif price < bar.low - 1e-6 or price > bar.high + 1e-6:
                    order["note"] = (
                        f"价格超出当日区间[{bar.low:g}~{bar.high:g}], 挂单待撮合"
                    )
                    return  # 保持 pending, 切换交易日后可再撮合
                else:
                    fill_price = price
            self._execute(order, qmt_code, direction, qty, fill_price)
        elif eff and self._cur_day() >= eff:
            order["note"] = f"待 {eff} 日K线, 同步后按该日最低价判定"
            return
        elif order.get("origin") == "pick":
            order["note"] = "选股挂单待生效日撮合"
            return
        elif self._should_defer_to_next_day():
            order["note"] = "待下一交易日撮合"
            return
        else:
            quote = self.quotes.get(qmt_code, force=force)
            self._try_fill(order, quote)

    def _try_fill(self, order: Dict[str, Any], quote) -> None:
        """尝试成交单笔委托。未成交则保持 pending。"""
        qmt_code = order["code"]
        direction = order["direction"]
        qty = order["quantity"]
        limit_price = order["price"]
        market_price = quote.price if quote else 0.0

        # 决定成交价
        if order["price_type"] == "market":
            if market_price <= 0:
                order["status"] = "pending"
                order["note"] = "无行情, 市价挂起"
                return
            fill_price = market_price
        else:  # 限价
            if limit_price <= 0:
                order["status"] = "failed"
                order["note"] = "限价单价格无效"
                return
            if market_price <= 0:
                order["note"] = "无行情, 挂单待撮合"
                return
            if direction == "buy" and market_price > limit_price:
                order["note"] = "价格未到, 挂单"
                return
            if direction == "sell" and market_price < limit_price:
                order["note"] = "价格未到, 挂单"
                return
            fill_price = min(limit_price, market_price) if direction == "buy" else max(limit_price, market_price)

        self._execute(order, qmt_code, direction, qty, fill_price)

    def _execute(self, order, qmt_code, direction, qty, fill_price) -> None:
        bare = _bare(qmt_code)
        amount = fill_price * qty
        total_fee, detail = self._calc_fees(bare, fill_price, qty, direction)

        if direction == "buy":
            total_cost = amount + total_fee
            if self.state["cash"] < total_cost:
                order["status"] = "failed"
                order["note"] = f"资金不足 (需{total_cost:.2f})"
                return
            self.state["cash"] = round(self.state["cash"] - total_cost, 2)
            pos = self.state["positions"].get(qmt_code)
            t0 = _is_t0(qmt_code)
            if pos is None:
                pos = {
                    "code": qmt_code, "name": order["name"], "volume": 0,
                    "available": 0, "cost_amount": 0.0, "avg_cost": 0.0,
                    "buy_date": self._cur_day(),
                }
                self.state["positions"][qmt_code] = pos
            pos["volume"] += qty
            pos["cost_amount"] = round(pos["cost_amount"] + total_cost, 2)
            pos["avg_cost"] = round(pos["cost_amount"] / pos["volume"], 4)
            pos["buy_date"] = self._cur_day()
            if t0:
                pos["available"] += qty  # 港股通/可转债/跨境ETF T+0 当日可卖
            # A 股当日买入不解冻 (available 不变, T+1)
        else:  # sell
            pos = self.state["positions"].get(qmt_code)
            if pos is None or pos["available"] < qty:
                order["status"] = "failed"
                order["note"] = "可用不足"
                return
            proceeds = amount - total_fee
            self.state["cash"] = round(self.state["cash"] + proceeds, 2)
            cost_out = round(pos["avg_cost"] * qty, 2)
            pos["volume"] -= qty
            pos["available"] -= qty
            pos["cost_amount"] = round(max(pos["cost_amount"] - cost_out, 0.0), 2)
            if pos["volume"] <= 0:
                self.state["positions"].pop(qmt_code, None)

        order["status"] = "filled"
        order["filled_qty"] = qty
        order["filled_price"] = round(fill_price, 3)
        order["fees"] = total_fee
        order["note"] = "已成交"

        trade = {
            "trade_id": f"T{self._next_seq():06d}",
            "order_id": order["order_id"],
            "code": qmt_code,
            "name": order["name"],
            "direction": direction,
            "price": round(fill_price, 3),
            "quantity": qty,
            "amount": round(amount, 2),
            "fees": total_fee,
            "fee_detail": detail,
            "trade_date": self._cur_day(),
            "ts": self._stamp(),
        }
        self.store.add_trade(self.name, trade)

    def cancel_order(self, order_id: str) -> bool:
        with self._lock:
            for o in self.state["orders"]:
                if o["order_id"] == order_id and o["status"] == "pending":
                    o["status"] = "cancelled"
                    o["note"] = "已撤单"
                    self._save()
                    return True
            return False

    def match_pending(self) -> int:
        """重新撮合所有挂单 (行情/交易日变化后调用)。返回本次成交数。

        卖出挂单需重新校验可用数量 (换日解冻后才可能成交)。
        """
        with self._lock:
            filled = 0
            for o in self.state["orders"]:
                if o["status"] != "pending":
                    continue
                if o["direction"] == "sell":
                    pos = self.state["positions"].get(o["code"])
                    if pos is None or pos["available"] < o["quantity"]:
                        continue
                self._match_one(o, force=True)
                if o["status"] == "filled":
                    filled += 1
            if filled:
                self._save()
            return filled

    # ------------------------------------------------------------------
    # 估值 / 快照
    # ------------------------------------------------------------------
    def _market_value(self) -> float:
        mv = 0.0
        for qmt_code, pos in self.state["positions"].items():
            price, _ = self._price_info(qmt_code)
            if price <= 0:
                price = pos["avg_cost"]
            mv += price * pos["volume"]
        return round(mv, 2)

    def _total_asset(self) -> float:
        return round(self.state["cash"] + self._market_value(), 2)

    def snapshot(self, refresh: bool = True) -> Dict[str, Any]:
        """账户全景快照 (含实时估值)。"""
        with self._lock:
            self._rollover()
            if refresh:
                self.match_pending()

            positions = []
            market_value = 0.0
            total_float_pnl = 0.0
            for qmt_code, pos in self.state["positions"].items():
                price, change_pct = self._price_info(qmt_code)
                if price <= 0:
                    price = pos["avg_cost"]
                mv = round(price * pos["volume"], 2)
                float_pnl = round(mv - pos["cost_amount"], 2)
                pnl_pct = round(float_pnl / pos["cost_amount"] * 100, 2) if pos["cost_amount"] > 0 else 0.0
                market_value += mv
                total_float_pnl += float_pnl
                positions.append({
                    "code": qmt_code,
                    "name": pos.get("name") or "",
                    "volume": pos["volume"],
                    "available": pos["available"],
                    "frozen": pos["volume"] - pos["available"],
                    "avg_cost": pos["avg_cost"],
                    "price": round(price, 3),
                    "market_value": mv,
                    "float_pnl": float_pnl,
                    "pnl_pct": pnl_pct,
                    "change_pct": change_pct,
                    "t0": _is_t0(qmt_code),
                })

            market_value = round(market_value, 2)
            cash = round(self.state["cash"], 2)
            total_asset = round(cash + market_value, 2)
            init_cap = self.state["initial_capital"]
            day_start = self.state.get("day_start_asset", init_cap)

            return {
                "account": self.name,
                "trade_date": self._cur_day(),
                "summary": {
                    "total_asset": total_asset,
                    "cash": cash,
                    "available_cash": cash,
                    "market_value": market_value,
                    "float_pnl": round(total_float_pnl, 2),
                    "total_pnl": round(total_asset - init_cap, 2),
                    "total_pnl_pct": round((total_asset - init_cap) / init_cap * 100, 2) if init_cap else 0.0,
                    "today_pnl": round(total_asset - day_start, 2),
                    "today_pnl_pct": round((total_asset - day_start) / day_start * 100, 2) if day_start else 0.0,
                    "initial_capital": init_cap,
                },
                "positions": sorted(positions, key=lambda p: -p["market_value"]),
                "orders": self.state["orders"][:100],
                "trades": self.store.list_trades(self.name, 100),
            }

    # ------------------------------------------------------------------
    # 资金调整 / 成交记录删除
    # ------------------------------------------------------------------
    def set_capital(self, new_cash: float) -> Dict[str, Any]:
        """调整模拟资金 (存/取): 将可用现金设为 ``new_cash`` (不得为负)。

        视为出入金 —— 同步平移 ``initial_capital`` 与当日起始资产, 使盈亏口径不受出入金影响。
        """
        with self._lock:
            new_cash = round(float(new_cash), 2)
            if new_cash < 0:
                raise ValueError("模拟资金不能为负")
            delta = round(new_cash - self.state["cash"], 2)
            self.state["cash"] = new_cash
            self.state["initial_capital"] = round(self.state.get("initial_capital", 0.0) + delta, 2)
            self.state["day_start_asset"] = round(self.state.get("day_start_asset", 0.0) + delta, 2)
            self._save()
            return self.snapshot(refresh=False)

    def delete_trade(self, trade_id: str) -> bool:
        """删除本用户的一条成交记录 (仅删记录, 不回滚已产生的资金/持仓变动)。"""
        with self._lock:
            return self.store.delete_trade(self.name, trade_id)

    def reset(self, initial_capital: float | None = None) -> None:
        with self._lock:
            cap = initial_capital if initial_capital is not None else self.state["initial_capital"]
            keep_date = self.state.get("trade_date", _today_str())
            self.state = self._default_state(cap)
            self.state["trade_date"] = keep_date
            self.state["last_day"] = keep_date
            self.store.clear_trades(self.name)
            self._save()
