"""情绪清洗器 — instructor + LLM 做精准情绪抽取

降级路径: LLM 抽取 → RuleCleaner (关键词/正则)
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ValidationError

from src.common.logger import get_logger
from src.dataclean.base import RAW_INPUT_MAX_LEN, BaseCleaner, CleanResult
from src.dataclean.exceptions import AllProvidersFailedError
from src.dataclean.prompts.sentiment_prompt import PROMPT_VERSION, SENTIMENT_PROMPT
from src.dataclean.schemas.sentiment import SentimentExtraction

logger = get_logger(__name__)


class SentimentCleaner(BaseCleaner):
    """LLM 情绪清洗 — instructor 直接返回已校验的 SentimentExtraction"""

    def get_schema(self) -> type[BaseModel]:
        return SentimentExtraction

    def clean(self, raw_data: Any) -> CleanResult:
        if isinstance(raw_data, dict) and "news_sentiment_score" in raw_data:
            try:
                validated = self._validate(raw_data)
            except (ValidationError, TypeError) as e:
                logger.warning("已结构化数据校验失败, 走 LLM: %s", e)
            else:
                return CleanResult(
                    engine="sentiment",
                    schema_name="SentimentExtraction",
                    cleaned_data=validated.model_dump(),
                    raw_input=str(raw_data)[:RAW_INPUT_MAX_LEN],
                    llm_usage={},
                    is_fallback=False,
                )

        if self.llm is None:
            raise AllProvidersFailedError("未配置 LLMClient, 无法执行 LLM 清洗")

        try:
            result, usage = self.llm.extract(
                response_model=SentimentExtraction,
                system_prompt=SENTIMENT_PROMPT,
                user_content=str(raw_data),
                prompt_version=PROMPT_VERSION,
            )
            return CleanResult(
                engine="sentiment",
                schema_name="SentimentExtraction",
                cleaned_data=result.model_dump(),
                raw_input=str(raw_data)[:RAW_INPUT_MAX_LEN],
                llm_usage=usage,
                is_fallback=False,
            )
        except AllProvidersFailedError:
            logger.warning("LLM 全部失败, 降级到规则清洗")
            raise
