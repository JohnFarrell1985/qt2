"""Tests for src/datacollect/chunking.py"""
from __future__ import annotations

import gc
from unittest.mock import patch

import pandas as pd

from src.datacollect.chunking import (
    CHUNK_THRESHOLD,
    chunk_dataframe,
    log_memory_usage,
    release_dataframe,
)


# ====================================================================
# chunk_dataframe
# ====================================================================


class TestChunkDataframe:

    def test_small_df_returns_single_chunk(self):
        df = pd.DataFrame({"a": range(10)})
        chunks = chunk_dataframe(df, chunk_size=100)
        assert len(chunks) == 1
        assert len(chunks[0]) == 10

    def test_exact_chunk_size(self):
        df = pd.DataFrame({"a": range(100)})
        chunks = chunk_dataframe(df, chunk_size=100)
        assert len(chunks) == 1

    def test_splits_into_correct_number_of_chunks(self):
        df = pd.DataFrame({"a": range(250)})
        chunks = chunk_dataframe(df, chunk_size=100)
        assert len(chunks) == 3
        total_rows = sum(len(c) for c in chunks)
        assert total_rows == 250

    def test_each_chunk_within_limit(self):
        df = pd.DataFrame({"a": range(1000)})
        chunks = chunk_dataframe(df, chunk_size=300)
        for c in chunks:
            assert len(c) <= 300

    def test_preserves_data(self):
        df = pd.DataFrame({"a": range(500), "b": range(500, 1000)})
        chunks = chunk_dataframe(df, chunk_size=200)
        reconstructed = pd.concat(chunks, ignore_index=True)
        pd.testing.assert_frame_equal(reconstructed, df.reset_index(drop=True))

    def test_empty_df_returns_single_chunk(self):
        df = pd.DataFrame()
        chunks = chunk_dataframe(df, chunk_size=100)
        assert len(chunks) == 1

    def test_single_row(self):
        df = pd.DataFrame({"x": [42]})
        chunks = chunk_dataframe(df, chunk_size=100)
        assert len(chunks) == 1
        assert chunks[0].iloc[0]["x"] == 42

    def test_default_threshold(self):
        assert CHUNK_THRESHOLD == 100_000

    def test_chunk_size_one(self):
        df = pd.DataFrame({"a": [1, 2, 3]})
        chunks = chunk_dataframe(df, chunk_size=1)
        assert len(chunks) == 3


# ====================================================================
# log_memory_usage
# ====================================================================


class TestLogMemoryUsage:

    def test_returns_positive_mb(self):
        df = pd.DataFrame({"a": range(1000), "b": ["text"] * 1000})
        result = log_memory_usage(df, label="test")
        assert result > 0.0

    def test_empty_df_returns_zero_or_small(self):
        df = pd.DataFrame()
        result = log_memory_usage(df, label="empty")
        assert result >= 0.0

    def test_larger_df_uses_more_memory(self):
        small = pd.DataFrame({"a": range(100)})
        large = pd.DataFrame({"a": range(10000)})
        small_mb = log_memory_usage(small, label="small")
        large_mb = log_memory_usage(large, label="large")
        assert large_mb > small_mb


# ====================================================================
# release_dataframe
# ====================================================================


class TestReleaseDataframe:

    def test_release_triggers_gc(self):
        df = pd.DataFrame({"a": range(100)})
        with patch.object(gc, "collect") as mock_gc:
            release_dataframe(df)
            mock_gc.assert_called_once()
