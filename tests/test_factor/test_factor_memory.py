"""FactorMemory 单元测试

测试 src/factor/factor_memory.py:
- record 添加记录
- is_duplicate 检测相似描述 (同文本)
- is_duplicate 不同描述返回 False
- search_similar 返回排序结果
- get_successful_patterns
"""
import pytest

from src.factor.factor_memory import FactorMemory, FactorRecord


@pytest.fixture()
def memory():
    return FactorMemory(embedding_dim=128, similarity_threshold=0.85)


@pytest.fixture()
def populated_memory():
    mem = FactorMemory(embedding_dim=128, similarity_threshold=0.85)
    mem.record("momentum_5d", "5日动量因子, 过去5个交易日收益率", status="accepted", metrics={"ic": 0.04})
    mem.record("volatility_20d", "20日波动率因子, 收益率标准差", status="accepted", metrics={"ic": 0.03})
    mem.record("rsi_14d", "14日RSI相对强弱指标", status="rejected", metrics={"ic": 0.005})
    mem.record("volume_ratio", "量比因子, 当日成交量除以5日均量", status="candidate", metrics={"ic": 0.02})
    return mem


class TestFactorRecord:

    @pytest.mark.timeout(30)
    def test_defaults(self):
        rec = FactorRecord(name="test", description="test desc")
        assert rec.name == "test"
        assert rec.description == "test desc"
        assert rec.embedding is None
        assert rec.status == "candidate"
        assert rec.metrics == {}


class TestRecord:

    @pytest.mark.timeout(30)
    def test_record_adds_entry(self, memory: FactorMemory):
        assert len(memory.records) == 0
        memory.record("f1", "测试因子描述")
        assert len(memory.records) == 1
        assert memory.records[0].name == "f1"
        assert memory.records[0].description == "测试因子描述"

    @pytest.mark.timeout(30)
    def test_record_generates_embedding(self, memory: FactorMemory):
        memory.record("f2", "另一个因子")
        assert memory.records[0].embedding is not None
        assert memory.records[0].embedding.shape == (128,)

    @pytest.mark.timeout(30)
    def test_record_preserves_status_and_metrics(self, memory: FactorMemory):
        memory.record("f3", "desc", status="accepted", metrics={"ic": 0.05})
        assert memory.records[0].status == "accepted"
        assert memory.records[0].metrics == {"ic": 0.05}

    @pytest.mark.timeout(30)
    def test_multiple_records(self, memory: FactorMemory):
        memory.record("a", "desc_a")
        memory.record("b", "desc_b")
        memory.record("c", "desc_c")
        assert len(memory.records) == 3


class TestIsDuplicate:

    @pytest.mark.timeout(30)
    def test_same_text_is_duplicate(self, memory: FactorMemory):
        memory.record("original", "5日动量因子")
        assert memory.is_duplicate("5日动量因子") is True

    @pytest.mark.timeout(30)
    def test_very_different_text_not_duplicate(self, memory: FactorMemory):
        memory.record("momentum", "5日动量因子, 过去5个交易日收益率")
        assert memory.is_duplicate("20日波动率因子, 收益率标准差") is False

    @pytest.mark.timeout(30)
    def test_empty_memory_not_duplicate(self, memory: FactorMemory):
        assert memory.is_duplicate("任何因子描述") is False

    @pytest.mark.timeout(30)
    def test_multiple_records_detects_any_match(self, populated_memory: FactorMemory):
        assert populated_memory.is_duplicate("5日动量因子, 过去5个交易日收益率") is True

    @pytest.mark.timeout(30)
    def test_threshold_respected(self):
        mem = FactorMemory(embedding_dim=128, similarity_threshold=0.99999)
        mem.record("strict", "一个非常具体的因子描述内容ABC")
        assert mem.is_duplicate("一个非常具体的因子描述内容XYZ") is False


class TestSearchSimilar:

    @pytest.mark.timeout(30)
    def test_returns_ranked_results(self, populated_memory: FactorMemory):
        results = populated_memory.search_similar("5日动量因子")
        assert len(results) > 0
        assert all(isinstance(r, tuple) and len(r) == 2 for r in results)
        if len(results) >= 2:
            assert results[0][1] >= results[1][1]

    @pytest.mark.timeout(30)
    def test_exact_match_highest_similarity(self, populated_memory: FactorMemory):
        results = populated_memory.search_similar("5日动量因子, 过去5个交易日收益率")
        assert results[0][0] == "momentum_5d"
        assert results[0][1] > 0.99

    @pytest.mark.timeout(30)
    def test_top_k_limits_results(self, populated_memory: FactorMemory):
        results = populated_memory.search_similar("因子", top_k=2)
        assert len(results) <= 2

    @pytest.mark.timeout(30)
    def test_empty_memory_returns_empty(self, memory: FactorMemory):
        results = memory.search_similar("任何描述")
        assert results == []


class TestGetSuccessfulPatterns:

    @pytest.mark.timeout(30)
    def test_returns_accepted_only(self, populated_memory: FactorMemory):
        patterns = populated_memory.get_successful_patterns()
        assert all(p.status == "accepted" for p in patterns)

    @pytest.mark.timeout(30)
    def test_sorted_by_ic(self, populated_memory: FactorMemory):
        patterns = populated_memory.get_successful_patterns()
        assert len(patterns) == 2
        assert patterns[0].metrics["ic"] >= patterns[1].metrics["ic"]
        assert patterns[0].name == "momentum_5d"

    @pytest.mark.timeout(30)
    def test_top_k_limits(self, populated_memory: FactorMemory):
        patterns = populated_memory.get_successful_patterns(top_k=1)
        assert len(patterns) == 1

    @pytest.mark.timeout(30)
    def test_empty_when_no_accepted(self, memory: FactorMemory):
        memory.record("x", "desc", status="rejected")
        assert memory.get_successful_patterns() == []


class TestEmbedAndCosineSimilarity:

    @pytest.mark.timeout(30)
    def test_embed_deterministic(self, memory: FactorMemory):
        e1 = memory._embed("test text")
        e2 = memory._embed("test text")
        assert (e1 == e2).all()

    @pytest.mark.timeout(30)
    def test_embed_normalized(self, memory: FactorMemory):
        import numpy as np
        e = memory._embed("something")
        norm = np.linalg.norm(e)
        assert abs(norm - 1.0) < 1e-6

    @pytest.mark.timeout(30)
    def test_cosine_similarity_identical(self, memory: FactorMemory):
        import numpy as np
        v = np.array([1.0, 0.0, 0.0])
        assert abs(memory._cosine_similarity(v, v) - 1.0) < 1e-6

    @pytest.mark.timeout(30)
    def test_cosine_similarity_orthogonal(self, memory: FactorMemory):
        import numpy as np
        a = np.array([1.0, 0.0])
        b = np.array([0.0, 1.0])
        assert abs(memory._cosine_similarity(a, b)) < 1e-6

    @pytest.mark.timeout(30)
    def test_cosine_similarity_zero_vector(self, memory: FactorMemory):
        import numpy as np
        a = np.zeros(3)
        b = np.array([1.0, 0.0, 0.0])
        assert memory._cosine_similarity(a, b) == 0.0
