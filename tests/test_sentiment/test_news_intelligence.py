"""Tests for src/sentiment/news_intelligence.py — NewsIntelligenceAgent."""
import pytest
from unittest.mock import MagicMock

from src.sentiment.news_intelligence import NewsIntelligenceAgent


EXPECTED_RESULT_KEYS = {
    "event_type", "impact_scope", "affected_codes", "affected_sectors",
    "sentiment_score", "impact_magnitude", "time_horizon",
    "confidence", "reasoning",
}


@pytest.fixture
def sample_news():
    return [
        {"title": "利好消息：某公司突破新高", "content": "市场上涨", "source": "test"},
        {"title": "暴跌：利空消息减持", "content": "下跌继续", "source": "test"},
        {"title": "平稳运行", "content": "今日无大事", "source": "test"},
    ]


class TestAnalyzeSingleRuleFallback:
    @pytest.mark.timeout(30)
    def test_positive_rule_analyze(self):
        agent = NewsIntelligenceAgent()
        result = agent._rule_analyze({"title": "利好消息 上涨 增持"})
        assert result["sentiment_score"] == 0.3
        assert result["event_type"] == "news"
        assert set(result.keys()) >= EXPECTED_RESULT_KEYS

    @pytest.mark.timeout(30)
    def test_negative_rule_analyze(self):
        agent = NewsIntelligenceAgent()
        result = agent._rule_analyze({"title": "暴跌 利空 减持"})
        assert result["sentiment_score"] == -0.3

    @pytest.mark.timeout(30)
    def test_neutral_rule_analyze(self):
        agent = NewsIntelligenceAgent()
        result = agent._rule_analyze({"title": "今天天气不错"})
        assert result["sentiment_score"] == 0.0

    @pytest.mark.timeout(30)
    def test_deep_analyze_without_llm(self):
        agent = NewsIntelligenceAgent()
        result = agent._deep_analyze({"title": "利好突破", "content": "详情"})
        assert result is not None
        assert result["sentiment_score"] == 0.3

    @pytest.mark.timeout(30)
    def test_deep_analyze_empty_text_returns_none(self):
        agent = NewsIntelligenceAgent()
        result = agent._deep_analyze({"title": "", "content": ""})
        assert result is None


class TestAnalyzeBatch:
    @pytest.mark.timeout(30)
    def test_returns_list(self, sample_news):
        agent = NewsIntelligenceAgent()
        results = agent.analyze(sample_news)
        assert isinstance(results, list)
        assert len(results) == 3

    @pytest.mark.timeout(30)
    def test_results_have_expected_structure(self, sample_news):
        agent = NewsIntelligenceAgent()
        results = agent.analyze(sample_news)
        for r in results:
            assert "event_type" in r
            assert "sentiment_score" in r
            assert "impact_magnitude" in r
            assert "confidence" in r

    @pytest.mark.timeout(30)
    def test_empty_input_returns_empty(self):
        agent = NewsIntelligenceAgent()
        results = agent.analyze([])
        assert results == []

    @pytest.mark.timeout(30)
    def test_with_llm_uses_llm(self, sample_news):
        mock_llm = MagicMock()
        mock_llm.extract.return_value = {
            "event_type": "policy",
            "impact_scope": "market",
            "affected_codes": [],
            "affected_sectors": ["银行"],
            "sentiment_score": 0.5,
            "impact_magnitude": "high",
            "time_horizon": "medium",
            "confidence": 0.8,
            "reasoning": "LLM 分析结果",
        }
        agent = NewsIntelligenceAgent(llm_client=mock_llm)
        results = agent.analyze(sample_news)
        assert len(results) == 3
        assert all(r["event_type"] == "policy" for r in results)

    @pytest.mark.timeout(30)
    def test_llm_failure_falls_back(self, sample_news):
        mock_llm = MagicMock()
        mock_llm.extract.side_effect = RuntimeError("LLM error")
        agent = NewsIntelligenceAgent(llm_client=mock_llm)
        results = agent.analyze(sample_news)
        assert len(results) == 3
        assert all(r["event_type"] == "news" for r in results)


class TestPreFilter:
    @pytest.mark.timeout(30)
    def test_no_finbert_passes_all(self, sample_news):
        agent = NewsIntelligenceAgent()
        filtered = agent._pre_filter(sample_news)
        assert len(filtered) == len(sample_news)

    @pytest.mark.timeout(30)
    def test_finbert_filters_neutral(self, sample_news):
        mock_finbert = MagicMock()
        mock_finbert.predict.return_value = {"label": "neutral", "confidence": 0.9}
        agent = NewsIntelligenceAgent(finbert_model=mock_finbert)
        filtered = agent._pre_filter(sample_news, threshold=0.3)
        assert len(filtered) == 0

    @pytest.mark.timeout(30)
    def test_finbert_keeps_non_neutral(self, sample_news):
        mock_finbert = MagicMock()
        mock_finbert.predict.return_value = {"label": "positive", "confidence": 0.8}
        agent = NewsIntelligenceAgent(finbert_model=mock_finbert)
        filtered = agent._pre_filter(sample_news)
        assert len(filtered) == len(sample_news)

    @pytest.mark.timeout(30)
    def test_finbert_error_keeps_item(self):
        mock_finbert = MagicMock()
        mock_finbert.predict.side_effect = RuntimeError("model error")
        agent = NewsIntelligenceAgent(finbert_model=mock_finbert)
        filtered = agent._pre_filter([{"title": "test", "content": "test"}])
        assert len(filtered) == 1
