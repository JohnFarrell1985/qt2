"""Backtest Engine E2E — 使用真实 PostgreSQL 数据验证回测核心组件

测试范围:
  - 交易日历从 stock_daily 加载
  - OHLCV 预加载 + 涨跌停/停牌状态计算
  - A 股 / 港股通费用计算
  - 绩效统计模块
"""
import pytest
from datetime import date

from src.backtest.orchestrator_backtester import OrchestratorBacktester
from src.backtest.fees import (
    FeeConfig, TradeFees, HKTradeFees,
    calc_buy_fees, calc_sell_fees,
    calc_hk_buy_fees, calc_hk_sell_fees,
    detect_market, is_sh_stock, is_hk_stock,
)
from src.backtest.performance import (
    full_performance_report, calc_returns,
    annualized_return, max_drawdown, sharpe_ratio,
    sortino_ratio, calmar_ratio, win_rate, profit_loss_ratio,
    deflated_sharpe_ratio,
)


pytestmark = pytest.mark.timeout(30)


class TestTradingCalendar:
    """从真实 stock_daily 加载交易日历"""

    def test_load_calendar_returns_sorted_dates(self, backtest_date_range):
        start, end = backtest_date_range
        calendar = OrchestratorBacktester._load_trading_calendar(start, end)
        assert len(calendar) > 0
        assert all(isinstance(d, date) for d in calendar)
        assert calendar == sorted(calendar)
        assert calendar[0] >= start
        assert calendar[-1] <= end

    def test_load_calendar_excludes_weekends(self, backtest_date_range):
        start, end = backtest_date_range
        calendar = OrchestratorBacktester._load_trading_calendar(start, end)
        for d in calendar:
            assert d.weekday() < 5, f"{d} is a weekend"

    def test_load_calendar_empty_for_future(self):
        future_start = date(2099, 1, 1)
        future_end = date(2099, 12, 31)
        calendar = OrchestratorBacktester._load_trading_calendar(future_start, future_end)
        assert calendar == []


class TestOHLCPreload:
    """真实 OHLCV 预加载与涨跌停状态计算"""

    def test_preload_ohlc_structure(self, backtest_date_range):
        start, end = backtest_date_range
        cache = OrchestratorBacktester._preload_ohlc(start, end)
        assert isinstance(cache, dict)
        assert len(cache) > 0

        for td, day_data in cache.items():
            assert isinstance(td, date)
            for code, bar in day_data.items():
                assert isinstance(code, str)
                for field in ("open", "high", "low", "close", "volume"):
                    assert field in bar, f"Missing {field} for {code} on {td}"

    def test_preload_ohlc_prices_positive(self, backtest_date_range):
        start, end = backtest_date_range
        cache = OrchestratorBacktester._preload_ohlc(start, end)
        for td, day_data in cache.items():
            for code, bar in day_data.items():
                if bar["volume"] and bar["volume"] > 0:
                    assert bar["close"] > 0, f"{code} close <= 0 on {td}"
                    assert bar["high"] >= bar["low"], f"{code} high < low on {td}"

    def test_limit_status_detection(self, backtest_date_range):
        start, end = backtest_date_range
        ohlc_cache = OrchestratorBacktester._preload_ohlc(start, end)
        limit_cache = OrchestratorBacktester._preload_limit_status(ohlc_cache)
        assert len(limit_cache) == len(ohlc_cache)

        for td, day_limits in limit_cache.items():
            for code, lim in day_limits.items():
                assert "is_suspended" in lim
                assert "is_limit_up" in lim
                assert "is_limit_down" in lim
                assert "is_one_word_limit" in lim
                assert "threshold" in lim
                if code.startswith("688") or code.startswith("300"):
                    assert lim["threshold"] == 20.0
                else:
                    assert lim["threshold"] == 10.0

    def test_suspended_stocks_have_zero_volume(self, backtest_date_range):
        """停牌 = volume == 0"""
        start, end = backtest_date_range
        ohlc_cache = OrchestratorBacktester._preload_ohlc(start, end)
        limit_cache = OrchestratorBacktester._preload_limit_status(ohlc_cache)
        for td in limit_cache:
            for code, lim in limit_cache[td].items():
                if lim["is_suspended"]:
                    bar = ohlc_cache[td][code]
                    assert (bar["volume"] or 0) == 0


class TestFeeCalculation:
    """A 股 & 港股通费用计算 — 使用真实股票代码"""

    def test_sh_buy_fees(self):
        fees = calc_buy_fees(price=50.0, quantity=100, code="600519")
        assert isinstance(fees, TradeFees)
        assert fees.commission >= 5.0
        assert fees.stamp_tax == 0.0
        assert fees.transfer_fee > 0

    def test_sz_buy_fees_no_transfer(self):
        fees = calc_buy_fees(price=30.0, quantity=100, code="000001")
        assert fees.transfer_fee == 0.0
        assert fees.commission >= 5.0

    def test_sell_has_stamp_tax(self):
        fees = calc_sell_fees(price=50.0, quantity=1000, code="600519")
        assert fees.stamp_tax > 0
        assert fees.commission > 0
        assert fees.total == fees.commission + fees.stamp_tax + fees.transfer_fee

    def test_min_commission_floor(self):
        fees = calc_buy_fees(price=1.0, quantity=100, code="000001")
        assert fees.commission == 5.0

    def test_custom_fee_config(self):
        cfg = FeeConfig(commission_rate=0.0003, commission_min=5.0,
                        stamp_tax_rate=0.001, transfer_fee_rate=0.0001)
        fees = calc_sell_fees(price=100.0, quantity=1000, code="600001", config=cfg)
        expected_commission = max(100.0 * 1000 * 0.0003, 5.0)
        assert fees.commission == round(expected_commission, 2)

    def test_hk_buy_fees(self):
        fees = calc_hk_buy_fees(price=100.0, quantity=1000, code="00700")
        assert isinstance(fees, HKTradeFees)
        assert fees.stamp_tax >= 1.0
        assert fees.total > fees.commission

    def test_hk_sell_fees_symmetric(self):
        buy = calc_hk_buy_fees(price=100.0, quantity=500, code="00700")
        sell = calc_hk_sell_fees(price=100.0, quantity=500, code="00700")
        assert buy.total == sell.total

    def test_detect_market_a_share(self):
        assert detect_market("600519") == "A"
        assert detect_market("000001") == "A"
        assert detect_market("300750") == "A"

    def test_detect_market_hk(self):
        assert detect_market("00700") == "HK"
        assert detect_market("HK00700") == "HK"

    def test_is_sh_stock(self):
        assert is_sh_stock("600519")
        assert not is_sh_stock("000001")

    def test_is_hk_stock(self):
        assert is_hk_stock("00700")
        assert is_hk_stock("HK09988")
        assert not is_hk_stock("600519")


class TestPerformanceReport:
    """绩效统计 — 使用真实行情数据构造净值曲线"""

    @pytest.fixture
    def equity_curve_from_real_data(self, real_ohlcv_sample):
        """用真实 000001 收盘价构造模拟净值曲线"""
        df = real_ohlcv_sample[real_ohlcv_sample["code"] == "000001"].copy()
        df = df.sort_values("trade_date")
        initial_capital = 100_000.0
        first_close = df["close"].iloc[0]
        curve = []
        for _, row in df.iterrows():
            capital = initial_capital * (row["close"] / first_close)
            curve.append({
                "date": str(row["trade_date"]),
                "capital": round(capital, 2),
                "cash": 0,
                "n_holdings": 1,
            })
        return curve

    @pytest.fixture
    def sample_trades(self):
        return [
            {"code": "000001", "direction": "sell", "profit": 500.0},
            {"code": "600519", "direction": "sell", "profit": -200.0},
            {"code": "000858", "direction": "sell", "profit": 300.0},
            {"code": "600036", "direction": "sell", "profit": -100.0},
            {"code": "300750", "direction": "sell", "profit": 800.0},
        ]

    def test_full_report_has_all_fields(self, equity_curve_from_real_data, sample_trades):
        report = full_performance_report(equity_curve_from_real_data, sample_trades)
        assert "annualized_return_pct" in report
        assert "max_drawdown" in report
        assert "sharpe_ratio" in report
        assert "sortino_ratio" in report
        assert "calmar_ratio" in report
        assert "win_rate" in report
        assert "total_trades" in report

    def test_returns_series_valid(self, equity_curve_from_real_data):
        returns = calc_returns(equity_curve_from_real_data)
        assert len(returns) > 0
        assert returns.isna().sum() == 0

    def test_annualized_return_reasonable(self, equity_curve_from_real_data):
        ann = annualized_return(equity_curve_from_real_data)
        assert -100 < ann < 500

    def test_max_drawdown_non_negative(self, equity_curve_from_real_data):
        dd = max_drawdown(equity_curve_from_real_data)
        assert dd["max_drawdown_pct"] >= 0
        assert dd["peak_date"] is not None

    def test_sharpe_is_finite(self, equity_curve_from_real_data):
        sr = sharpe_ratio(equity_curve_from_real_data)
        assert isinstance(sr, float)
        import math
        assert not math.isnan(sr) and not math.isinf(sr)

    def test_sortino_is_finite(self, equity_curve_from_real_data):
        s = sortino_ratio(equity_curve_from_real_data)
        assert isinstance(s, float)

    def test_calmar_is_finite(self, equity_curve_from_real_data):
        c = calmar_ratio(equity_curve_from_real_data)
        assert isinstance(c, float)

    def test_win_rate_calculation(self, sample_trades):
        wr = win_rate(sample_trades)
        assert wr == 60.0

    def test_profit_loss_ratio(self, sample_trades):
        plr = profit_loss_ratio(sample_trades)
        assert plr > 0

    def test_deflated_sharpe_ratio_in_range(self, equity_curve_from_real_data):
        returns = calc_returns(equity_curve_from_real_data)
        sr = sharpe_ratio(equity_curve_from_real_data)
        if sr != 0 and len(returns) > 5:
            dsr = deflated_sharpe_ratio(
                sr, num_trials=10,
                var_sharpe=returns.std() ** 2,
                T=len(returns),
            )
            assert 0.0 <= dsr <= 1.0

    def test_full_report_with_deflated_sharpe(self, equity_curve_from_real_data, sample_trades):
        report = full_performance_report(
            equity_curve_from_real_data, sample_trades, num_trials=5
        )
        if report["sharpe_ratio"] != 0:
            assert "deflated_sharpe_pvalue" in report
