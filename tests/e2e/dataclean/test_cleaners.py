"""E2E: 清洗器完整链路 (真实 API)

验证 SentimentCleaner → LLM 抽取 → CleanResult 完整路径,
以及 RuleCleaner / PassthroughCleaner 的端到端行为。

API 调用次数: 仅 1 次 (SentimentCleaner), 其余不调 LLM
"""
import pytest

from src.dataclean.base import CleanResult
from tests.e2e.dataclean.conftest import skip_on_auth_failure


class TestSentimentCleanerE2E:
    """SentimentCleaner 真实 LLM 调用"""

    @pytest.mark.timeout(60)
    @skip_on_auth_failure
    def test_full_clean_pipeline(self, llm_client, dataclean_settings):
        """完整: 原始文本 → SentimentCleaner → CleanResult"""
        if not dataclean_settings.deepseek_api_key and not dataclean_settings.qwen_api_key:
            pytest.skip("无可用 API key")

        from src.dataclean.cleaners.sentiment_cleaner import SentimentCleaner
        from tests.e2e.dataclean.conftest import SAMPLE_NEWS_CN

        cleaner = SentimentCleaner(llm_client=llm_client)
        result = cleaner.clean(SAMPLE_NEWS_CN)

        assert isinstance(result, CleanResult)
        assert result.engine == "sentiment"
        assert result.schema_name == "SentimentExtraction"
        assert result.is_fallback is False
        assert -1 <= result.cleaned_data["news_sentiment_score"] <= 1
        assert result.llm_usage["provider"] in ("deepseek", "qwen")
        assert result.llm_usage["cost_usd"] >= 0
        assert result.llm_usage["tokens_in"] > 0
        assert len(result.raw_input) <= 500

    @pytest.mark.timeout(10)
    def test_already_structured_bypasses_llm(self, llm_client):
        """已结构化 dict 应直接通过, 不调 LLM"""
        from src.dataclean.cleaners.sentiment_cleaner import SentimentCleaner

        structured = {
            "news_sentiment_score": 0.5,
            "hot_sectors": ["银行"],
            "key_events": [],
            "hot_stocks": [],
            "market_mood_text": "偏乐观",
        }
        cleaner = SentimentCleaner(llm_client=llm_client)
        result = cleaner.clean(structured)

        assert result.engine == "sentiment"
        assert result.llm_usage == {}
        assert result.cleaned_data["news_sentiment_score"] == 0.5


class TestRuleCleanerE2E:
    """RuleCleaner 端到端 — 无 API 调用"""

    def test_positive_news(self):
        from src.dataclean.cleaners.rule_cleaner import RuleCleaner

        cleaner = RuleCleaner()
        result = cleaner.clean(
            "银行股集体涨停, 利好消息频传, 北向资金大量买入, 市场突破新高"
        )

        assert isinstance(result, CleanResult)
        assert result.is_fallback is True
        assert result.cleaned_data["news_sentiment_score"] > 0
        assert result.llm_usage == {}

    def test_negative_news(self):
        from src.dataclean.cleaners.rule_cleaner import RuleCleaner

        cleaner = RuleCleaner()
        result = cleaner.clean("暴跌利空制裁跌停, 外资大幅减持")

        assert result.cleaned_data["news_sentiment_score"] < 0

    def test_extracts_stock_codes(self):
        from src.dataclean.cleaners.rule_cleaner import RuleCleaner

        cleaner = RuleCleaner()
        result = cleaner.clean("利好 601398.SH 工商银行涨停, 000001.SZ 平安银行跟涨")

        codes = [s["code"] for s in result.cleaned_data["hot_stocks"]]
        assert "601398.SH" in codes
        assert "000001.SZ" in codes


class TestPassthroughCleanerE2E:
    """PassthroughCleaner 端到端 — 无 API 调用"""

    def test_dict_passthrough(self):
        from src.dataclean.cleaners.passthrough_cleaner import PassthroughCleaner

        cleaner = PassthroughCleaner()
        data = {"symbol": "SPX", "close_price": 5200.0, "change_pct": 0.35}
        result = cleaner.clean(data)

        assert result.engine == "passthrough"
        assert result.cleaned_data == data
        assert result.is_fallback is False

    def test_list_passthrough(self):
        from src.dataclean.cleaners.passthrough_cleaner import PassthroughCleaner

        cleaner = PassthroughCleaner()
        data = [
            {"symbol": "SPX", "close": 5200},
            {"symbol": "IXIC", "close": 16400},
        ]
        result = cleaner.clean(data)
        assert result.cleaned_data == data

    def test_dataframe_passthrough(self):
        pd = pytest.importorskip("pandas")
        from src.dataclean.cleaners.passthrough_cleaner import PassthroughCleaner

        df = pd.DataFrame({
            "code": ["000001.SZ", "601398.SH"],
            "close": [15.3, 5.8],
        })
        cleaner = PassthroughCleaner()
        result = cleaner.clean(df)

        assert isinstance(result.cleaned_data, list)
        assert len(result.cleaned_data) == 2
        assert result.cleaned_data[0]["code"] == "000001.SZ"


class TestDegradationChain:
    """降级链: LLM 不可用 → RuleCleaner 兜底"""

    def test_no_api_key_falls_to_rule(self):
        """无 API key 时 SentimentCleaner 应抛异常, 上游可降级到 RuleCleaner"""
        from src.dataclean.cleaners.sentiment_cleaner import SentimentCleaner
        from src.dataclean.cleaners.rule_cleaner import RuleCleaner
        from src.dataclean.exceptions import AllProvidersFailedError

        text = "银行股涨停利好, 000001.SZ 大涨"

        sentiment_cleaner = SentimentCleaner()
        try:
            result = sentiment_cleaner.clean(text)
        except AllProvidersFailedError:
            rule_cleaner = RuleCleaner()
            result = rule_cleaner.clean(text)

        assert isinstance(result, CleanResult)
        assert result.is_fallback is True
        assert result.cleaned_data["news_sentiment_score"] > 0
