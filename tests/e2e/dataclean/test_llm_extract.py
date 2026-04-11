"""E2E: LLMClient 真实 API 调用

每个测试真实调用一次 DeepSeek/Qwen API, 验证:
  - instructor 结构化抽取返回已校验的 Pydantic 对象
  - usage_meta 包含 provider / model / tokens / cost / latency
  - DeepSeek Prefix Caching (tokens_cached >= 0)

注意: 每次运行约消耗 ~0.01 元 (DeepSeek V3 极低成本)
"""
import pytest

from src.dataclean.schemas.sentiment import SentimentExtraction
from src.dataclean.prompts.sentiment_prompt import SENTIMENT_PROMPT, PROMPT_VERSION
from tests.e2e.dataclean.conftest import skip_on_auth_failure


class TestDeepSeekExtract:
    """真实调用 DeepSeek API"""

    @pytest.mark.timeout(60)
    @skip_on_auth_failure
    def test_sentiment_extraction(self, llm_client, dataclean_settings):
        if not dataclean_settings.deepseek_api_key:
            pytest.skip("DEEPSEEK_API_KEY 未配置")

        from tests.e2e.dataclean.conftest import SAMPLE_NEWS_CN

        result, usage = llm_client.extract(
            response_model=SentimentExtraction,
            system_prompt=SENTIMENT_PROMPT,
            user_content=SAMPLE_NEWS_CN,
            prompt_version=PROMPT_VERSION,
        )

        assert isinstance(result, SentimentExtraction)
        assert -1 <= result.news_sentiment_score <= 1
        assert len(result.market_mood_text) > 0
        assert len(result.market_mood_text) <= 100

        assert usage["provider"] == "deepseek"
        assert usage["model"] == dataclean_settings.deepseek_model
        assert usage["tokens_in"] > 0
        assert usage["tokens_out"] > 0
        assert usage["cost_usd"] > 0
        assert usage["latency_ms"] > 0
        assert usage["prompt_version"] == PROMPT_VERSION
        assert "tokens_cached" in usage

    @pytest.mark.timeout(60)
    @skip_on_auth_failure
    def test_extracts_stock_codes(self, llm_client, dataclean_settings):
        """验证 LLM 能正确提取原文中提到的股票代码"""
        if not dataclean_settings.deepseek_api_key:
            pytest.skip("DEEPSEEK_API_KEY 未配置")

        from tests.e2e.dataclean.conftest import SAMPLE_NEWS_CN

        result, _ = llm_client.extract(
            response_model=SentimentExtraction,
            system_prompt=SENTIMENT_PROMPT,
            user_content=SAMPLE_NEWS_CN,
            prompt_version=PROMPT_VERSION,
        )

        codes = [s.code for s in result.hot_stocks]
        assert any("601398" in c for c in codes) or any("600519" in c for c in codes), (
            f"应至少提取到 601398.SH 或 600519.SH, 实际: {codes}"
        )

    @pytest.mark.timeout(60)
    @skip_on_auth_failure
    def test_neutral_news_low_score(self, llm_client, dataclean_settings):
        """中性新闻应返回接近 0 的情绪分"""
        if not dataclean_settings.deepseek_api_key:
            pytest.skip("DEEPSEEK_API_KEY 未配置")

        from tests.e2e.dataclean.conftest import SAMPLE_NEWS_NEUTRAL

        result, _ = llm_client.extract(
            response_model=SentimentExtraction,
            system_prompt=SENTIMENT_PROMPT,
            user_content=SAMPLE_NEWS_NEUTRAL,
            prompt_version=PROMPT_VERSION,
        )

        assert -0.4 <= result.news_sentiment_score <= 0.4, (
            f"中性新闻情绪分应接近 0, 实际: {result.news_sentiment_score}"
        )


class TestQwenExtract:
    """真实调用 Qwen API (降级兜底验证)"""

    @pytest.mark.timeout(60)
    @skip_on_auth_failure
    def test_qwen_sentiment_extraction(self, dataclean_settings):
        """直接构造仅 Qwen 的 client, 验证 Qwen 也能正确抽取"""
        if not dataclean_settings.qwen_api_key:
            pytest.skip("QWEN_API_KEY 未配置")

        from unittest.mock import MagicMock
        from tests.e2e.dataclean.conftest import SAMPLE_NEWS_CN

        qwen_only = MagicMock()
        qwen_only.deepseek_api_key = ""
        qwen_only.qwen_api_key = dataclean_settings.qwen_api_key
        qwen_only.qwen_base_url = dataclean_settings.qwen_base_url
        qwen_only.qwen_model = dataclean_settings.qwen_model
        qwen_only.llm_timeout = dataclean_settings.llm_timeout
        qwen_only.llm_provider = "qwen"
        qwen_only.llm_temperature = dataclean_settings.llm_temperature
        qwen_only.llm_max_retries = dataclean_settings.llm_max_retries

        from src.dataclean.llm_client import LLMClient

        client = LLMClient(qwen_only)
        result, usage = client.extract(
            response_model=SentimentExtraction,
            system_prompt=SENTIMENT_PROMPT,
            user_content=SAMPLE_NEWS_CN,
            prompt_version=PROMPT_VERSION,
        )

        assert isinstance(result, SentimentExtraction)
        assert usage["provider"] == "qwen"
        assert usage["tokens_in"] > 0
        assert usage["cost_usd"] > 0
