"""内存高效分块处理工具"""
from __future__ import annotations

import gc

import pandas as pd

from src.common.logger import get_logger

logger = get_logger(__name__)

CHUNK_THRESHOLD = 100_000

try:
    _major = int(pd.__version__.split(".")[0])
    if _major < 3:
        pd.options.mode.copy_on_write = True
except (AttributeError, TypeError, ValueError):
    pass


def chunk_dataframe(df: pd.DataFrame, chunk_size: int = CHUNK_THRESHOLD) -> list[pd.DataFrame]:
    """Split a large DataFrame into smaller chunks.

    Returns list of DataFrames, each at most chunk_size rows.
    """
    if len(df) <= chunk_size:
        return [df]

    chunks = [df.iloc[i : i + chunk_size] for i in range(0, len(df), chunk_size)]
    logger.debug("split DataFrame (%d rows) into %d chunks", len(df), len(chunks))
    return chunks


def log_memory_usage(df: pd.DataFrame, label: str = "") -> float:
    """Log DataFrame memory usage and return size in MB."""
    mem_bytes = df.memory_usage(deep=True).sum()
    mem_mb = mem_bytes / (1024 * 1024)
    logger.debug("memory_usage label=%s rows=%d size=%.1fMB", label, len(df), mem_mb)
    return mem_mb


def release_dataframe(df: pd.DataFrame) -> None:
    """Explicitly release a DataFrame and trigger GC."""
    del df
    gc.collect()
