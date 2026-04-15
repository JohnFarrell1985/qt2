"""Schema + Prompt 注册表 (P2-33c)

集中管理所有清洗 Schema 和对应的 LLM Prompt, 支持按名称动态查找。
新增 Schema 只需在本文件注册, 无需修改 cleaner 代码。
"""
from __future__ import annotations

from typing import Dict, Optional, Type

from pydantic import BaseModel

from src.common.logger import get_logger

logger = get_logger(__name__)


class CleanerRegistryEntry:
    """注册表条目"""

    __slots__ = ("schema_cls", "prompt_template", "description")

    def __init__(
        self,
        schema_cls: Type[BaseModel],
        prompt_template: str,
        description: str = "",
    ):
        self.schema_cls = schema_cls
        self.prompt_template = prompt_template
        self.description = description


class CleanerRegistry:
    """全局 Schema + Prompt 注册表 — 单例"""

    _instance: Optional[CleanerRegistry] = None
    _entries: Dict[str, CleanerRegistryEntry] = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def register(
        self,
        name: str,
        schema_cls: Type[BaseModel],
        prompt_template: str,
        description: str = "",
    ) -> None:
        self._entries[name] = CleanerRegistryEntry(schema_cls, prompt_template, description)
        logger.debug("Schema 已注册: %s (%s)", name, schema_cls.__name__)

    def get(self, name: str) -> Optional[CleanerRegistryEntry]:
        return self._entries.get(name)

    def list_schemas(self) -> list[dict]:
        return [
            {
                "name": name,
                "schema": entry.schema_cls.__name__,
                "description": entry.description,
            }
            for name, entry in self._entries.items()
        ]

    def get_schema(self, name: str) -> Optional[Type[BaseModel]]:
        entry = self.get(name)
        return entry.schema_cls if entry else None

    def get_prompt(self, name: str) -> Optional[str]:
        entry = self.get(name)
        return entry.prompt_template if entry else None


cleaner_registry = CleanerRegistry()


def _register_defaults():
    """注册内置 Schema"""
    from src.dataclean.schemas.sentiment import SentimentExtraction
    from src.dataclean.schemas.sector_signal import SectorSignalExtraction
    from src.dataclean.schemas.fund_flow import FundFlowExtraction
    from src.dataclean.schemas.macro_indicator import MacroIndicatorExtraction
    from src.dataclean.schemas.stock_event import StockEventExtraction
    from src.dataclean.schemas.risk_alert import RiskAlertExtraction

    cleaner_registry.register(
        "sentiment", SentimentExtraction,
        "分析以下财经新闻/数据, 提取市场情绪信号。",
        "市场情绪结构化抽取",
    )
    cleaner_registry.register(
        "sector_signal", SectorSignalExtraction,
        "分析以下内容, 提取行业轮动信号。",
        "行业轮动信号抽取 (P2-10)",
    )
    cleaner_registry.register(
        "fund_flow", FundFlowExtraction,
        "分析以下内容, 提取资金流向信号。",
        "资金流向抽取 (P2-11)",
    )
    cleaner_registry.register(
        "macro_indicator", MacroIndicatorExtraction,
        "分析以下内容, 提取宏观经济指标。",
        "宏观经济指标抽取 (P2-12)",
    )
    cleaner_registry.register(
        "stock_event", StockEventExtraction,
        "分析以下公告/新闻, 提取影响个股的事件。",
        "个股事件抽取 (P2-33a)",
    )
    cleaner_registry.register(
        "risk_alert", RiskAlertExtraction,
        "分析以下内容, 识别潜在风险预警。",
        "风险预警抽取 (P2-33b)",
    )


_register_defaults()
