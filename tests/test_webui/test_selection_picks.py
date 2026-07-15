"""选股/选基服务 + 选股挂单 (次日撮合) 测试。"""
from datetime import date

import pandas as pd
import pytest

from src.common.config import MaFilterConfig, RankConfig, settings
from src.trading import market_rules
from src.webui.paper_engine import PaperAccount
from src.webui.quotes import DayBar, QuoteProvider
from src.webui.store import MemoryStore


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


@pytest.fixture
def store():
    return MemoryStore()


@pytest.fixture
def quotes():
    qp = QuoteProvider()
    qp.set_manual("600519.SH", 1800.0)
    return qp


@pytest.fixture
def bars():
    fb = FakeBars()
    fb.add("600519.SH", "2024-01-02", o=1700, h=1750, low=1680, c=1720, pre=1690)
    fb.add("600519.SH", "2024-01-03", o=1720, h=1800, low=1710, c=1780, pre=1720)
    return fb


@pytest.fixture
def acct(store, quotes, bars):
    a = PaperAccount(name="pick", initial_capital=5_000_000.0,
                     quote_provider=quotes, bar_provider=bars, store=store)
    a.set_trade_date("2024-01-02")
    return a


class TestPickOrders:

    def test_pick_pending_until_effective_date(self, acct):
        res = acct.place_picks([{"code": "600519.SH", "price": 1720.0, "quantity": 100}],
                               screen_date="2024-01-02")
        assert res["effective_date"] == "2024-01-03"
        o = res["orders"][0]
        assert o["status"] == "pending"
        assert o["origin"] == "pick"
        assert o["effective_date"] == "2024-01-03"

    def test_pick_fills_when_next_low_below_bid(self, acct):
        acct.place_picks([{"code": "600519.SH", "price": 1720.0, "quantity": 100}],
                         screen_date="2024-01-02")
        acct.set_trade_date("2024-01-03")           # 次日: low=1710 < bid 1720 → 成交
        o = acct.state["orders"][0]
        assert o["status"] == "filled"
        assert o["filled_price"] == 1720.0          # min(bid, 当日最高1800)

    def test_pick_fill_price_capped_at_high(self, acct):
        acct.place_picks([{"code": "600519.SH", "price": 5000.0, "quantity": 100}],
                         screen_date="2024-01-02")
        acct.set_trade_date("2024-01-03")           # low<5000 → 成交价 = min(5000, high1800)=1800
        o = acct.state["orders"][0]
        assert o["status"] == "filled"
        assert o["filled_price"] == 1800.0

    def test_pick_stays_pending_when_low_not_crossed(self, acct):
        # bid=1700 < 次日最低 1710 → 未越过, 继续挂单 (GTC)
        acct.place_picks([{"code": "600519.SH", "price": 1700.0, "quantity": 100}],
                         screen_date="2024-01-02")
        acct.set_trade_date("2024-01-03")
        o = acct.state["orders"][0]
        assert o["status"] == "pending"

    def test_manual_order_unaffected_by_pick_rule(self, acct, monkeypatch):
        # 普通限价买 (origin=manual) 仍按 [low, high] 区间校验 (回放模式)
        monkeypatch.setattr("src.webui.paper_engine._today_str", lambda: "2026-01-05")
        o = acct.place_order("600519.SH", "buy", 100, price=1700.0, price_type="limit")
        assert o["status"] == "filled"              # 1700 在 1/2 区间 [1680,1750]
        assert o["origin"] == "manual"


class TestStrategyRegistry:

    def test_get_strategy_dispatches(self):
        import src.selection.strategies  # noqa: F401
        from src.selection.strategy import get_strategy

        cls = get_strategy("bull_launch")
        assert cls.strategy_id() == "bull_launch"

    def test_unknown_strategy_raises(self):
        import src.selection.strategies  # noqa: F401
        from src.selection.strategy import get_strategy

        with pytest.raises(KeyError, match="bear_rebound"):
            get_strategy("bear_rebound")


class TestParamMerge:

    def test_overrides_win_over_preset(self):
        from src.selection.strategies.bull_launch import build_configs

        cfg, rank_cfg, meta = build_configs({
            "filter_periods": "5,10",
            "max_gain_total_pct": "25",
            "export_top_n": "8",
        })
        assert cfg.filter_periods == [5, 10]
        assert cfg.max_gain_total_pct == 25.0
        assert rank_cfg.export_top_n == 8
        assert meta["id"] == "bull_launch"

    def test_filter_periods_subset_of_compute(self):
        from src.selection.strategies.bull_launch import build_configs

        cfg, _, _ = build_configs({"filter_periods": "5,10,120"})
        assert 120 in cfg.compute_periods            # 自动补入 compute_periods

    def test_no_global_mutation(self):
        from src.selection.strategies.bull_launch import build_configs

        before = settings.selection.ma_filter.max_gain_total_pct
        build_configs({"max_gain_total_pct": "999"})
        assert settings.selection.ma_filter.max_gain_total_pct == before

    def test_ma_groups_override(self):
        from src.selection.strategies.bull_launch import build_configs

        cfg, _, _ = build_configs({
            "require_ma5_ma10_above_long": "是",
            "ma5_ma10_above_groups": "20,30|40,50",
        })
        assert cfg.require_ma5_ma10_above_long is True
        assert cfg.ma5_ma10_above_groups == [[20, 30], [40, 50]]
        assert 20 in cfg.compute_periods and 50 in cfg.compute_periods

    def test_above_long_auto_default_groups(self):
        from src.selection.strategies.bull_launch import build_configs

        cfg, _, _ = build_configs({"require_ma5_ma10_above_long": "是"})
        assert cfg.require_ma5_ma10_above_long is True
        assert cfg.ma5_ma10_above_groups == [[20, 30], [40, 50]]

    def test_catalog_lists_strategies(self):
        import src.selection.strategies  # noqa: F401
        from src.selection.strategy import strategy_catalog

        cat = strategy_catalog()
        ids = {s["id"] for s in cat}
        assert ids == {"bull_launch"}
        assert "bear_rebound" not in ids
        for s in cat:
            assert "params" in s and isinstance(s["params"], list)
            assert set(s["supports"]) == {"stock", "etf"}


def _uptrend_bars(n=70):
    """构造一段温和上升 + 一次前期大涨 + 末日缩量的日线, 供 ETF 初筛通过。"""
    closes = [10.0]
    for i in range(1, n):
        step = 0.02 if i != n - 6 else 0.6      # 倒数第6日一次大涨
        closes.append(round(closes[-1] * (1 + step / 10 + 0.001 * i / n), 4))
    rows = []
    base = pd.Timestamp("2023-09-01")
    for i, c in enumerate(closes):
        vol = 1_000_000 - i * 500
        if i == n - 1:
            vol = int(vol * 0.5)                # 末日缩量
        rows.append({
            "trade_date": (base + pd.Timedelta(days=i)).date(),
            "open": c * 0.995, "high": c * 1.01, "low": c * 0.99,
            "close": c, "volume": vol, "amount": c * vol,
        })
    df = pd.DataFrame(rows)
    df["change_pct"] = df["close"].pct_change() * 100
    df["turnover_rate"] = pd.NA
    return df


class TestEtfScreener:

    def test_etf_screen_returns_candidate(self, monkeypatch):
        import src.selection.etf_screener as es

        df = _uptrend_bars()
        monkeypatch.setattr(es, "_load_etf_universe", lambda td: ["510300.SH"])
        monkeypatch.setattr(es, "_load_etf_bars", lambda code, td, lookback: df.copy())

        cfg = MaFilterConfig()
        # 关闭对合成数据不友好的硬性要求, 仅验证 ETF 接线正确
        cfg.require_bullish_order = False
        cfg.require_rising = False
        cfg.require_spreading = False
        cfg.require_volume_pullback = False
        cfg.require_ma5_proximity = False
        cfg.prior_surge_use_board_threshold = False
        cfg.prior_surge_min_pct = 0.0
        cfg.prior_surge_lookback_days = 8
        cfg.max_gain_total_pct = 100.0
        cfg.max_gain_1m_pct = 100.0
        rank_cfg = RankConfig()

        candidates, snaps = es.screen_etf_universe(date(2024, 1, 3), cfg, rank_cfg)
        assert "510300.SH" in candidates
        snap = snaps["510300.SH"]
        assert "close" in snap
        assert "composite_score" in snap
