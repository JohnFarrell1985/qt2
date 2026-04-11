"""Tests for src/dataclean/llm_client.py — LLMClient with mocked instructor/OpenAI"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from openai import AuthenticationError, APITimeoutError, RateLimitError
from pydantic import BaseModel, Field

from src.dataclean.exceptions import AllProvidersFailedError
from src.dataclean.llm_client import COST_PER_M_TOKENS, LLMClient


# ── Test helpers ──────────────────────────────────────────────────

class _FakeSchema(BaseModel):
    score: float = Field(ge=-1, le=1)
    label: str


def _make_settings(**overrides):
    """Create a mock DatacleanConfig with sensible defaults."""
    s = MagicMock()
    s.deepseek_api_key = overrides.get("deepseek_api_key", "sk-deep-test")
    s.deepseek_base_url = overrides.get("deepseek_base_url", "https://api.deepseek.com")
    s.deepseek_model = overrides.get("deepseek_model", "deepseek-chat")
    s.deepseek_reasoner_model = overrides.get("deepseek_reasoner_model", "deepseek-reasoner")
    s.qwen_api_key = overrides.get("qwen_api_key", "sk-qwen-test")
    s.qwen_base_url = overrides.get("qwen_base_url", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    s.qwen_model = overrides.get("qwen_model", "qwen3-max")
    s.llm_timeout = overrides.get("llm_timeout", 30)
    s.llm_provider = overrides.get("llm_provider", "deepseek")
    s.llm_temperature = overrides.get("llm_temperature", 0.1)
    s.llm_max_retries = overrides.get("llm_max_retries", 2)
    return s


def _make_raw_response(prompt_tokens=100, completion_tokens=50, cached_tokens=0):
    """Build a mock _raw_response.usage object."""
    usage = MagicMock()
    usage.prompt_tokens = prompt_tokens
    usage.completion_tokens = completion_tokens
    usage.prompt_cache_hit_tokens = cached_tokens
    return usage


def _make_instructor_result(schema_instance, raw_response_usage):
    """Build a mock instructor result that looks like what instructor returns."""
    result = schema_instance
    result._raw_response = MagicMock()
    result._raw_response.usage = raw_response_usage
    return result


# ── Initialization tests ─────────────────────────────────────────

class TestLLMClientInit:
    @patch("src.dataclean.llm_client.instructor")
    @patch("src.dataclean.llm_client.OpenAI")
    def test_both_providers_configured(self, mock_openai_cls, mock_instructor):
        mock_instructor.from_openai.return_value = MagicMock()
        settings = _make_settings()
        client = LLMClient(settings)
        assert "deepseek" in client.providers
        assert "deepseek-reasoner" in client.providers
        assert "qwen" in client.providers
        assert client.primary == "deepseek"

    @patch("src.dataclean.llm_client.instructor")
    @patch("src.dataclean.llm_client.OpenAI")
    def test_deepseek_only(self, mock_openai_cls, mock_instructor):
        mock_instructor.from_openai.return_value = MagicMock()
        settings = _make_settings(qwen_api_key="")
        client = LLMClient(settings)
        assert "deepseek" in client.providers
        assert "qwen" not in client.providers

    @patch("src.dataclean.llm_client.instructor")
    @patch("src.dataclean.llm_client.OpenAI")
    def test_qwen_only(self, mock_openai_cls, mock_instructor):
        mock_instructor.from_openai.return_value = MagicMock()
        settings = _make_settings(deepseek_api_key="")
        client = LLMClient(settings)
        assert "deepseek" not in client.providers
        assert "qwen" in client.providers

    @patch("src.dataclean.llm_client.instructor")
    @patch("src.dataclean.llm_client.OpenAI")
    def test_no_providers(self, mock_openai_cls, mock_instructor):
        settings = _make_settings(deepseek_api_key="", qwen_api_key="")
        client = LLMClient(settings)
        assert len(client.providers) == 0

    @patch("src.dataclean.llm_client.instructor")
    @patch("src.dataclean.llm_client.OpenAI")
    def test_openai_timeout_passed(self, mock_openai_cls, mock_instructor):
        mock_instructor.from_openai.return_value = MagicMock()
        settings = _make_settings(llm_timeout=60)
        LLMClient(settings)
        call_kwargs = mock_openai_cls.call_args_list[0][1]
        assert call_kwargs["timeout"] == 60


# ── Extract tests ─────────────────────────────────────────────────

class TestExtractSuccess:
    @patch("src.dataclean.llm_client.instructor")
    @patch("src.dataclean.llm_client.OpenAI")
    def test_primary_succeeds(self, mock_openai_cls, mock_instructor):
        fake_result = _FakeSchema(score=0.5, label="positive")
        raw_usage = _make_raw_response(prompt_tokens=200, completion_tokens=80)
        instrumented = _make_instructor_result(fake_result, raw_usage)

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = instrumented
        mock_instructor.from_openai.return_value = mock_client

        settings = _make_settings()
        client = LLMClient(settings)
        result, usage = client.extract(
            response_model=_FakeSchema,
            system_prompt="test prompt",
            user_content="test content",
            prompt_version="test-v1",
        )
        assert result.score == 0.5
        assert usage["provider"] == "deepseek"
        assert usage["model"] == "deepseek-chat"
        assert usage["tokens_in"] == 200
        assert usage["tokens_out"] == 80
        assert usage["prompt_version"] == "test-v1"
        assert usage["cost_usd"] > 0

    @patch("src.dataclean.llm_client.instructor")
    @patch("src.dataclean.llm_client.OpenAI")
    def test_cost_calculation(self, mock_openai_cls, mock_instructor):
        fake_result = _FakeSchema(score=0.0, label="neutral")
        raw_usage = _make_raw_response(prompt_tokens=1000, completion_tokens=500)
        instrumented = _make_instructor_result(fake_result, raw_usage)

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = instrumented
        mock_instructor.from_openai.return_value = mock_client

        settings = _make_settings()
        client = LLMClient(settings)
        _, usage = client.extract(_FakeSchema, "prompt", "content")

        rates = COST_PER_M_TOKENS["deepseek-chat"]
        expected = (1000 * rates["input"] + 500 * rates["output"]) / 1_000_000
        assert abs(usage["cost_usd"] - expected) < 1e-10

    @patch("src.dataclean.llm_client.instructor")
    @patch("src.dataclean.llm_client.OpenAI")
    def test_cached_tokens_tracked(self, mock_openai_cls, mock_instructor):
        fake_result = _FakeSchema(score=0.0, label="neutral")
        raw_usage = _make_raw_response(prompt_tokens=500, completion_tokens=100, cached_tokens=400)
        instrumented = _make_instructor_result(fake_result, raw_usage)

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = instrumented
        mock_instructor.from_openai.return_value = mock_client

        settings = _make_settings()
        client = LLMClient(settings)
        _, usage = client.extract(_FakeSchema, "p", "c")
        assert usage["tokens_cached"] == 400


class TestExtractDegradation:
    @patch("src.dataclean.llm_client.instructor")
    @patch("src.dataclean.llm_client.OpenAI")
    def test_primary_fails_fallback_to_qwen(self, mock_openai_cls, mock_instructor):
        fake_result = _FakeSchema(score=-0.5, label="negative")
        raw_usage = _make_raw_response()
        instrumented = _make_instructor_result(fake_result, raw_usage)

        ds_client = MagicMock()
        ds_client.chat.completions.create.side_effect = RateLimitError(
            message="rate limited",
            response=MagicMock(status_code=429),
            body=None,
        )

        qwen_client = MagicMock()
        qwen_client.chat.completions.create.return_value = instrumented

        call_count = [0]

        def _from_openai(base):
            call_count[0] += 1
            if call_count[0] <= 2:
                return ds_client
            return qwen_client

        mock_instructor.from_openai.side_effect = _from_openai

        settings = _make_settings(llm_max_retries=1)
        client = LLMClient(settings)
        result, usage = client.extract(_FakeSchema, "p", "c")
        assert usage["provider"] == "qwen"

    @patch("src.dataclean.llm_client.instructor")
    @patch("src.dataclean.llm_client.OpenAI")
    def test_auth_error_skips_immediately(self, mock_openai_cls, mock_instructor):
        fake_result = _FakeSchema(score=0.0, label="neutral")
        raw_usage = _make_raw_response()
        instrumented = _make_instructor_result(fake_result, raw_usage)

        ds_client = MagicMock()
        ds_client.chat.completions.create.side_effect = AuthenticationError(
            message="invalid key",
            response=MagicMock(status_code=401),
            body=None,
        )

        qwen_client = MagicMock()
        qwen_client.chat.completions.create.return_value = instrumented

        call_count = [0]

        def _from_openai(base):
            call_count[0] += 1
            if call_count[0] <= 2:
                return ds_client
            return qwen_client

        mock_instructor.from_openai.side_effect = _from_openai

        settings = _make_settings()
        client = LLMClient(settings)
        result, usage = client.extract(_FakeSchema, "p", "c")
        assert usage["provider"] == "qwen"
        ds_client.chat.completions.create.assert_called_once()

    @patch("src.dataclean.llm_client.instructor")
    @patch("src.dataclean.llm_client.OpenAI")
    def test_all_fail_raises(self, mock_openai_cls, mock_instructor):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = APITimeoutError(request=MagicMock())
        mock_instructor.from_openai.return_value = mock_client

        settings = _make_settings(llm_max_retries=1)
        client = LLMClient(settings)
        with pytest.raises(AllProvidersFailedError, match="所有 LLM 均失败"):
            client.extract(_FakeSchema, "p", "c")

    @patch("src.dataclean.llm_client.instructor")
    @patch("src.dataclean.llm_client.OpenAI")
    def test_no_providers_raises(self, mock_openai_cls, mock_instructor):
        settings = _make_settings(deepseek_api_key="", qwen_api_key="")
        client = LLMClient(settings)
        with pytest.raises(AllProvidersFailedError):
            client.extract(_FakeSchema, "p", "c")


class TestExtractReasonerRouting:
    @patch("src.dataclean.llm_client.instructor")
    @patch("src.dataclean.llm_client.OpenAI")
    def test_reasoner_order(self, mock_openai_cls, mock_instructor):
        fake_result = _FakeSchema(score=0.9, label="positive")
        raw_usage = _make_raw_response()
        instrumented = _make_instructor_result(fake_result, raw_usage)

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = instrumented
        mock_instructor.from_openai.return_value = mock_client

        settings = _make_settings()
        client = LLMClient(settings)
        _, usage = client.extract(_FakeSchema, "p", "c", use_reasoner=True)
        assert usage["model"] == "deepseek-reasoner"

    @patch("src.dataclean.llm_client.instructor")
    @patch("src.dataclean.llm_client.OpenAI")
    def test_default_temperature_from_settings(self, mock_openai_cls, mock_instructor):
        fake_result = _FakeSchema(score=0.0, label="neutral")
        raw_usage = _make_raw_response()
        instrumented = _make_instructor_result(fake_result, raw_usage)

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = instrumented
        mock_instructor.from_openai.return_value = mock_client

        settings = _make_settings(llm_temperature=0.5)
        client = LLMClient(settings)
        client.extract(_FakeSchema, "p", "c")

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["temperature"] == 0.5

    @patch("src.dataclean.llm_client.instructor")
    @patch("src.dataclean.llm_client.OpenAI")
    def test_override_temperature(self, mock_openai_cls, mock_instructor):
        fake_result = _FakeSchema(score=0.0, label="neutral")
        raw_usage = _make_raw_response()
        instrumented = _make_instructor_result(fake_result, raw_usage)

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = instrumented
        mock_instructor.from_openai.return_value = mock_client

        settings = _make_settings(llm_temperature=0.1)
        client = LLMClient(settings)
        client.extract(_FakeSchema, "p", "c", temperature=0.9)

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        assert call_kwargs["temperature"] == 0.9


class TestCostPerMTokens:
    def test_deepseek_chat_rates(self):
        rates = COST_PER_M_TOKENS["deepseek-chat"]
        assert rates["input"] == 0.28
        assert rates["output"] == 0.42

    def test_qwen_rates(self):
        rates = COST_PER_M_TOKENS["qwen3-max"]
        assert rates["input"] == 1.22
        assert rates["output"] == 6.11

    def test_unknown_model_defaults_zero(self):
        rates = COST_PER_M_TOKENS.get("unknown-model", {"input": 0, "output": 0})
        assert rates["input"] == 0
