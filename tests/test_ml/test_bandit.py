"""Tests for src/ml/bandit.py - LinearThompsonTwoArm (P2-18)"""
import numpy as np
import pytest

from src.ml.bandit import (
    LinearThompsonTwoArm,
    ARM_FACTOR,
    ARM_MODEL,
    ARMS,
    DEFAULT_WEIGHTS,
)


class TestDefaultWeights:
    def test_weights_sum_to_one(self):
        assert abs(float(DEFAULT_WEIGHTS.sum()) - 1.0) < 1e-9

    def test_weights_length(self):
        assert len(DEFAULT_WEIGHTS) == 8


class TestLinearThompsonTwoArm:
    def test_default_init(self):
        b = LinearThompsonTwoArm()
        assert b.n_features == 8
        assert set(b._B.keys()) == {ARM_FACTOR, ARM_MODEL}

    def test_custom_features(self):
        b = LinearThompsonTwoArm(n_features=4)
        assert b.n_features == 4
        for arm in ARMS:
            assert b._B[arm].shape == (4, 4)
            assert b._f[arm].shape == (4,)

    def test_next_arm_no_context(self):
        b = LinearThompsonTwoArm()
        arm = b.next_arm(context=None)
        assert arm in ARMS

    def test_next_arm_with_context(self):
        b = LinearThompsonTwoArm()
        ctx = np.random.randn(8)
        arm = b.next_arm(ctx)
        assert arm in ARMS

    def test_next_arm_wrong_dim_falls_back(self):
        b = LinearThompsonTwoArm(n_features=8)
        arm = b.next_arm(np.ones(5))
        assert arm in ARMS

    def test_update_records_history(self):
        b = LinearThompsonTwoArm()
        ctx = np.random.randn(8)
        b.update(ARM_FACTOR, 1.0, ctx)
        assert len(b._history) == 1
        assert b._history[0][0] == ARM_FACTOR

    def test_update_changes_B_matrix(self):
        b = LinearThompsonTwoArm()
        B_before = b._B[ARM_FACTOR].copy()
        ctx = np.random.randn(8)
        b.update(ARM_FACTOR, 1.0, ctx)
        assert not np.allclose(B_before, b._B[ARM_FACTOR])

    def test_update_changes_f_vector(self):
        b = LinearThompsonTwoArm()
        f_before = b._f[ARM_MODEL].copy()
        ctx = np.random.randn(8)
        b.update(ARM_MODEL, 2.0, ctx)
        assert not np.allclose(f_before, b._f[ARM_MODEL])

    def test_total_pulls(self):
        b = LinearThompsonTwoArm()
        ctx = np.random.randn(8)
        b.update(ARM_FACTOR, 1.0, ctx)
        b.update(ARM_FACTOR, 0.5, ctx)
        b.update(ARM_MODEL, 0.8, ctx)
        pulls = b.total_pulls
        assert pulls[ARM_FACTOR] == 2
        assert pulls[ARM_MODEL] == 1

    def test_compute_reward_empty_metrics(self):
        b = LinearThompsonTwoArm()
        r = b.compute_reward({})
        assert r == 0.0

    def test_compute_reward_weighted(self):
        b = LinearThompsonTwoArm()
        metrics = {
            "ic": 0.05, "icir": 1.0, "rank_ic": 0.04, "rank_icir": 0.8,
            "ann_return": 0.15, "ir": 1.2, "max_drawdown": 0.10, "sharpe": 1.5,
        }
        r = b.compute_reward(metrics)
        expected = (
            0.1 * 0.05
            + 0.1 * 1.0
            + 0.05 * 0.04
            + 0.05 * 0.8
            + 0.25 * 0.15
            + 0.15 * 1.2
            + 0.1 * (-0.10)
            + 0.2 * 1.5
        )
        assert abs(r - expected) < 1e-9

    def test_mdd_negated_in_reward(self):
        b = LinearThompsonTwoArm()
        r_low = b.compute_reward({"max_drawdown": 0.05})
        r_high = b.compute_reward({"max_drawdown": 0.20})
        assert r_low > r_high

    @pytest.mark.timeout(30)
    def test_convergence_to_better_arm(self):
        rng = np.random.RandomState(42)
        b = LinearThompsonTwoArm(n_features=4)

        for _ in range(200):
            ctx = rng.randn(4)
            b.update(ARM_FACTOR, float(ctx @ np.array([1.0, 0.5, 0.2, 0.1])) + rng.randn() * 0.1, ctx)
            b.update(ARM_MODEL, float(ctx @ np.array([0.1, 0.1, 0.1, 0.1])) + rng.randn() * 0.1, ctx)

        factor_count = sum(
            1 for _ in range(100)
            if b.next_arm(np.abs(rng.randn(4))) == ARM_FACTOR
        )
        assert factor_count > 50, f"factor chosen {factor_count}/100, expected > 50"
