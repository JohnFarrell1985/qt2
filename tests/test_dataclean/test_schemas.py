"""Tests for src/dataclean/schemas/sentiment.py"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.dataclean.schemas.sentiment import (
    HotStock,
    KeyEvent,
    SentimentExtraction,
)


class TestKeyEvent:
    def test_valid(self):
        e = KeyEvent(event="央行降准", impact="positive", magnitude="high")
        assert e.event == "央行降准"
        assert e.impact == "positive"
        assert e.magnitude == "high"

    def test_missing_field(self):
        with pytest.raises(ValidationError):
            KeyEvent(event="test")  # type: ignore[call-arg]


class TestHotStock:
    def test_valid(self):
        s = HotStock(code="600519.SH", reason="涨停", sentiment=0.8)
        assert s.sentiment == 0.8

    def test_sentiment_out_of_range_high(self):
        with pytest.raises(ValidationError, match="less than or equal to 1"):
            HotStock(code="600519.SH", reason="test", sentiment=1.5)

    def test_sentiment_out_of_range_low(self):
        with pytest.raises(ValidationError, match="greater than or equal to -1"):
            HotStock(code="600519.SH", reason="test", sentiment=-1.5)

    def test_boundary_values(self):
        s1 = HotStock(code="000001.SZ", reason="test", sentiment=-1.0)
        s2 = HotStock(code="000001.SZ", reason="test", sentiment=1.0)
        assert s1.sentiment == -1.0
        assert s2.sentiment == 1.0


class TestSentimentExtraction:
    def test_full_valid(self):
        data = {
            "news_sentiment_score": 0.5,
            "hot_sectors": ["银行", "券商"],
            "key_events": [
                {"event": "降准", "impact": "positive", "magnitude": "high"},
            ],
            "hot_stocks": [
                {"code": "601398.SH", "reason": "银行", "sentiment": 0.6},
            ],
            "gold_price_usd": 2300.0,
            "crude_oil_usd": 80.0,
            "fx_usdcny": 7.25,
            "market_mood_text": "整体偏乐观",
        }
        result = SentimentExtraction(**data)
        assert result.news_sentiment_score == 0.5
        assert len(result.hot_sectors) == 2
        assert result.key_events[0].event == "降准"
        assert result.hot_stocks[0].code == "601398.SH"
        assert result.gold_price_usd == 2300.0

    def test_minimal_valid(self):
        result = SentimentExtraction(
            news_sentiment_score=0.0,
            market_mood_text="平淡",
        )
        assert result.hot_sectors == []
        assert result.key_events == []
        assert result.hot_stocks == []
        assert result.gold_price_usd is None

    def test_score_out_of_range(self):
        with pytest.raises(ValidationError):
            SentimentExtraction(news_sentiment_score=2.0, market_mood_text="x")

    def test_mood_text_too_long(self):
        with pytest.raises(ValidationError):
            SentimentExtraction(
                news_sentiment_score=0.0,
                market_mood_text="x" * 101,
            )

    def test_model_dump(self):
        result = SentimentExtraction(
            news_sentiment_score=-0.3,
            hot_sectors=["白酒"],
            market_mood_text="白酒板块承压",
        )
        d = result.model_dump()
        assert isinstance(d, dict)
        assert d["news_sentiment_score"] == -0.3
        assert d["hot_sectors"] == ["白酒"]

    def test_model_json_schema(self):
        schema = SentimentExtraction.model_json_schema()
        assert "properties" in schema
        assert "news_sentiment_score" in schema["properties"]

    def test_optional_fields_none(self):
        result = SentimentExtraction(
            news_sentiment_score=0.0,
            market_mood_text="ok",
            gold_price_usd=None,
            crude_oil_usd=None,
            fx_usdcny=None,
        )
        assert result.gold_price_usd is None
        assert result.crude_oil_usd is None
        assert result.fx_usdcny is None
