"""E2E: Thompson Sampling Bandit + IterationController — 纯计算

覆盖:
  P1-02 LinearThompsonBandit: 多轮 select + update 收敛性
  P1-02 IterationController: decide/record 全流程
  P1-02 BanditMetrics: 指标向量 + 奖励计算
"""
import numpy as np
import pytest

from src.ml.bandit import BanditMetrics, LinearThompsonBandit, IterationController


class TestBanditMetricsE2E:
    """BanditMetrics 8 维向量"""

    def test_to_reward_positive_metrics(self):
        m = BanditMetrics(
            ic=0.05, icir=1.0, rank_ic=0.04, rank_icir=0.8,
            annual_return=0.15, information_ratio=1.5,
            max_drawdown=0.10, sharpe=2.0,
        )
        reward = m.to_reward()
        assert reward > 0

    def test_to_reward_negative_metrics(self):
        m = BanditMetrics(
            ic=-0.02, icir=-0.5, rank_ic=-0.01, rank_icir=-0.3,
            annual_return=-0.10, information_ratio=-0.5,
            max_drawdown=0.30, sharpe=-1.0,
        )
        reward = m.to_reward()
        assert reward < 0

    def test_to_vector_shape(self):
        m = BanditMetrics()
        vec = m.to_vector()
        assert vec.shape == (8,)

    def test_mdd_negated_in_vector(self):
        m = BanditMetrics(max_drawdown=0.15)
        vec = m.to_vector()
        assert vec[6] == -0.15, "max_drawdown 在向量中应被取反"

    def test_weights_sum_to_one(self):
        total = sum(BanditMetrics.WEIGHTS)
        assert abs(total - 1.0) < 1e-10


class TestLinearThompsonBanditE2E:
    """双臂 Thompson Sampling — 多轮交互"""

    def test_select_arm_returns_valid_name(self):
        bandit = LinearThompsonBandit(n_features=8)
        context = np.random.randn(8)
        arm = bandit.select_arm(context)
        assert arm in ("factor", "model")

    def test_update_modifies_stats(self):
        bandit = LinearThompsonBandit(n_features=8)
        context = np.random.randn(8)
        arm = bandit.select_arm(context)
        stats_before = bandit.get_stats()[arm]["n_pulls"]
        bandit.update(arm, context, reward=0.5)
        stats_after = bandit.get_stats()[arm]["n_pulls"]
        assert stats_after == stats_before + 1

    def test_multi_round_convergence(self):
        """100 轮交互: factor arm 持续给高奖励, 应被更多选择"""
        np.random.seed(42)
        bandit = LinearThompsonBandit(n_features=8, prior_variance=1.0)

        factor_pulls = 0
        model_pulls = 0

        for _ in range(100):
            context = np.random.randn(8) * 0.1
            context[0] = 0.5
            arm = bandit.select_arm(context)

            if arm == "factor":
                factor_pulls += 1
                reward = 0.8 + np.random.randn() * 0.1
            else:
                model_pulls += 1
                reward = 0.2 + np.random.randn() * 0.1

            bandit.update(arm, context, reward)

        stats = bandit.get_stats()
        assert stats["factor"]["n_pulls"] + stats["model"]["n_pulls"] == 100
        assert factor_pulls > 30, "高奖励 arm 应被拉至少 30 次"

    def test_get_stats_structure(self):
        bandit = LinearThompsonBandit(n_features=8)
        context = np.random.randn(8)
        bandit.update("factor", context, 0.5)
        stats = bandit.get_stats()
        assert "factor" in stats
        assert "model" in stats
        assert "n_pulls" in stats["factor"]
        assert "mu_hat" in stats["factor"]
        assert "posterior_trace" in stats["factor"]

    def test_wrong_context_dimension_raises(self):
        bandit = LinearThompsonBandit(n_features=8)
        with pytest.raises(ValueError, match="Context dimension"):
            bandit.select_arm(np.array([1.0, 2.0]))

    def test_unknown_arm_raises(self):
        bandit = LinearThompsonBandit(n_features=8)
        with pytest.raises(ValueError, match="Unknown arm"):
            bandit.update("unknown_arm", np.random.randn(8), 0.5)


class TestIterationControllerE2E:
    """IterationController — decide/record 全流程"""

    def test_decide_returns_action(self):
        ctrl = IterationController()
        metrics = BanditMetrics(ic=0.05, sharpe=1.5)
        action = ctrl.decide(metrics)
        assert action in ("factor", "model")

    def test_multi_iteration_cycle(self):
        """模拟 20 轮迭代循环"""
        ctrl = IterationController()
        for i in range(20):
            m = BanditMetrics(
                ic=0.03 + np.random.randn() * 0.01,
                sharpe=1.0 + np.random.randn() * 0.2,
                annual_return=0.10 + np.random.randn() * 0.05,
            )
            action = ctrl.decide(m)
            assert action in ("factor", "model")

        summary = ctrl.get_summary()
        assert summary["total_iterations"] == 20
        assert summary["factor_pulls"] + summary["model_pulls"] == 20
        assert summary["mean_reward"] != 0

    def test_record_manual_mode(self):
        ctrl = IterationController()
        m = BanditMetrics(ic=0.10, sharpe=3.0)
        ctrl.record("factor", m)
        ctrl.record("model", BanditMetrics(ic=0.02, sharpe=0.5))

        summary = ctrl.get_summary()
        assert summary["total_iterations"] == 2
        assert summary["factor_pulls"] == 1
        assert summary["model_pulls"] == 1

    def test_get_summary_bandit_stats(self):
        ctrl = IterationController()
        for _ in range(5):
            ctrl.decide(BanditMetrics(ic=0.05, sharpe=1.0))
        summary = ctrl.get_summary()
        assert "bandit_stats" in summary
        assert "factor" in summary["bandit_stats"]
        assert "model" in summary["bandit_stats"]
