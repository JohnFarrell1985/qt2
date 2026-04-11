"""Tests for src/dataclean/__init__.py — module exports"""
from __future__ import annotations


class TestModuleExports:
    def test_import_dataclean_error(self):
        from src.dataclean import DatacleanError
        assert issubclass(DatacleanError, Exception)

    def test_import_all_providers_failed(self):
        from src.dataclean import AllProvidersFailedError
        assert issubclass(AllProvidersFailedError, Exception)

    def test_import_schema_validation(self):
        from src.dataclean import SchemaValidationError
        assert issubclass(SchemaValidationError, Exception)

    def test_import_llm_timeout(self):
        from src.dataclean import LLMTimeoutError
        assert issubclass(LLMTimeoutError, Exception)

    def test_all_list(self):
        import src.dataclean as dc
        for name in dc.__all__:
            assert hasattr(dc, name)
