"""Tests for src/webui/paper_engine.py (自包含模拟盘引擎)"""
from datetime import date

import pytest

from src.webui.paper_engine import PaperAccount
from src.webui.quotes import DayBar, QuoteProvider
from src.webui.store import MemoryStore
from src.trading import market_rules


class NoBars:
    """禁用「按日回放」模式的日线源 (始终无当日日线 → 走实时报价撮合)。"""

    def get_bar(self, code, date_str):
        return None

    def latest_trading_day(self):
        return None

    def step_trading_day(self, date_str, direction):
        return None

    def trading_days(self, start, end):
        return []


class FakeBars:
    """可控日线源: bars[date][qmt_code] = DayBar。"""

    def __init__(self):
        self.bars = {}
        self.days = []

    def add(self, code, date_str, o, h, low, c, pre=0.0, name=""):
        qmt = market_rules.normalize_qmt_code(code)
        self.bars.setdefault(date_str, {})[qmt] = DayBar(
            code=qmt, date=date_str, name=name, open=o, high=h,
            low=low, close=c, pre_close=pre or o)
        if date_str not in self.days:
            self.days.append(date_str)
            self.days.sort()

    def get_bar(self, code, date_str):
        qmt = market_rules.normalize_qmt_code(code)
        return self.bars.get(date_str, {}).get(qmt)

    def latest_trading_day(self):
        return self.days[-1] if self.days else None

    def step_trading_day(self, date_str, direction):
        future = [d for d in self.days if (d > date_str if direction == "next" else d < date_str)]
        if not future:
            return None
        return min(future) if direction == "next" else max(future)

    def trading_days(self, start, end):
        return [d for d in self.days if start <= d <= end]


class FrontierBars(FakeBars):
    """跟盘测试: ``latest_trading_day`` 固定为 frontier, days 可含更晚日期供 step 用。"""

    def __init__(self, frontier: str):
        super().__init__()
        self._frontier = frontier

    def latest_trading_day(self):
        return self._frontier


@pytest.fixture
def store():
    return MemoryStore()


@pytest.fixture
def quotes():
    qp = QuoteProvider()
    qp.set_manual("600519.SH", 1800.0)   # 沪市主板
    qp.set_manual("000001.SZ", 12.0)     # 深市主板
    qp.set_manual("688981.SH", 55.0)     # 科创板
    qp.set_manual("00700.HK", 380.0)     # 港股通
    return qp


@pytest.fixture
def acct(store, quotes):
    # 回放模式 (模拟日 < 日历当天): 走实时报价撮合, 复用既有断言
    a = PaperAccount(name="test", initial_capital=1_000_000.0,
                     quote_provider=quotes, bar_provider=NoBars(), store=store)
    a.set_trade_date("2024-01-02")
    return a


class TestBuy:

    def test_market_buy_fills(self, acct):
        o = acct.place_order("600519.SH", "buy", 100, price_type="market")
        assert o["status"] == "filled"
        assert o["filled_qty"] == 100
        assert o["filled_price"] == 1800.0
        # A股买入费用: 佣金 max(180000*0.000115, 5)=20.7 + 过户费 180000*0.00002=3.6
        assert o["fees"] == pytest.approx(24.3, abs=0.01)
        snap = acct.snapshot(refresh=False)
        assert snap["summary"]["cash"] == pytest.approx(1_000_000 - 180024.3, abs=0.01)

    def test_limit_buy_pending_when_price_high(self, acct):
        # 限价买 1700 < 现价 1800 → 挂单
        o = acct.place_order("600519.SH", "buy", 100, price=1700.0, price_type="limit")
        assert o["status"] == "pending"

    def test_limit_buy_fills_when_price_ok(self, acct):
        o = acct.place_order("600519.SH", "buy", 100, price=1850.0, price_type="limit")
        assert o["status"] == "filled"

    def test_insufficient_cash(self, acct):
        o = acct.place_order("600519.SH", "buy", 1000, price_type="market")  # 180万 > 100万
        assert o["status"] == "failed"
        assert "资金不足" in o["note"]

    def test_star_min_quantity(self, acct):
        # 科创板不足200股自动抬升
        o = acct.place_order("688981.SH", "buy", 100, price_type="market")
        assert o["quantity"] == 200
        assert o["status"] == "filled"


class TestT1:

    def test_a_share_t1_frozen(self, acct):
        acct.place_order("600519.SH", "buy", 100, price_type="market")
        pos = acct.state["positions"]["600519.SH"]
        assert pos["volume"] == 100
        assert pos["available"] == 0  # T+1 当日不可卖

    def test_a_share_sell_same_day_rejected(self, acct):
        acct.place_order("600519.SH", "buy", 100, price_type="market")
        o = acct.place_order("600519.SH", "sell", 100, price_type="market")
        assert o["status"] == "failed"
        assert "可用不足" in o["note"]

    def test_hk_t0_available(self, acct):
        acct.place_order("00700.HK", "buy", 500, price_type="market")
        pos = acct.state["positions"]["00700.HK"]
        assert pos["available"] == 500  # 港股 T+0 当日可卖
        o = acct.place_order("00700.HK", "sell", 500, price_type="market")
        assert o["status"] == "filled"


class TestSell:

    def test_sell_after_rollover(self, acct, monkeypatch):
        acct.place_order("600519.SH", "buy", 100, price_type="market")
        # 模拟隔日: 修改 last_day 触发解冻
        acct.state["last_day"] = "2000-01-01"
        acct._rollover()
        assert acct.state["positions"]["600519.SH"]["available"] == 100
        o = acct.place_order("600519.SH", "sell", 100, price_type="market")
        assert o["status"] == "filled"
        assert "600519.SH" not in acct.state["positions"]  # 清仓


class TestCancel:

    def test_cancel_pending(self, acct):
        o = acct.place_order("600519.SH", "buy", 100, price=1700.0, price_type="limit")
        assert o["status"] == "pending"
        assert acct.cancel_order(o["order_id"]) is True
        assert acct.cancel_order(o["order_id"]) is False  # 已撤不能再撤

    def test_cannot_cancel_filled(self, acct):
        o = acct.place_order("600519.SH", "buy", 100, price_type="market")
        assert acct.cancel_order(o["order_id"]) is False


class TestSnapshotAndFees:

    def test_fee_estimate_a_share(self, acct):
        est = acct.estimate_fees("600519.SH", 1800.0, 100, "buy")
        assert est["total"] == pytest.approx(24.3, abs=0.01)
        assert "transfer_fee" in est["detail"]

    def test_fee_estimate_hk(self, acct):
        est = acct.estimate_fees("00700.HK", 380.0, 500, "buy")
        assert "trading_fee" in est["detail"]
        assert est["total"] > 0

    def test_sell_stamp_tax(self, acct):
        est = acct.estimate_fees("600519.SH", 1800.0, 100, "sell")
        # 卖出含印花税 千0.5 = 180000*0.0005 = 90
        assert est["detail"]["stamp_tax"] == pytest.approx(90.0, abs=0.01)

    def test_snapshot_structure(self, acct):
        acct.place_order("600519.SH", "buy", 100, price_type="market")
        snap = acct.snapshot(refresh=False)
        assert "summary" in snap and "positions" in snap
        assert snap["summary"]["total_asset"] > 0
        assert len(snap["positions"]) == 1


class TestReset:

    def test_reset(self, acct):
        acct.place_order("600519.SH", "buy", 100, price_type="market")
        acct.reset(500_000)
        assert acct.state["cash"] == 500_000
        assert acct.state["positions"] == {}
        assert acct.state["orders"] == []


class TestPersistence:

    def test_state_persisted(self, store, quotes):
        a1 = PaperAccount(name="persist", initial_capital=1_000_000,
                          quote_provider=quotes, bar_provider=NoBars(), store=store)
        a1.set_trade_date("2024-01-02")
        a1.place_order("600519.SH", "buy", 100, price_type="market")
        # 同一 store 重新加载 (模拟重启)
        a2 = PaperAccount(name="persist", quote_provider=quotes, bar_provider=NoBars(), store=store)
        assert "600519.SH" in a2.state["positions"]
        assert a2.state["positions"]["600519.SH"]["volume"] == 100

    def test_users_isolated(self, store, quotes):
        a = PaperAccount(name="alice", quote_provider=quotes, bar_provider=NoBars(), store=store)
        b = PaperAccount(name="bob", quote_provider=quotes, bar_provider=NoBars(), store=store)
        a.set_trade_date("2024-01-02")
        a.place_order("600519.SH", "buy", 100, price_type="market")
        assert "600519.SH" in a.state["positions"]
        assert b.state["positions"] == {}
        assert len(a.snapshot(refresh=False)["trades"]) == 1
        assert len(b.snapshot(refresh=False)["trades"]) == 0


class TestDateMode:
    """按交易日回放: 价格须落在当日 [最低, 最高] 区间内, T+1/T+0 以交易日为准。"""

    @pytest.fixture
    def bars(self):
        fb = FakeBars()
        # 600519 两个交易日
        fb.add("600519.SH", "2024-01-02", o=1700, h=1750, low=1680, c=1720, pre=1690)
        fb.add("600519.SH", "2024-01-03", o=1720, h=1800, low=1710, c=1780, pre=1720)
        # 港股通 (T+0)
        fb.add("00700.HK", "2024-01-02", o=380, h=390, low=375, c=385, pre=378)
        return fb

    @pytest.fixture
    def dacct(self, store, quotes, bars):
        a = PaperAccount(name="dmode", initial_capital=1_000_000.0,
                         quote_provider=quotes, bar_provider=bars, store=store)
        a.set_trade_date("2024-01-02")
        return a

    def test_buy_within_range_fills_at_price(self, dacct):
        o = dacct.place_order("600519.SH", "buy", 100, price=1700.0, price_type="limit")
        assert o["status"] == "filled"
        assert o["filled_price"] == 1700.0

    def test_buy_price_above_high_pending(self, dacct):
        o = dacct.place_order("600519.SH", "buy", 100, price=1760.0, price_type="limit")
        assert o["status"] == "pending"
        assert "区间" in o["note"]

    def test_buy_price_below_low_pending(self, dacct):
        o = dacct.place_order("600519.SH", "buy", 100, price=1600.0, price_type="limit")
        assert o["status"] == "pending"

    def test_market_buy_fills_at_close(self, dacct):
        o = dacct.place_order("600519.SH", "buy", 100, price_type="market")
        assert o["status"] == "filled"
        assert o["filled_price"] == 1720.0  # 当日收盘

    def test_no_position_cannot_sell(self, dacct):
        o = dacct.place_order("600519.SH", "sell", 100, price=1700.0, price_type="limit")
        assert o["status"] == "failed"
        assert "无持仓" in o["note"]

    def test_a_share_t1_then_next_day_sellable(self, dacct):
        dacct.place_order("600519.SH", "buy", 100, price=1700.0, price_type="limit")
        assert dacct.state["positions"]["600519.SH"]["available"] == 0
        # 同日卖出被拒
        o = dacct.place_order("600519.SH", "sell", 100, price=1720.0, price_type="limit")
        assert o["status"] == "failed"
        # 切换到次日 → 解冻可卖
        dacct.set_trade_date("2024-01-03")
        assert dacct.state["positions"]["600519.SH"]["available"] == 100
        o2 = dacct.place_order("600519.SH", "sell", 100, price=1780.0, price_type="limit")
        assert o2["status"] == "filled"
        assert o2["filled_price"] == 1780.0

    def test_hk_t0_same_day_sell(self, dacct):
        dacct.place_order("00700.HK", "buy", 500, price=380.0, price_type="limit")
        assert dacct.state["positions"]["00700.HK"]["available"] == 500
        o = dacct.place_order("00700.HK", "sell", 500, price=385.0, price_type="limit")
        assert o["status"] == "filled"

    def test_pending_fills_after_date_switch(self, dacct):
        # 1760 超出 1/2 当日区间 → 挂单; 切到 1/3 (区间含1760) → 成交
        o = dacct.place_order("600519.SH", "buy", 100, price=1760.0, price_type="limit")
        assert o["status"] == "pending"
        dacct.set_trade_date("2024-01-03")
        oid = o["order_id"]
        filled = [x for x in dacct.state["orders"] if x["order_id"] == oid][0]
        assert filled["status"] == "filled"
        assert filled["filled_price"] == 1760.0

    def test_valuation_uses_day_close(self, dacct):
        dacct.place_order("600519.SH", "buy", 100, price=1700.0, price_type="limit")
        snap = dacct.snapshot(refresh=False)
        pos = snap["positions"][0]
        assert pos["price"] == 1720.0  # 1/2 收盘估值
        assert pos["t0"] is False

    def test_snapshot_has_trade_date(self, dacct):
        snap = dacct.snapshot(refresh=False)
        assert snap["trade_date"] == "2024-01-02"


class TestCapital:

    def test_increase_capital(self, acct):
        acct.set_capital(1_500_000.0)
        snap = acct.snapshot(refresh=False)
        assert snap["summary"]["cash"] == 1_500_000.0
        # 出入金不计入盈亏
        assert snap["summary"]["total_pnl"] == 0.0

    def test_decrease_capital(self, acct):
        acct.set_capital(200_000.0)
        assert acct.snapshot(refresh=False)["summary"]["cash"] == 200_000.0

    def test_capital_cannot_be_negative(self, acct):
        with pytest.raises(ValueError):
            acct.set_capital(-1.0)

    def test_pnl_unaffected_by_deposit(self, acct):
        acct.place_order("600519.SH", "buy", 100, price_type="market")  # 现价=成本, 浮盈0
        pnl_before = acct.snapshot(refresh=False)["summary"]["total_pnl"]
        cash_now = acct.state["cash"]
        acct.set_capital(cash_now + 300_000.0)
        pnl_after = acct.snapshot(refresh=False)["summary"]["total_pnl"]
        assert pnl_after == pytest.approx(pnl_before, abs=0.01)


class TestDeleteTrade:

    def test_delete_own_trade(self, acct):
        o = acct.place_order("600519.SH", "buy", 100, price_type="market")
        trades = acct.snapshot(refresh=False)["trades"]
        assert len(trades) == 1
        tid = trades[0]["trade_id"]
        assert acct.delete_trade(tid) is True
        assert len(acct.snapshot(refresh=False)["trades"]) == 0
        assert acct.delete_trade(tid) is False  # 已删除
        assert o["status"] == "filled"

    def test_delete_is_per_user(self, store, quotes):
        a = PaperAccount(name="alice", quote_provider=quotes, bar_provider=NoBars(), store=store)
        b = PaperAccount(name="bob", quote_provider=quotes, bar_provider=NoBars(), store=store)
        a.set_trade_date("2024-01-02")
        a.place_order("600519.SH", "buy", 100, price_type="market")
        tid = a.snapshot(refresh=False)["trades"][0]["trade_id"]
        # bob 删除 alice 的 trade_id 无效
        assert b.delete_trade(tid) is False
        assert len(a.snapshot(refresh=False)["trades"]) == 1


class TestLiveDeferral:

    @pytest.fixture
    def live_bars(self):
        fb = FrontierBars("2026-07-10")
        fb.add("688795.SH", "2026-07-10", o=690, h=720, low=680, c=701, pre=680, name="摩尔线程")
        fb.add("600519.SH", "2026-07-11", o=1700, h=1750, low=1680, c=1720)  # 下一交易日 (日历)
        return fb

    @pytest.fixture
    def live_bars_with_fill(self, live_bars):
        live_bars.add("688795.SH", "2026-07-11", o=700, h=710, low=695, c=705, pre=701)
        return live_bars

    def test_manual_buy_pending_at_frontier(self, store, quotes, live_bars, monkeypatch):
        """跟盘日 (模拟日=日历当天) 任意时刻下单均次日生效。"""
        monkeypatch.setattr("src.webui.paper_engine._today_str", lambda: "2026-07-10")
        acct = PaperAccount(
            name="live", initial_capital=5_000_000.0,
            quote_provider=quotes, bar_provider=live_bars, store=store,
        )
        acct.set_trade_date("2026-07-10")
        o = acct.place_order("688795.SH", "buy", 100, price=701.01, price_type="limit")
        assert o["status"] == "pending"
        assert o["effective_date"] == "2026-07-11"
        assert "预约" in o["note"]

    def test_replay_day_fills_same_day_in_range(self, store, quotes, monkeypatch):
        """历史回放 (模拟日 < 日历当天) 可在当日线价区间内即时成交。"""
        monkeypatch.setattr("src.webui.paper_engine._today_str", lambda: "2026-07-12")
        fb = FakeBars()
        fb.add("688795.SH", "2026-07-10", o=690, h=720, low=680, c=701, pre=680)
        fb.add("688795.SH", "2026-07-11", o=700, h=720, low=690, c=710)  # 库内最新日 7/11
        acct = PaperAccount(
            name="replay", initial_capital=5_000_000.0,
            quote_provider=quotes, bar_provider=fb, store=store,
        )
        acct.set_trade_date("2026-07-10")
        o = acct.place_order("688795.SH", "buy", 100, price=701.01, price_type="limit")
        assert o["status"] == "filled"
        assert o.get("effective_date") is None

    def test_deferred_buy_fills_when_next_low_below_bid(self, store, quotes, live_bars_with_fill, monkeypatch):
        monkeypatch.setattr("src.webui.paper_engine._today_str", lambda: "2026-07-10")
        acct = PaperAccount(
            name="live2", initial_capital=5_000_000.0,
            quote_provider=quotes, bar_provider=live_bars_with_fill, store=store,
        )
        acct.set_trade_date("2026-07-10")
        o = acct.place_order("688795.SH", "buy", 100, price=701.01, price_type="limit")
        assert o["status"] == "pending"
        acct.set_trade_date("2026-07-11")
        filled = [x for x in acct.state["orders"] if x["order_id"] == o["order_id"]][0]
        assert filled["status"] == "filled"
        assert filled["filled_price"] == 701.01

    def test_deferred_waits_for_kline_when_bar_missing(self, store, quotes, monkeypatch):
        monkeypatch.setattr("src.webui.paper_engine._today_str", lambda: "2026-07-10")
        fb = FrontierBars("2026-07-10")
        fb.add("688795.SH", "2026-07-10", o=690, h=720, low=680, c=701, pre=680)
        fb.add("600519.SH", "2026-07-11", o=1700, h=1750, low=1680, c=1720)  # 日历有 7/11, 688795 无 K
        acct = PaperAccount(
            name="live3", initial_capital=5_000_000.0,
            quote_provider=quotes, bar_provider=fb, store=store,
        )
        acct.set_trade_date("2026-07-10")
        o = acct.place_order("688795.SH", "buy", 100, price=701.01, price_type="limit")
        acct.set_trade_date("2026-07-11")
        pending = [x for x in acct.state["orders"] if x["order_id"] == o["order_id"]][0]
        assert pending["status"] == "pending"
        assert "日K线" in pending["note"]
