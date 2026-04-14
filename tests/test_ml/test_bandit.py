"""Tests for src/ml/bandit.py - BanditMetrics, LinearThompsonBandit, IterationController"""
import numpy as np
import pytest

from src.ml.bandit import BanditMetrics, LinearThompsonBandit, IterationController


# ---------------------------------------------------------------------------
# BanditMetrics
# ---------------------------------------------------------------------------

class TestBanditMetrics:
    def test_default_zero_reward(self):
        m = BanditMetrics()
        assert m.to_reward() == 0.0

    def test_reward_weighted_sum(self):
        m = BanditMetrics(
            ic=0.05, icir=1.0, rank_ic=0.04, rank_icir=0.8,
            annual_return=0.15, information_ratio=1.2,
            max_drawdown=0.10, sharpe=1.5,
        )
        expected = (
            0.1 * 0.05
            + 0.1 * 1.0
            + 0.05 * 0.04
            + 0.05 * 0.8
            + 0.25 * 0.15
            + 0.15 * 1.2
            + 0.1 * (-0.10)   # mdd negated
            + 0.2 * 1.5
        )
        assert abs(m.to_reward() - expected) < 1e-9

    def test_mdd_negated_in_reward(self):
        """Higher max_drawdown should decrease reward (it's a cost)."""
        m_low = BanditMetrics(max_drawdown=0.05)
        m_high = BanditMetrics(max_drawdown=0.20)
        assert m_low.to_reward() > m_high.to_reward()

    def test_to_vector_shape(self):
        m = BanditMetrics(ic=0.1, sharpe=2.0)
        v = m.to_vector()
        assert isinstance(v, np.ndarray)
        assert v.shape == (8,)

    def test_to_vector_mdd_negated(self):
        m = BanditMetrics(max_drawdown=0.15)
        v = m.to_vector()
        assert v[6] == -0.15

    def test_weights_sum_to_one(self):
        assert abs(sum(BanditMetrics.WEIGHTS) - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# LinearThompsonBandit
# ---------------------------------------------------------------------------

class TestLinearThompsonBandit:
    def test_default_init(self):
        b = LinearThompsonBandit()
        assert b.n_features == 8
        assert set(b.arms.keys()) == {"factor", "model"}
        for arm_data in b.arms.values():
            assert arm_data["n_pulls"] == 0
            assert arm_data["B"].shape == (8, 8)
            assert arm_data["f"].shape == (8,)

    def test_select_arm_returns_valid_name(self):
        b = LinearThompsonBandit()
        ctx = np.random.randn(8)
        arm = b.select_arm(ctx)
        assert arm in LinearThompsonBandit.ARM_NAMES

    def test_select_arm_wrong_dim_raises(self):
        b = LinearThompsonBandit(n_features=8)
        with pytest.raises(ValueError, match="Context dimension"):
            b.select_arm(np.ones(5))

    def test_update_increments_pull_count(self):
        b = LinearThompsonBandit()
        ctx = np.random.randn(8)
        b.update("factor", ctx, 1.0)
        assert b.arms["factor"]["n_pulls"] == 1
        b.update("factor", ctx, 0.5)
        assert b.arms["factor"]["n_pulls"] == 2

    def test_update_changes_B_matrix(self):
        b = LinearThompsonBandit()
        B_before = b.arms["factor"]["B"].copy()
        ctx = np.random.randn(8)
        b.update("factor", ctx, 1.0)
        B_after = b.arms["factor"]["B"]
        assert not np.allclose(B_before, B_after)

    def test_update_changes_f_vector(self):
        b = LinearThompsonBandit()
        f_before = b.arms["model"]["f"].copy()
        ctx = np.random.randn(8)
        b.update("model", ctx, 2.0)
        assert not np.allclose(f_before, b.arms["model"]["f"])

    def test_update_unknown_arm_raises(self):
        b = LinearThompsonBandit()
        with pytest.raises(ValueError, match="Unknown arm"):
            b.update("unknown", np.ones(8), 1.0)

    def test_convergence_to_better_arm(self):
        """After many updates, bandit should prefer the arm with higher reward."""
        rng = np.random.RandomState(42)
        b = LinearThompsonBandit(n_features=4, prior_variance=1.0)

        for _ in range(200):
            ctx = rng.randn(4)
            b.update("factor", ctx, float(ctx @ np.array([1.0, 0.5, 0.2, 0.1])) + rng.randn() * 0.1)
            b.update("model", ctx, float(ctx @ np.array([0.1, 0.1, 0.1, 0.1])) + rng.randn() * 0.1)

        factor_count = 0
        for _ in range(100):
            ctx = rng.randn(4)
            ctx_positive = np.abs(ctx)
            arm = b.select_arm(ctx_positive)
            if arm == "factor":
                factor_count += 1

        assert factor_count > 60, f"factor chosen {factor_count}/100, expected > 60"

    def test_get_stats_structure(self):
        b = LinearThompsonBandit()
        ctx = np.ones(8)
        b.update("factor", ctx, 1.0)
        stats = b.get_stats()
        assert "factor" in stats and "model" in stats
        assert stats["factor"]["n_pulls"] == 1
        assert stats["model"]["n_pulls"] == 0
        assert "mu_hat" in stats["factor"]
        assert "posterior_trace" in stats["factor"]

    def test_invalid_n_features_raises(self):
        with pytest.raises(ValueError, match="positive"):
            LinearThompsonBandit(n_features=0)

    def test_invalid_prior_variance_raises(self):
        with pytest.raises(ValueError, match="positive"):
            LinearThompsonBandit(prior_variance=-1)


# ---------------------------------------------------------------------------
# IterationController
# ---------------------------------------------------------------------------

class TestIterationController:
    def test_first_decide_returns_valid_arm(self):
        ctrl = IterationController()
        m = BanditMetrics(ic=0.05, sharpe=1.0)
        action = ctrl.decide(m)
        assert action in LinearThompsonBandit.ARM_NAMES

    def test_decide_builds_history(self):
        ctrl = IterationController()
        for i in range(5):
            m = BanditMetrics(ic=0.01 * i, sharpe=0.5 * i)
            ctrl.decide(m)
        assert len(ctrl.history) == 5

    def test_decide_records_action_and_reward(self):
        ctrl = IterationController()
        m = BanditMetrics(ic=0.1, sharpe=2.0)
        action = ctrl.decide(m)
        assert ctrl.history[-1]["action"] == action
        assert "reward" in ctrl.history[-1]
        assert "context" in ctrl.history[-1]
        assert "timestamp" in ctrl.history[-1]

    def test_record_updates_bandit(self):
        ctrl = IterationController()
        m = BanditMetrics(ic=0.05, sharpe=1.5)
        ctrl.record("factor", m)
        assert ctrl.bandit.arms["factor"]["n_pulls"] == 1
        assert len(ctrl.history) == 1

    def test_get_summary(self):
        ctrl = IterationController()
        ctrl.record("factor", BanditMetrics(ic=0.05))
        ctrl.record("model", BanditMetrics(sharpe=1.0))
        ctrl.record("factor", BanditMetrics(ic=0.08))
        summary = ctrl.get_summary()
        assert summary["total_iterations"] == 3
        assert summary["factor_pulls"] == 2
        assert summary["model_pulls"] == 1
        assert "mean_reward" in summary
        assert "bandit_stats" in summary

    def test_decide_updates_bandit_on_second_call(self):
        """Second decide() should update the bandit with previous action's result."""
        ctrl = IterationController()
        m1 = BanditMetrics(ic=0.05, sharpe=1.0)
        action1 = ctrl.decide(m1)
        initial_pulls = ctrl.bandit.arms[action1]["n_pulls"]

        m2 = BanditMetrics(ic=0.08, sharpe=1.5)
        ctrl.decide(m2)
        assert ctrl.bandit.arms[action1]["n_pulls"] == initial_pulls + 1

    def test_custom_bandit(self):
        bandit = LinearThompsonBandit(n_features=4)
        ctrl = IterationController(bandit=bandit)
        assert ctrl.bandit.n_features == 4
