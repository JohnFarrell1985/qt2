"""Tests for src/dataclean/cleaners/rule_cleaner.py"""
from __future__ import annotations

from src.dataclean.base import CleanResult
from src.dataclean.cleaners.rule_cleaner import (
    NEGATIVE_KEYWORDS,
    POSITIVE_KEYWORDS,
    STOCK_CODE_PATTERN,
    RuleCleaner,
)


class TestRuleCleaner:
    def test_get_schema_returns_none(self):
        cleaner = RuleCleaner()
        assert cleaner.get_schema() is None

    def test_positive_sentiment(self):
        cleaner = RuleCleaner()
        result = cleaner.clean("银行股涨停, 利好消息, 大涨放量")
        assert isinstance(result, CleanResult)
        assert result.engine == "rule_fallback"
        assert result.schema_name == "partial"
        assert result.is_fallback is True
        assert result.cleaned_data["news_sentiment_score"] > 0

    def test_negative_sentiment(self):
        cleaner = RuleCleaner()
        result = cleaner.clean("股市暴跌, 利空制裁跌停加息")
        assert result.cleaned_data["news_sentiment_score"] < 0

    def test_neutral_sentiment(self):
        cleaner = RuleCleaner()
        result = cleaner.clean("今天天气晴朗, 适合出门散步")
        assert result.cleaned_data["news_sentiment_score"] == 0

    def test_mixed_sentiment(self):
        cleaner = RuleCleaner()
        result = cleaner.clean("银行涨停但白酒暴跌")
        score = result.cleaned_data["news_sentiment_score"]
        assert -1 <= score <= 1

    def test_stock_code_extraction(self):
        cleaner = RuleCleaner()
        result = cleaner.clean("利好 000001.SZ 和 601398.SH 涨停")
        stocks = result.cleaned_data["hot_stocks"]
        codes = [s["code"] for s in stocks]
        assert "000001.SZ" in codes
        assert "601398.SH" in codes

    def test_stock_code_limit_5(self):
        cleaner = RuleCleaner()
        text = " ".join(f"0{i:05d}.SZ" for i in range(10))
        result = cleaner.clean(text)
        assert len(result.cleaned_data["hot_stocks"]) <= 5

    def test_mood_text_fixed(self):
        cleaner = RuleCleaner()
        result = cleaner.clean("any text")
        assert result.cleaned_data["market_mood_text"] == "规则提取(LLM不可用)"

    def test_raw_input_truncated(self):
        cleaner = RuleCleaner()
        result = cleaner.clean("x" * 1000)
        assert len(result.raw_input) <= 500

    def test_llm_usage_empty(self):
        cleaner = RuleCleaner()
        result = cleaner.clean("test")
        assert result.llm_usage == {}


class TestKeywordLists:
    def test_positive_keywords_non_empty(self):
        assert len(POSITIVE_KEYWORDS) > 0

    def test_negative_keywords_non_empty(self):
        assert len(NEGATIVE_KEYWORDS) > 0

    def test_no_overlap(self):
        overlap = set(POSITIVE_KEYWORDS) & set(NEGATIVE_KEYWORDS)
        assert len(overlap) == 0


class TestStockCodePattern:
    def test_sz_code(self):
        assert STOCK_CODE_PATTERN.search("000001.SZ")

    def test_sh_code(self):
        assert STOCK_CODE_PATTERN.search("601398.SH")

    def test_chuangye_code(self):
        assert STOCK_CODE_PATTERN.search("300750.SZ")

    def test_invalid_prefix(self):
        assert STOCK_CODE_PATTERN.search("999001.SZ") is None

    def test_no_match_in_plain_text(self):
        assert STOCK_CODE_PATTERN.search("hello world") is None
