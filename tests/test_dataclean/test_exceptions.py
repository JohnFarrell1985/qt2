"""Tests for src/dataclean/exceptions.py"""
from __future__ import annotations

import pytest

from src.dataclean.exceptions import (
    AllProvidersFailedError,
    DatacleanError,
    LLMTimeoutError,
    SchemaValidationError,
)


class TestExceptionHierarchy:
    """All custom errors inherit from DatacleanError."""

    def test_all_providers_is_dataclean_error(self):
        assert issubclass(AllProvidersFailedError, DatacleanError)

    def test_schema_validation_is_dataclean_error(self):
        assert issubclass(SchemaValidationError, DatacleanError)

    def test_llm_timeout_is_dataclean_error(self):
        assert issubclass(LLMTimeoutError, DatacleanError)

    def test_dataclean_error_is_base_exception(self):
        assert issubclass(DatacleanError, Exception)


class TestExceptionCatching:
    """Upstream can catch DatacleanError to handle all subclasses."""

    def test_catch_all_providers_failed(self):
        with pytest.raises(DatacleanError):
            raise AllProvidersFailedError("test")

    def test_catch_schema_validation(self):
        with pytest.raises(DatacleanError):
            raise SchemaValidationError("bad json")

    def test_catch_llm_timeout(self):
        with pytest.raises(DatacleanError):
            raise LLMTimeoutError("30s exceeded")

    def test_specific_catch(self):
        with pytest.raises(AllProvidersFailedError, match="deepseek"):
            raise AllProvidersFailedError("deepseek + qwen failed")

    def test_message_preserved(self):
        err = AllProvidersFailedError("所有 LLM 均失败")
        assert str(err) == "所有 LLM 均失败"
