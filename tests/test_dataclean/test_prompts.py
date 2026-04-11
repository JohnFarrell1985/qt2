"""Tests for src/dataclean/prompts/sentiment_prompt.py"""
from __future__ import annotations

from src.dataclean.prompts.sentiment_prompt import (
    PROMPT_VERSION,
    SENTIMENT_PROMPT,
)


class TestSentimentPrompt:
    def test_prompt_version_format(self):
        assert PROMPT_VERSION == "sentiment-v2"

    def test_prompt_is_string(self):
        assert isinstance(SENTIMENT_PROMPT, str)
        assert len(SENTIMENT_PROMPT) > 100

    def test_prompt_contains_schema(self):
        assert "news_sentiment_score" in SENTIMENT_PROMPT
        assert "hot_sectors" in SENTIMENT_PROMPT
        assert "key_events" in SENTIMENT_PROMPT

    def test_prompt_contains_rules(self):
        assert "## 规则" in SENTIMENT_PROMPT

    def test_prompt_contains_negative_constraints(self):
        assert "## 禁止" in SENTIMENT_PROMPT
        assert "不要编造" in SENTIMENT_PROMPT

    def test_prompt_contains_example(self):
        assert "## 示例" in SENTIMENT_PROMPT
        assert "央行降准50bp" in SENTIMENT_PROMPT

    def test_prompt_is_static(self):
        """Prompt should be identical across calls (no dynamic content)."""
        p1 = SENTIMENT_PROMPT
        p2 = SENTIMENT_PROMPT
        assert p1 is p2

    def test_prompt_has_json_schema_section(self):
        assert "## JSON Schema" in SENTIMENT_PROMPT
        assert "properties" in SENTIMENT_PROMPT

    def test_no_dynamic_content(self):
        """No timestamps, UUIDs, or other dynamic content that breaks caching."""
        import re

        assert "datetime.now" not in SENTIMENT_PROMPT
        assert "uuid" not in SENTIMENT_PROMPT.lower()
        iso_pattern = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
        assert not iso_pattern.search(SENTIMENT_PROMPT)
