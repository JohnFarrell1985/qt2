"""instructor 驱动的统一 LLM 客户端 — 自动降级 + 指数退避重试 + 成本追踪

降级链: deepseek-chat → qwen3-max → raise AllProvidersFailedError
Reasoner: deepseek-reasoner → deepseek-chat → qwen3-max
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any

import instructor
from openai import (
    APIConnectionError,
    APITimeoutError,
    AuthenticationError,
    OpenAI,
    RateLimitError,
)
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from src.common.logger import get_logger
from src.dataclean.exceptions import AllProvidersFailedError

if TYPE_CHECKING:
    from src.common.config import DatacleanConfig

logger = get_logger(__name__)

TRANSIENT_ERRORS = (RateLimitError, APITimeoutError, APIConnectionError)
PERMANENT_ERRORS = (AuthenticationError,)

COST_PER_M_TOKENS: dict[str, dict[str, float]] = {
    "deepseek-chat": {"input": 0.28, "output": 0.42},
    "deepseek-reasoner": {"input": 0.28, "output": 0.42},
    "qwen3-max": {"input": 1.22, "output": 6.11},
}


class LLMClient:
    """DeepSeek (主) / Qwen3-Max (备) 统一客户端 — instructor 驱动, 自动降级"""

    def __init__(self, settings: DatacleanConfig) -> None:
        self.settings = settings
        self.providers: dict[str, dict[str, Any]] = {}

        if settings.deepseek_api_key:
            base = OpenAI(
                base_url=settings.deepseek_base_url,
                api_key=settings.deepseek_api_key,
                timeout=settings.llm_timeout,
            )
            self.providers["deepseek"] = {
                "client": instructor.from_openai(base),
                "model": settings.deepseek_model,
            }
            self.providers["deepseek-reasoner"] = {
                "client": instructor.from_openai(base),
                "model": settings.deepseek_reasoner_model,
            }

        if settings.qwen_api_key:
            base = OpenAI(
                base_url=settings.qwen_base_url,
                api_key=settings.qwen_api_key,
                timeout=settings.llm_timeout,
            )
            self.providers["qwen"] = {
                "client": instructor.from_openai(base),
                "model": settings.qwen_model,
            }

        self.primary = settings.llm_provider

    def extract(
        self,
        response_model: type[BaseModel],
        system_prompt: str,
        user_content: str,
        *,
        use_reasoner: bool = False,
        temperature: float | None = None,
        max_retries: int = 2,
        prompt_version: str = "",
    ) -> tuple[BaseModel, dict]:
        """调用 LLM 抽取结构化数据, 返回 (validated_model, usage_meta).

        Args:
            response_model: Pydantic Schema (如 SentimentExtraction)
            system_prompt: 静态 system prompt (触发 DeepSeek 缓存)
            user_content: 动态用户输入 (每次不同)
            use_reasoner: True 时使用 deepseek-reasoner (研报/蒸馏标注)
            temperature: 覆盖默认温度, None 时使用 settings.llm_temperature
            max_retries: instructor 内部 Pydantic 校验重试次数
            prompt_version: prompt 版本标签, 附加到 usage_meta

        Returns:
            (validated_model, usage_meta) 元组

        Raises:
            AllProvidersFailedError: 所有 provider 均失败
        """
        if temperature is None:
            temperature = self.settings.llm_temperature

        if use_reasoner:
            order = ["deepseek-reasoner", "deepseek", "qwen"]
        else:
            order = [self.primary] + [
                p for p in ("deepseek", "qwen") if p != self.primary
            ]

        last_error: Exception | None = None
        for provider_name in order:
            if provider_name not in self.providers:
                continue
            try:
                return self._call_with_retry(
                    provider_name,
                    response_model,
                    system_prompt,
                    user_content,
                    temperature,
                    max_retries,
                    prompt_version,
                )
            except PERMANENT_ERRORS as e:
                logger.error("[%s] 永久错误, 跳过: %s", provider_name, e)
                last_error = e
                continue
            except Exception as e:
                logger.warning("[%s] 重试耗尽, 降级: %s", provider_name, e)
                last_error = e
                continue

        raise AllProvidersFailedError(f"所有 LLM 均失败: {last_error}")

    def _call_with_retry(
        self,
        provider_name: str,
        response_model: type[BaseModel],
        system_prompt: str,
        user_content: str,
        temperature: float,
        max_retries: int,
        prompt_version: str,
    ) -> tuple[BaseModel, dict]:
        p = self.providers[provider_name]
        retries = self.settings.llm_max_retries

        @retry(
            stop=stop_after_attempt(retries),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type(TRANSIENT_ERRORS),
            reraise=True,
        )
        def _do() -> tuple[BaseModel, dict]:
            t0 = time.monotonic()
            result = p["client"].chat.completions.create(
                model=p["model"],
                response_model=response_model,
                max_retries=max_retries,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=temperature,
            )
            elapsed_ms = (time.monotonic() - t0) * 1000

            raw = result._raw_response.usage
            tokens_in = raw.prompt_tokens
            tokens_out = raw.completion_tokens
            model_name = p["model"]
            rates = COST_PER_M_TOKENS.get(model_name, {"input": 0, "output": 0})

            usage = {
                "provider": provider_name,
                "model": model_name,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "tokens_cached": getattr(raw, "prompt_cache_hit_tokens", 0),
                "cost_usd": (
                    tokens_in * rates["input"] + tokens_out * rates["output"]
                )
                / 1_000_000,
                "latency_ms": round(elapsed_ms),
                "prompt_version": prompt_version,
            }
            return result, usage

        return _do()
