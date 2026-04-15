"""ExperimentTrace / ExperimentRecord 单元测试

测试 src/ml/experiment_tracker.py:
- append 创建带递增 round_id 的记录
- last_metrics 返回最新
- filter_by_action 过滤
- get_context_for_action 跨类别上下文
- max_history 截断
- save / load 往返
"""
import json
import pytest

from src.ml.experiment_tracker import ExperimentRecord, ExperimentTrace


@pytest.fixture()
def trace():
    return ExperimentTrace(max_history=50)


@pytest.fixture()
def populated_trace():
    t = ExperimentTrace(max_history=50)
    t.append(action="factor", hypothesis="h1", metrics={"ic": 0.02}, reward=0.5, success=True)
    t.append(action="model", hypothesis="h2", metrics={"ic": 0.03}, reward=0.8, success=True)
    t.append(action="factor", hypothesis="h3", metrics={"ic": 0.01}, reward=0.2, success=False)
    t.append(action="model", hypothesis="h4", metrics={"ic": 0.04}, reward=1.0, success=True)
    return t


class TestExperimentRecord:

    @pytest.mark.timeout(30)
    def test_dataclass_fields(self):
        rec = ExperimentRecord(round_id=1, action="factor")
        assert rec.round_id == 1
        assert rec.action == "factor"
        assert rec.hypothesis == ""
        assert rec.metrics == {}
        assert rec.reward == 0.0
        assert rec.success is False

    @pytest.mark.timeout(30)
    def test_with_metrics(self):
        rec = ExperimentRecord(
            round_id=5,
            action="model",
            metrics={"ic": 0.05, "sharpe": 1.2},
            reward=1.5,
            success=True,
        )
        assert rec.metrics["ic"] == 0.05
        assert rec.success is True


class TestExperimentTraceAppend:

    @pytest.mark.timeout(30)
    def test_append_increments_round_id(self, trace: ExperimentTrace):
        r1 = trace.append(action="factor")
        r2 = trace.append(action="model")
        r3 = trace.append(action="factor")
        assert r1.round_id == 1
        assert r2.round_id == 2
        assert r3.round_id == 3

    @pytest.mark.timeout(30)
    def test_append_stores_record(self, trace: ExperimentTrace):
        trace.append(action="factor", hypothesis="test_hyp", metrics={"ic": 0.1})
        assert len(trace.records) == 1
        assert trace.records[0].hypothesis == "test_hyp"
        assert trace.records[0].metrics == {"ic": 0.1}

    @pytest.mark.timeout(30)
    def test_append_returns_record(self, trace: ExperimentTrace):
        rec = trace.append(action="model", reward=2.0, success=True)
        assert isinstance(rec, ExperimentRecord)
        assert rec.reward == 2.0
        assert rec.success is True


class TestExperimentTraceLastMetrics:

    @pytest.mark.timeout(30)
    def test_empty_returns_none(self, trace: ExperimentTrace):
        assert trace.last_metrics() is None

    @pytest.mark.timeout(30)
    def test_returns_latest(self, populated_trace: ExperimentTrace):
        last = populated_trace.last_metrics()
        assert last == {"ic": 0.04}


class TestExperimentTraceFilterByAction:

    @pytest.mark.timeout(30)
    def test_filter_factor(self, populated_trace: ExperimentTrace):
        factors = populated_trace.filter_by_action("factor")
        assert len(factors) == 2
        assert all(r.action == "factor" for r in factors)

    @pytest.mark.timeout(30)
    def test_filter_model(self, populated_trace: ExperimentTrace):
        models = populated_trace.filter_by_action("model")
        assert len(models) == 2
        assert all(r.action == "model" for r in models)

    @pytest.mark.timeout(30)
    def test_filter_unknown_action(self, populated_trace: ExperimentTrace):
        assert populated_trace.filter_by_action("unknown") == []

    @pytest.mark.timeout(30)
    def test_filter_with_limit(self, populated_trace: ExperimentTrace):
        result = populated_trace.filter_by_action("factor", limit=1)
        assert len(result) == 1
        assert result[0].hypothesis == "h3"


class TestGetContextForAction:

    @pytest.mark.timeout(30)
    def test_factor_context_includes_best_model(self, populated_trace: ExperimentTrace):
        ctx = populated_trace.get_context_for_action("factor")
        actions = [c["action"] for c in ctx]
        assert "factor" in actions
        assert "model" in actions

    @pytest.mark.timeout(30)
    def test_model_context_includes_best_factor(self, populated_trace: ExperimentTrace):
        ctx = populated_trace.get_context_for_action("model")
        actions = [c["action"] for c in ctx]
        assert "model" in actions
        assert "factor" in actions

    @pytest.mark.timeout(30)
    def test_context_excludes_timestamp(self, populated_trace: ExperimentTrace):
        ctx = populated_trace.get_context_for_action("factor")
        for c in ctx:
            assert "timestamp" not in c

    @pytest.mark.timeout(30)
    def test_context_returns_dicts(self, populated_trace: ExperimentTrace):
        ctx = populated_trace.get_context_for_action("factor")
        assert all(isinstance(c, dict) for c in ctx)


class TestMaxHistoryTruncation:

    @pytest.mark.timeout(30)
    def test_truncation(self):
        t = ExperimentTrace(max_history=5)
        for i in range(10):
            t.append(action="factor", hypothesis=f"h{i}")
        assert len(t.records) == 5
        assert t.records[0].round_id == 6
        assert t.records[-1].round_id == 10

    @pytest.mark.timeout(30)
    def test_truncation_preserves_latest(self):
        t = ExperimentTrace(max_history=3)
        for i in range(7):
            t.append(action="model", metrics={"ic": float(i)})
        assert len(t.records) == 3
        assert t.records[-1].metrics == {"ic": 6.0}


class TestSaveLoad:

    @pytest.mark.timeout(30)
    def test_save_load_roundtrip(self, populated_trace: ExperimentTrace, tmp_path):
        filepath = str(tmp_path / "trace.json")
        populated_trace.save(filepath)

        loaded = ExperimentTrace()
        loaded.load(filepath)

        assert len(loaded.records) == len(populated_trace.records)
        for orig, restored in zip(populated_trace.records, loaded.records):
            assert orig.round_id == restored.round_id
            assert orig.action == restored.action
            assert orig.hypothesis == restored.hypothesis
            assert orig.metrics == restored.metrics
            assert orig.reward == restored.reward
            assert orig.success == restored.success

    @pytest.mark.timeout(30)
    def test_load_restores_counter(self, populated_trace: ExperimentTrace, tmp_path):
        filepath = str(tmp_path / "trace2.json")
        populated_trace.save(filepath)

        loaded = ExperimentTrace()
        loaded.load(filepath)
        new_rec = loaded.append(action="factor")
        assert new_rec.round_id == 5

    @pytest.mark.timeout(30)
    def test_load_nonexistent_is_noop(self, trace: ExperimentTrace, tmp_path):
        trace.load(str(tmp_path / "nonexistent.json"))
        assert len(trace.records) == 0

    @pytest.mark.timeout(30)
    def test_save_creates_parent_dirs(self, trace: ExperimentTrace, tmp_path):
        filepath = str(tmp_path / "sub" / "dir" / "trace.json")
        trace.append(action="model")
        trace.save(filepath)
        data = json.loads(open(filepath, encoding="utf-8").read())
        assert len(data) == 1


class TestBestRecordAndSuccessRate:

    @pytest.mark.timeout(30)
    def test_get_best_record(self, populated_trace: ExperimentTrace):
        best = populated_trace.get_best_record()
        assert best is not None
        assert best.reward == 1.0

    @pytest.mark.timeout(30)
    def test_get_best_record_by_action(self, populated_trace: ExperimentTrace):
        best = populated_trace.get_best_record(action="factor")
        assert best is not None
        assert best.action == "factor"
        assert best.reward == 0.5

    @pytest.mark.timeout(30)
    def test_get_best_record_empty(self, trace: ExperimentTrace):
        assert trace.get_best_record() is None

    @pytest.mark.timeout(30)
    def test_success_rate(self, populated_trace: ExperimentTrace):
        rate = populated_trace.success_rate()
        assert rate == 0.75

    @pytest.mark.timeout(30)
    def test_success_rate_by_action(self, populated_trace: ExperimentTrace):
        assert populated_trace.success_rate("factor") == 0.5
        assert populated_trace.success_rate("model") == 1.0

    @pytest.mark.timeout(30)
    def test_success_rate_empty(self, trace: ExperimentTrace):
        assert trace.success_rate() == 0.0
