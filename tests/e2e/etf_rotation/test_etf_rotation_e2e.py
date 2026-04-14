"""E2E: ETF 全球资产轮动策略 — 真实 etf_daily 数据

覆盖:
  P1-20 ETFUniverse.load_prices + momentum scoring + CrashGuard + ETFRotator + ETFRotationStrategy
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from src.strategy.etf_rotation.momentum import (
    calc_13612w, calc_r2_return, calc_dual_momentum, score,
)
from src.strategy.etf_rotation.crash_guard import (
    BreadthMomentumGuard, AbsoluteMomentumGuard, VolatilityGuard, CrashGuard,
)
from src.strategy.etf_rotation.rotator import ETFRotator
from src.strategy.etf_rotation.universe import ETFUniverse
from src.strategy.base import HoldingPosition

from tests.e2e.etf_rotation.conftest import ETF_RISK_CODES, ETF_CANARY_CODES


def _make_holding(code, hold_days=5, buy_price=10.0, current_price=10.0, can_sell=True):
    return HoldingPosition(
        code=code,
        buy_date=date.today() - timedelta(days=hold_days),
        buy_price=buy_price,
        quantity=100,
        current_price=current_price,
        hold_days=hold_days,
        can_sell=can_sell,
    )


# ================================================================
# Universe — 真实 DB 加载
# ================================================================

class TestETFUniverseE2E:
    """ETFUniverse — 使用 real_etf_prices fixture (避免 ORM schema 冲突)"""

    def test_load_prices_returns_pivot_matrix(self, real_etf_prices):
        assert isinstance(real_etf_prices, pd.DataFrame)
        assert real_etf_prices.shape[0] >= 100, \
            f"预期至少 100 个交易日, 实际 {real_etf_prices.shape[0]}"
        assert real_etf_prices.shape[1] >= 1, "至少有 1 只 ETF 有数据"
        assert real_etf_prices.isna().sum().sum() < real_etf_prices.size * 0.1

    def test_load_prices_all_risk_pool(self, real_etf_prices):
        risk_cols = [c for c in ETF_RISK_CODES if c in real_etf_prices.columns]
        assert len(risk_cols) >= 8, f"风险池应有 8+ ETF 有数据, 实际 {len(risk_cols)}"
        for dt in real_etf_prices[risk_cols].dtypes:
            assert np.issubdtype(dt, np.floating)

    def test_universe_parses_config_pools(self):
        u = ETFUniverse()
        assert len(u.risk_pool) >= 5
        assert len(u.defensive_pool) >= 1
        assert len(u.canary_pool) >= 1
        assert len(u.get_all_codes()) >= 5


# ================================================================
# Momentum — 真实价格
# ================================================================

class TestMomentumE2E:
    """动量因子计算 — 使用真实 ETF 价格矩阵"""

    def test_calc_13612w_produces_scores(self, real_etf_prices):
        scores = calc_13612w(real_etf_prices)
        assert isinstance(scores, pd.Series)
        assert len(scores) > 0
        assert scores.index.tolist() == list(real_etf_prices.columns)
        assert not scores.isna().all()

    def test_calc_r2_return_with_real_prices(self, real_etf_prices):
        scores = calc_r2_return(real_etf_prices, lookback=25)
        assert isinstance(scores, pd.Series)
        assert len(scores) == real_etf_prices.shape[1]
        for val in scores.dropna():
            assert np.isfinite(val)

    def test_calc_dual_momentum(self, real_etf_prices):
        scores = calc_dual_momentum(real_etf_prices, lookback_months=6)
        assert isinstance(scores, pd.Series)
        assert not scores.isna().all()

    def test_score_dispatcher_13612w(self, real_etf_prices):
        s = score(real_etf_prices, method="13612w")
        assert isinstance(s, pd.Series)
        assert len(s) == real_etf_prices.shape[1]

    def test_score_dispatcher_r2_return(self, real_etf_prices):
        s = score(real_etf_prices, method="r2_return", lookback_days=25)
        assert isinstance(s, pd.Series)

    def test_score_dispatcher_dual_momentum(self, real_etf_prices):
        s = score(real_etf_prices, method="dual_momentum")
        assert isinstance(s, pd.Series)

    def test_score_raises_on_unknown_method(self, real_etf_prices):
        with pytest.raises(ValueError, match="未知动量方法"):
            score(real_etf_prices, method="unknown_method")

    def test_momentum_ranking_is_reasonable(self, real_etf_prices):
        """检验动量排名: 不同方法对同一价格序列应给出非零分"""
        for method in ("13612w", "r2_return", "dual_momentum"):
            s = score(real_etf_prices, method=method, lookback_days=25)
            nonzero = (s != 0).sum()
            assert nonzero >= 2, f"{method}: 应至少有 2 只 ETF 得到非零动量分"


# ================================================================
# CrashGuard — 真实波动
# ================================================================

class TestCrashGuardE2E:
    """崩盘保护机制 — 真实市场数据"""

    def test_breadth_guard_returns_fraction(self, real_etf_prices):
        canary_cols = [c for c in ETF_CANARY_CODES if c in real_etf_prices.columns]
        if not canary_cols:
            pytest.skip("金丝雀 ETF 无数据")
        canary_prices = real_etf_prices[canary_cols]
        guard = BreadthMomentumGuard()
        frac = guard.evaluate(canary_prices)
        assert 0.0 <= frac <= 1.0

    def test_absolute_guard_returns_binary(self, real_etf_prices):
        risk_cols = [c for c in ETF_RISK_CODES if c in real_etf_prices.columns]
        risk_prices = real_etf_prices[risk_cols]
        guard = AbsoluteMomentumGuard()
        frac = guard.evaluate(risk_prices)
        assert frac in (0.0, 1.0)

    def test_volatility_guard_returns_valid_fraction(self, real_etf_prices):
        guard = VolatilityGuard()
        frac = guard.evaluate(real_etf_prices)
        assert 0.0 <= frac <= 1.0

    def test_composite_guard(self, real_etf_prices):
        canary_cols = [c for c in ETF_CANARY_CODES if c in real_etf_prices.columns]
        risk_cols = [c for c in ETF_RISK_CODES if c in real_etf_prices.columns]
        guard = CrashGuard(enable_breadth=True, enable_absolute=True, enable_volatility=True)
        frac = guard.evaluate(
            canary_prices=real_etf_prices[canary_cols] if canary_cols else pd.DataFrame(),
            risk_prices=real_etf_prices[risk_cols],
            all_prices=real_etf_prices,
        )
        assert 0.0 <= frac <= 1.0


# ================================================================
# Rotator — 排名/选择/止损
# ================================================================

class TestRotatorE2E:
    """ETF 轮动核心逻辑 — 真实动量排名"""

    def test_rank_and_select_top_k(self, real_etf_prices):
        scores = calc_13612w(real_etf_prices)
        risk_scores = scores.reindex(
            [c for c in ETF_RISK_CODES if c in scores.index]
        ).dropna()
        selected = ETFRotator.rank_and_select(risk_scores, top_k=2)
        assert isinstance(selected, list)
        assert 0 < len(selected) <= 2
        for code in selected:
            assert code in risk_scores.index

    def test_rank_and_select_respects_score_bounds(self, real_etf_prices):
        scores = calc_13612w(real_etf_prices)
        selected = ETFRotator.rank_and_select(
            scores, top_k=3, score_min=-1.0, score_max=10.0,
        )
        for code in selected:
            assert -1.0 <= scores[code] <= 10.0

    def test_anti_whipsaw_preserves_recent_holdings(self, real_etf_prices):
        scores = calc_13612w(real_etf_prices)
        risk_scores = scores.reindex(
            [c for c in ETF_RISK_CODES if c in scores.index]
        ).dropna()
        new_selected = ETFRotator.rank_and_select(risk_scores, top_k=2)
        old_code = [c for c in risk_scores.index if c not in new_selected][0]
        holdings = [_make_holding(old_code, hold_days=3, buy_price=10.0, current_price=10.1)]
        filtered = ETFRotator.anti_whipsaw_filter(
            new_selected, holdings, risk_scores,
            min_hold_days=9, rank_threshold=0.10,
        )
        assert old_code in filtered, "持仓 3 天 < min_hold_days 9, 应被保留"

    def test_is_rebalance_day(self):
        assert ETFRotator.is_rebalance_day(None, date(2025, 6, 1), 20) is True
        assert ETFRotator.is_rebalance_day(
            date(2025, 5, 31), date(2025, 6, 1), 20,
        ) is False
        assert ETFRotator.is_rebalance_day(
            date(2025, 5, 1), date(2025, 6, 1), 20,
        ) is True

    def test_check_stop_loss_no_trigger(self, real_etf_prices):
        """正常涨跌幅不应触发高阈值止损"""
        code = real_etf_prices.columns[0]
        last_price = float(real_etf_prices[code].iloc[-1])
        holdings = [
            _make_holding(
                code, hold_days=5, buy_price=last_price * 0.98,
                current_price=last_price, can_sell=True,
            ),
        ]
        sells = ETFRotator.check_stop_loss(
            holdings, stop_loss_daily=0.20, stop_loss_3d=0.30, prices=real_etf_prices,
        )
        assert len(sells) == 0, "高阈值止损不应被触发"


# ================================================================
# Full Strategy — 端到端信号生成
# ================================================================

class TestETFRotationStrategyE2E:
    """ETFRotationStrategy.generate_signals — 真实价格数据端到端

    注意: 主 E2E conftest 的 db_engine 会修改 ORM schema 为 e2e_test,
    导致 ETFDaily ORM 查询失败。因此这里 mock _load_prices 使用 fixture 真实数据。
    """

    @staticmethod
    def _patch_load_prices(strategy, prices_df):
        """替换策略的 _load_prices 为直接返回 fixture 数据"""
        from unittest.mock import MagicMock
        strategy._load_prices = MagicMock(return_value=prices_df)

    def test_generate_signals_on_rebalance_day(self, real_etf_prices):
        from src.strategy.etf_rotation.etf_rotation_strategy import ETFRotationStrategy

        strategy = ETFRotationStrategy()
        strategy._last_rebalance_date = None
        self._patch_load_prices(strategy, real_etf_prices)

        signals = strategy.generate_signals(
            trade_date=date(2026, 3, 1),
            universe=[],
            holdings=None,
        )
        assert isinstance(signals, list)
        assert len(signals) > 0, "调仓日应生成至少 1 个信号"
        for sig in signals:
            assert sig.strategy_name == "etf_rotation"
            assert sig.direction in ("buy", "sell")
            assert sig.trade_date == date(2026, 3, 1)

    def test_generate_signals_non_rebalance_day_no_signals(self, real_etf_prices):
        from src.strategy.etf_rotation.etf_rotation_strategy import ETFRotationStrategy

        strategy = ETFRotationStrategy()
        strategy._last_rebalance_date = date(2026, 2, 28)
        self._patch_load_prices(strategy, real_etf_prices)

        signals = strategy.generate_signals(
            trade_date=date(2026, 3, 1),
            universe=[],
            holdings=None,
        )
        assert isinstance(signals, list)
        assert len(signals) == 0, "1 天后非调仓日不应产生信号"

    def test_generate_signals_with_existing_holdings(self, real_etf_prices):
        from src.strategy.etf_rotation.etf_rotation_strategy import ETFRotationStrategy

        strategy = ETFRotationStrategy()
        strategy._last_rebalance_date = None
        self._patch_load_prices(strategy, real_etf_prices)

        holdings = [
            _make_holding("510300.SH", hold_days=15, buy_price=3.5, current_price=3.6),
        ]
        signals = strategy.generate_signals(
            trade_date=date(2026, 3, 1),
            universe=[],
            holdings=holdings,
        )
        assert isinstance(signals, list)
        directions = {s.direction for s in signals}
        assert directions.issubset({"buy", "sell"})

    def test_disabled_strategy_returns_empty(self, real_etf_prices):
        from src.strategy.etf_rotation.etf_rotation_strategy import ETFRotationStrategy

        strategy = ETFRotationStrategy()
        self._patch_load_prices(strategy, real_etf_prices)
        original = strategy._cfg.enabled
        object.__setattr__(strategy._cfg, "enabled", False)
        try:
            signals = strategy.generate_signals(
                trade_date=date(2026, 3, 1), universe=[], holdings=None,
            )
            assert signals == []
        finally:
            object.__setattr__(strategy._cfg, "enabled", original)
