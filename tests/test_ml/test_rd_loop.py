"""SimpleRDLoop 单元测试

测试 src/ml/rd_loop.py:
- iterate 使用 mock proposer + evaluator
- iterate 使用默认 proposer (无 LLM)
- bandit / trace 集成
- max_iterations 控制循环次数
"""
import pytest
from unittest.mock import MagicMock, patch

import numpy as np

from src.ml.bandit import ARM_FACTOR, ARM_MODEL, LinearThompsonTwoArm
from src.ml.experiment_tracker import ExperimentTrace
from src.ml.rd_loop import SimpleRDLoop


def _make_metrics(ic: float = 0.03, sharpe: float = 1.0) -> dict:
    return {
        "ic": ic, "icir": 0.3, "rank_ic": 0.02, "rank_icir": 0.3,
        "ann_return": 0.1, "ir": 0.5, "max_drawdown": 0.1, "sharpe": sharpe,
    }


def _mock_proposer(trace: ExperimentTrace) -> dict:
    return {
        "hypothesis": "mock hypothesis",
        "implementation": "mock_impl",
        "metrics": _make_metrics(),
    }


def _mock_evaluator(proposal: dict, action: str) -> dict:
    return {"ic": 0.05, "icir": 0.4, "rank_ic": 0.04, "rank_icir": 0.4,
            "ann_return": 0.15, "ir": 0.7, "max_drawdown": 0.08, "sharpe": 1.5}


class TestSimpleRDLoopInit:

    @pytest.mark.timeout(30)
    def test_default_init(self):
        loop = SimpleRDLoop(max_iterations=3)
        assert loop.max_iterations == 3
        assert isinstance(loop.bandit, LinearThompsonTwoArm)
        assert isinstance(loop.trace, ExperimentTrace)
        assert loop.sota_metrics == {}

    @pytest.mark.timeout(30)
    def test_custom_components(self):
        bandit = LinearThompsonTwoArm()
        trace = ExperimentTrace(max_history=10)
        loop = SimpleRDLoop(
            bandit=bandit,
            trace=trace,
            factor_proposer=_mock_proposer,
            model_proposer=_mock_proposer,
            evaluator=_mock_evaluator,
        )
        assert loop.bandit is bandit
        assert loop.trace is trace


class TestIterateWithMockProposers:

    @pytest.mark.timeout(30)
    def test_iterate_returns_results(self):
        loop = SimpleRDLoop(
            factor_proposer=_mock_proposer,
            model_proposer=_mock_proposer,
            evaluator=_mock_evaluator,
            max_iterations=5,
        )
        results = loop.iterate()
        assert len(results) == 5
        for r in results:
            assert "round" in r
            assert "action" in r
            assert "reward" in r
            assert "success" in r
            assert "metrics" in r

    @pytest.mark.timeout(30)
    def test_iterate_n_rounds_override(self):
        loop = SimpleRDLoop(
            factor_proposer=_mock_proposer,
            model_proposer=_mock_proposer,
            max_iterations=100,
        )
        results = loop.iterate(n_rounds=3)
        assert len(results) == 3

    @pytest.mark.timeout(30)
    def test_iterate_populates_trace(self):
        loop = SimpleRDLoop(
            factor_proposer=_mock_proposer,
            model_proposer=_mock_proposer,
            max_iterations=4,
        )
        loop.iterate()
        assert len(loop.trace.records) == 4

    @pytest.mark.timeout(30)
    def test_iterate_each_result_has_action(self):
        loop = SimpleRDLoop(
            factor_proposer=_mock_proposer,
            model_proposer=_mock_proposer,
            max_iterations=6,
        )
        results = loop.iterate()
        for r in results:
            assert r["action"] in (ARM_FACTOR, ARM_MODEL)


class TestIterateWithDefaultProposers:

    @pytest.mark.timeout(30)
    def test_default_proposers_no_crash(self):
        loop = SimpleRDLoop(max_iterations=3)
        results = loop.iterate()
        assert len(results) == 3
        for r in results:
            assert isinstance(r["metrics"], dict)
            assert "ic" in r["metrics"]

    @pytest.mark.timeout(30)
    def test_default_factor_proposer_returns_dict(self):
        trace = ExperimentTrace()
        proposal = SimpleRDLoop._default_factor_proposer(trace)
        assert "hypothesis" in proposal
        assert "implementation" in proposal
        assert "metrics" in proposal
        assert "ic" in proposal["metrics"]

    @pytest.mark.timeout(30)
    def test_default_model_proposer_returns_dict(self):
        trace = ExperimentTrace()
        proposal = SimpleRDLoop._default_model_proposer(trace)
        assert "hypothesis" in proposal
        assert "implementation" in proposal
        assert "metrics" in proposal
        assert "sharpe" in proposal["metrics"]


class TestBanditTraceIntegration:

    @pytest.mark.timeout(30)
    def test_bandit_gets_updated(self):
        bandit = LinearThompsonTwoArm()
        loop = SimpleRDLoop(
            bandit=bandit,
            factor_proposer=_mock_proposer,
            model_proposer=_mock_proposer,
            max_iterations=5,
        )
        loop.iterate()
        total = bandit.total_pulls
        assert total[ARM_FACTOR] + total[ARM_MODEL] == 5

    @pytest.mark.timeout(30)
    def test_trace_records_match_results(self):
        trace = ExperimentTrace()
        loop = SimpleRDLoop(
            trace=trace,
            factor_proposer=_mock_proposer,
            model_proposer=_mock_proposer,
            max_iterations=4,
        )
        results = loop.iterate()
        assert len(trace.records) == len(results)
        for rec, res in zip(trace.records, results):
            assert rec.action == res["action"]

    @pytest.mark.timeout(30)
    def test_sota_metrics_updated_on_success(self):
        loop = SimpleRDLoop(
            factor_proposer=_mock_proposer,
            model_proposer=_mock_proposer,
            max_iterations=3,
        )
        loop.iterate()
        assert loop.sota_metrics != {}


class TestMaxIterations:

    @pytest.mark.timeout(30)
    def test_zero_iterations(self):
        loop = SimpleRDLoop(max_iterations=0)
        results = loop.iterate()
        assert results == []

    @pytest.mark.timeout(30)
    def test_single_iteration(self):
        loop = SimpleRDLoop(
            factor_proposer=_mock_proposer,
            model_proposer=_mock_proposer,
            max_iterations=1,
        )
        results = loop.iterate()
        assert len(results) == 1

    @pytest.mark.timeout(30)
    def test_n_rounds_takes_precedence(self):
        loop = SimpleRDLoop(
            factor_proposer=_mock_proposer,
            model_proposer=_mock_proposer,
            max_iterations=10,
        )
        results = loop.iterate(n_rounds=2)
        assert len(results) == 2


class TestErrorHandling:

    @pytest.mark.timeout(30)
    def test_proposer_exception_recorded(self):
        def bad_proposer(trace):
            raise ValueError("boom")

        loop = SimpleRDLoop(
            factor_proposer=bad_proposer,
            model_proposer=bad_proposer,
            max_iterations=3,
        )
        results = loop.iterate()
        assert len(results) == 0
        assert len(loop.trace.records) == 3
        for rec in loop.trace.records:
            assert rec.success is False
            assert rec.reward == -1.0


class TestMetricsToVec:

    @pytest.mark.timeout(30)
    def test_full_metrics(self):
        metrics = _make_metrics()
        vec = SimpleRDLoop._metrics_to_vec(metrics)
        assert isinstance(vec, np.ndarray)
        assert vec.shape == (8,)

    @pytest.mark.timeout(30)
    def test_missing_keys_default_zero(self):
        vec = SimpleRDLoop._metrics_to_vec({"ic": 0.05})
        assert vec[0] == 0.05
        assert vec[1] == 0.0
