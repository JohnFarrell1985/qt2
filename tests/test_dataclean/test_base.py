"""Tests for src/dataclean/base.py — BaseCleaner + CleanResult"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel, Field, ValidationError

from src.dataclean.base import BaseCleaner, CleanResult


# ── Test helpers ──────────────────────────────────────────────────

class _DummySchema(BaseModel):
    value: int = Field(ge=0)
    label: str


class _ConcreteCleaner(BaseCleaner):
    """Minimal concrete implementation for testing."""

    def get_schema(self):
        return _DummySchema

    def clean(self, raw_data):
        return CleanResult(
            engine="test",
            schema_name="DummySchema",
            cleaned_data={"value": 42, "label": "ok"},
            raw_input=str(raw_data),
        )


class _NoSchemaCleaner(BaseCleaner):
    """Cleaner without a schema (like PassthroughCleaner)."""

    def get_schema(self):
        return None

    def clean(self, raw_data):
        return CleanResult(
            engine="passthrough",
            schema_name="raw",
            cleaned_data={"raw": str(raw_data)},
            raw_input=str(raw_data),
        )


# ── CleanResult tests ────────────────────────────────────────────

class TestCleanResult:
    def test_defaults(self):
        r = CleanResult(
            engine="test",
            schema_name="Test",
            cleaned_data={"a": 1},
            raw_input="hello",
        )
        assert r.llm_usage == {}
        assert r.is_fallback is False

    def test_all_fields(self):
        usage = {"provider": "deepseek", "cost_usd": 0.001}
        r = CleanResult(
            engine="sentiment",
            schema_name="SentimentExtraction",
            cleaned_data={"score": 0.5},
            raw_input="text",
            llm_usage=usage,
            is_fallback=True,
        )
        assert r.engine == "sentiment"
        assert r.is_fallback is True
        assert r.llm_usage["provider"] == "deepseek"

    def test_cleaned_data_can_be_list(self):
        r = CleanResult(
            engine="passthrough",
            schema_name="raw",
            cleaned_data=[{"a": 1}, {"b": 2}],
            raw_input="df",
        )
        assert isinstance(r.cleaned_data, list)


# ── BaseCleaner tests ────────────────────────────────────────────

class TestBaseCleaner:
    def test_concrete_clean(self):
        cleaner = _ConcreteCleaner()
        result = cleaner.clean("input")
        assert result.engine == "test"
        assert result.cleaned_data["value"] == 42

    def test_validate_success(self):
        cleaner = _ConcreteCleaner()
        validated = cleaner._validate({"value": 10, "label": "good"})
        assert isinstance(validated, _DummySchema)
        assert validated.value == 10

    def test_validate_failure(self):
        cleaner = _ConcreteCleaner()
        with pytest.raises(ValidationError):
            cleaner._validate({"value": -1, "label": "bad"})

    def test_validate_no_schema_raises(self):
        cleaner = _NoSchemaCleaner()
        with pytest.raises(TypeError, match="未定义 Schema"):
            cleaner._validate({"value": 1})

    def test_init_with_llm_client(self):
        mock_llm = MagicMock()
        cleaner = _ConcreteCleaner(llm_client=mock_llm)
        assert cleaner.llm is mock_llm

    def test_init_without_llm_client(self):
        cleaner = _ConcreteCleaner()
        assert cleaner.llm is None

    def test_abstract_cannot_instantiate(self):
        with pytest.raises(TypeError):
            BaseCleaner()  # type: ignore[abstract]
