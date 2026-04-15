"""Tests for src/research/rag_engine.py — ResearchRAG & SimpleVectorStore."""
import pytest
from unittest.mock import MagicMock

from src.research.rag_engine import ResearchRAG, SimpleVectorStore, Chunk


class TestChunk:
    @pytest.mark.timeout(30)
    def test_default_metadata(self):
        c = Chunk(text="hello")
        assert c.metadata == {}
        assert c.score == 0.0

    @pytest.mark.timeout(30)
    def test_custom_fields(self):
        c = Chunk(text="t", source="s", score=0.9, metadata={"k": "v"})
        assert c.source == "s"
        assert c.score == 0.9
        assert c.metadata["k"] == "v"


class TestSimpleVectorStore:
    @pytest.mark.timeout(30)
    def test_add_increases_size(self):
        store = SimpleVectorStore()
        assert store.size == 0
        store.add("hello world", source="doc1")
        assert store.size == 1
        store.add("foo bar", source="doc2")
        assert store.size == 2

    @pytest.mark.timeout(30)
    def test_search_returns_matching_chunks(self):
        store = SimpleVectorStore()
        store.add("quant strategy backtest factor")
        store.add("weather temperature forecast")
        store.add("quant factor selection alpha")
        results = store.search("quant strategy", top_k=5)
        assert len(results) > 0
        assert all(isinstance(r, Chunk) for r in results)
        assert results[0].score > 0

    @pytest.mark.timeout(30)
    def test_search_no_match(self):
        store = SimpleVectorStore()
        store.add("apple banana cherry")
        results = store.search("quant factor", top_k=5)
        assert results == []

    @pytest.mark.timeout(30)
    def test_search_top_k_limit(self):
        store = SimpleVectorStore()
        for i in range(20):
            store.add(f"quant doc{i}")
        results = store.search("quant", top_k=3)
        assert len(results) <= 3


class TestResearchRAGIngest:
    @pytest.mark.timeout(30)
    def test_ingest_adds_documents(self):
        rag = ResearchRAG()
        rag.ingest("这是一篇关于量化投资的研报。包含多种因子分析方法。", source="report1")
        assert rag.vector_store.size > 0

    @pytest.mark.timeout(30)
    def test_ingest_chunking(self):
        rag = ResearchRAG()
        text = "x" * 1200
        rag.ingest(text, source="long_doc", chunk_size=500)
        assert rag.vector_store.size == 3

    @pytest.mark.timeout(30)
    def test_ingest_short_text(self):
        rag = ResearchRAG()
        rag.ingest("短文本", source="short")
        assert rag.vector_store.size == 1


class TestResearchRAGSearch:
    @pytest.mark.timeout(30)
    def test_search_returns_results(self):
        rag = ResearchRAG()
        rag.ingest("quant factor strategy research backtest", source="r1")
        rag.ingest("weather forecast system temperature", source="r2")
        result = rag.query("quant strategy")
        assert "quant" in result

    @pytest.mark.timeout(30)
    def test_search_no_docs(self):
        rag = ResearchRAG()
        result = rag.query("quant strategy")
        assert "未找到" in result


class TestResearchRAGAnswer:
    @pytest.mark.timeout(30)
    def test_without_llm_returns_context(self):
        rag = ResearchRAG(llm_client=None)
        rag.ingest("quant factor backtest framework alpha", source="doc1")
        result = rag.query("quant factor")
        assert "相关内容" in result
        assert "doc1" in result

    @pytest.mark.timeout(30)
    def test_with_llm_generates_answer(self):
        mock_llm = MagicMock()
        mock_llm.generate.return_value = "LLM generated answer: quant factors matter"
        rag = ResearchRAG(llm_client=mock_llm)
        rag.ingest("quant research report factor analysis", source="r1")
        result = rag.query("quant factor analysis")
        assert "LLM generated answer" in result
        mock_llm.generate.assert_called_once()

    @pytest.mark.timeout(30)
    def test_llm_error_falls_back_to_context(self):
        mock_llm = MagicMock()
        mock_llm.generate.side_effect = RuntimeError("LLM unavailable")
        rag = ResearchRAG(llm_client=mock_llm)
        rag.ingest("quant investment strategy alpha beta", source="doc")
        result = rag.query("quant investment")
        assert "相关内容" in result
