"""清洗器抽象基类 + 标准化输出结构"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from src.dataclean.llm_client import LLMClient

RAW_INPUT_MAX_LEN: int = 500
"""raw_input 字段截断长度 — 所有 cleaner 统一引用"""


@dataclass
class CleanResult:
    """清洗结果标准格式 — 所有清洗器统一返回此结构"""

    engine: str
    """引擎标识: "sentiment" / "stock_event" / "sector_signal" / "passthrough" / "rule_fallback" """

    schema_name: str
    """Schema 名称: "SentimentExtraction" / "StockEventExtraction" / "raw" / "partial" """

    cleaned_data: dict | list
    """校验通过的结构化数据 (Pydantic model_dump 输出)"""

    raw_input: str
    """原始输入文本 (截断到合理长度)"""

    llm_usage: dict = field(default_factory=dict)
    """LLM 调用元数据: provider / model / tokens_in / tokens_out / tokens_cached / cost_usd / latency_ms"""

    is_fallback: bool = False
    """是否使用了降级方案"""


class BaseCleaner(ABC):
    """所有清洗器的基类 — 统一接口, 可选 LLM 依赖"""

    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm = llm_client

    @abstractmethod
    def clean(self, raw_data: Any) -> CleanResult:
        """将原始数据清洗为结构化输出"""
        ...

    @abstractmethod
    def get_schema(self) -> type[BaseModel] | None:
        """返回该清洗器使用的 Pydantic Schema, 直通/规则清洗器返回 None"""
        ...

    def _validate(self, data: dict) -> BaseModel:
        """Pydantic 双重校验 — 用 Schema 再次验证数据完整性"""
        schema = self.get_schema()
        if schema is None:
            raise TypeError("当前清洗器未定义 Schema, 无法调用 _validate")
        return schema(**data)
