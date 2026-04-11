"""Tests for src/dataclean/cleaners/sentiment_cleaner.py"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.dataclean.base import CleanResult
from src.dataclean.cleaners.sentiment_cleaner import SentimentCleaner
from src.dataclean.exceptions import AllProvidersFailedError
from src.dataclean.schemas.sentiment import SentimentExtraction


def _make_valid_dict():
    return {
        "news_sentiment_score": 0.3,
        "hot_sectors": ["银行"],
        "key_events": [{"event": "降准", "impact": "positive", "magnitude": "high"}],
        "hot_stocks": [{"code": "601398.SH", "reason": "利好", "sentiment": 0.5}],
        "gold_price_usd": None,
        "crude_oil_usd": None,
        "fx_usdcny": None,
        "market_mood_text": "整体偏乐观",
    }


class TestSentimentCleanerSchema:
    def test_get_schema(self):
        cleaner = SentimentCleaner()
        assert cleaner.get_schema() is SentimentExtraction


class TestSentimentCleanerDirectDict:
    """Already-structured dict with news_sentiment_score bypasses LLM."""

    def test_valid_dict_passthrough(self):
        cleaner = SentimentCleaner()
        result = cleaner.clean(_make_valid_dict())
        assert isinstance(result, CleanResult)
        assert result.engine == "sentiment"
        assert result.schema_name == "SentimentExtraction"
        assert result.is_fallback is False
        assert result.llm_usage == {}
        assert result.cleaned_data["news_sentiment_score"] == 0.3

    def test_invalid_dict_falls_to_llm(self):
        """Dict with news_sentiment_score but invalid data should try LLM."""
        mock_llm = MagicMock()
        extraction = SentimentExtraction(
            news_sentiment_score=0.0,
            market_mood_text="fallback",
        )
        mock_llm.extract.return_value = (extraction, {"provider": "deepseek"})

        cleaner = SentimentCleaner(llm_client=mock_llm)
        bad_dict = {"news_sentiment_score": 999}  # out of range
        result = cleaner.clean(bad_dict)
        assert result.cleaned_data["news_sentiment_score"] == 0.0
        mock_llm.extract.assert_called_once()


class TestSentimentCleanerLLM:
    def test_llm_extract_success(self):
        mock_llm = MagicMock()
        extraction = SentimentExtraction(
            news_sentiment_score=0.7,
            hot_sectors=["科技"],
            market_mood_text="科技股大涨",
        )
        usage = {
            "provider": "deepseek",
            "model": "deepseek-chat",
            "tokens_in": 500,
            "tokens_out": 200,
            "cost_usd": 0.001,
            "latency_ms": 1500,
            "prompt_version": "sentiment-v2",
        }
        mock_llm.extract.return_value = (extraction, usage)

        cleaner = SentimentCleaner(llm_client=mock_llm)
        result = cleaner.clean("科技股今日全面上涨")
        assert result.engine == "sentiment"
        assert result.cleaned_data["news_sentiment_score"] == 0.7
        assert result.llm_usage["provider"] == "deepseek"
        assert result.is_fallback is False

    def test_llm_extract_all_fail_raises(self):
        mock_llm = MagicMock()
        mock_llm.extract.side_effect = AllProvidersFailedError("全部失败")

        cleaner = SentimentCleaner(llm_client=mock_llm)
        with pytest.raises(AllProvidersFailedError):
            cleaner.clean("some text")

    def test_no_llm_client_raises(self):
        cleaner = SentimentCleaner()
        with pytest.raises(AllProvidersFailedError, match="未配置 LLMClient"):
            cleaner.clean("some text that needs LLM")

    def test_raw_input_truncated(self):
        mock_llm = MagicMock()
        extraction = SentimentExtraction(
            news_sentiment_score=0.0,
            market_mood_text="ok",
        )
        mock_llm.extract.return_value = (extraction, {})

        cleaner = SentimentCleaner(llm_client=mock_llm)
        long_text = "x" * 1000
        result = cleaner.clean(long_text)
        assert len(result.raw_input) <= 500

    def test_prompt_version_passed(self):
        mock_llm = MagicMock()
        extraction = SentimentExtraction(
            news_sentiment_score=0.0,
            market_mood_text="ok",
        )
        mock_llm.extract.return_value = (extraction, {})

        cleaner = SentimentCleaner(llm_client=mock_llm)
        cleaner.clean("test")

        call_kwargs = mock_llm.extract.call_args[1]
        assert call_kwargs["prompt_version"] == "sentiment-v2"
