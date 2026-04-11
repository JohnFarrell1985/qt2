"""直通清洗器 — 已结构化数据 (akshare DataFrame / list[dict]) 直接映射, 不调 LLM"""

from __future__ import annotations

from typing import Any

from src.dataclean.base import RAW_INPUT_MAX_LEN, BaseCleaner, CleanResult

try:
    import pandas as pd
except ImportError:  # pragma: no cover
    pd = None  # type: ignore[assignment]


class PassthroughCleaner(BaseCleaner):
    """已结构化数据直接映射入库 — 不调用 LLM, 零成本"""

    def get_schema(self) -> None:
        return None

    def clean(self, raw_data: Any) -> CleanResult:
        if pd is not None and isinstance(raw_data, pd.DataFrame):
            data: dict | list = raw_data.to_dict(orient="records")
        elif isinstance(raw_data, list):
            data = raw_data
        elif isinstance(raw_data, dict):
            data = raw_data
        else:
            data = {"raw": str(raw_data)}

        return CleanResult(
            engine="passthrough",
            schema_name="raw",
            cleaned_data=data,
            raw_input=str(raw_data)[:RAW_INPUT_MAX_LEN],
            llm_usage={},
            is_fallback=False,
        )
