"""Tests for src/dataclean/cleaners/passthrough_cleaner.py"""
from __future__ import annotations

import pytest

from src.dataclean.base import CleanResult
from src.dataclean.cleaners.passthrough_cleaner import PassthroughCleaner


class TestPassthroughCleaner:
    def test_get_schema_returns_none(self):
        cleaner = PassthroughCleaner()
        assert cleaner.get_schema() is None

    def test_dict_input(self):
        data = {"symbol": "SPX", "close_price": 5200.0}
        result = cleaner = PassthroughCleaner()
        result = cleaner.clean(data)
        assert isinstance(result, CleanResult)
        assert result.engine == "passthrough"
        assert result.schema_name == "raw"
        assert result.cleaned_data == data
        assert result.is_fallback is False
        assert result.llm_usage == {}

    def test_list_input(self):
        data = [{"a": 1}, {"b": 2}]
        cleaner = PassthroughCleaner()
        result = cleaner.clean(data)
        assert result.cleaned_data == data

    def test_string_input(self):
        cleaner = PassthroughCleaner()
        result = cleaner.clean("raw text")
        assert result.cleaned_data == {"raw": "raw text"}

    def test_number_input(self):
        cleaner = PassthroughCleaner()
        result = cleaner.clean(42)
        assert result.cleaned_data == {"raw": "42"}

    def test_dataframe_input(self):
        pd = pytest.importorskip("pandas")
        df = pd.DataFrame({"code": ["000001.SZ"], "price": [15.3]})
        cleaner = PassthroughCleaner()
        result = cleaner.clean(df)
        assert isinstance(result.cleaned_data, list)
        assert result.cleaned_data[0]["code"] == "000001.SZ"

    def test_raw_input_truncated(self):
        cleaner = PassthroughCleaner()
        long_data = {"x": "y" * 1000}
        result = cleaner.clean(long_data)
        assert len(result.raw_input) <= 500

    def test_no_llm_required(self):
        cleaner = PassthroughCleaner()
        assert cleaner.llm is None
