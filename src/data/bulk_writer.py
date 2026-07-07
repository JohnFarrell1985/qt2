"""批量写入器 — COPY 协议 + INSERT ON CONFLICT 双模式"""
from __future__ import annotations

import csv
import io
from collections import defaultdict
from typing import Any

from sqlalchemy import inspect as sa_inspect, text
from sqlalchemy.dialects.postgresql import insert

from src.common.db import get_session, get_engine
from src.common.db_batch import DEFAULT_TABLE_UPSERT_FLUSH, log_upsert_commit
from src.common.logger import get_logger

logger = get_logger(__name__)


class BulkWriter:
    """Dual-mode bulk writer: COPY for empty tables, UPSERT for incremental.

    Modes:
        - "copy": PostgreSQL COPY protocol via raw psycopg2 copy_expert (fastest for initial loads)
        - "upsert": INSERT ON CONFLICT DO UPDATE (for incremental with dedup)
        - "auto": COPY if table empty, else UPSERT
    """

    def __init__(self, batch_size: int = DEFAULT_TABLE_UPSERT_FLUSH):
        self._batch_size = batch_size

    def write(
        self,
        model: Any,
        records: list[dict],
        mode: str = "auto",
        conflict_columns: list[str] | None = None,
        update_columns: list[str] | None = None,
    ) -> int:
        """Write records to DB.

        Args:
            model: SQLAlchemy ORM model class
            records: list of dicts to insert
            mode: "copy", "upsert", or "auto"
            conflict_columns: columns for ON CONFLICT (required for upsert)
            update_columns: columns to update on conflict (if None, updates all non-conflict cols)

        Returns:
            number of records written
        """
        if not records:
            return 0

        table_name = model.__tablename__

        if mode == "auto":
            mode = "copy" if self._is_table_empty(table_name) else "upsert"

        if mode == "copy":
            return self._copy_insert(model, records)
        return self._batch_upsert(
            model,
            records,
            conflict_columns=conflict_columns,
            update_columns=update_columns,
        )

    def write_flush(self, batch: list[tuple[Any, list[dict]]]) -> None:
        """Flush a batch from WriteBehindBuffer.

        Each item is (model_class, records_list).
        Groups by model and writes each group.
        """
        grouped: dict[Any, list[dict]] = defaultdict(list)
        for model, records in batch:
            grouped[model].extend(records)

        for model, all_records in grouped.items():
            try:
                self.write(model, all_records, mode="upsert")
            except Exception:
                logger.exception(
                    "write_flush failed for %s (%d records)",
                    model.__tablename__,
                    len(all_records),
                )

    _ALLOWED_TABLES: frozenset[str] = frozenset({
        "stocks", "stock_daily", "stock_minute", "market_index",
        "trading_date", "sector_stock", "index_weight",
        "convertible_bond", "cb_daily", "etf_info", "etf_daily",
        "factor_meta", "factor_values",
        "stock_financial_report", "stock_financial_indicator",
        "trade_order", "trade_position", "trade_daily_report",
        "sector_data",
        "stock_download_progress", "etf_download_progress", "stock_realtime",
        "watchlist_stock", "watchlist_intel",
        "hsgt_market_daily", "stock_moneyflow_daily", "stock_lhb_daily",
        "institution_survey", "alt_datacollect_progress",
        "stock_universe",
        "collect_log", "collect_dead_letter",
    })

    def _is_table_empty(self, table_name: str) -> bool:
        if table_name not in self._ALLOWED_TABLES:
            raise ValueError(f"Table name not in whitelist: {table_name}")
        try:
            with get_session(readonly=True) as session:
                result = session.execute(
                    text(f"SELECT EXISTS (SELECT 1 FROM {table_name} LIMIT 1)")  # noqa: S608
                ).scalar()
                return not result
        except Exception:
            return False

    def _copy_insert(self, model: Any, records: list[dict]) -> int:
        """COPY protocol via psycopg2 CSV format for maximum throughput.

        Uses FORMAT csv which handles quoting of fields containing
        delimiters, newlines, and quote characters automatically.
        """
        table_name = model.__tablename__
        columns = list(records[0].keys())

        buf = io.StringIO()
        writer = csv.writer(buf, delimiter=",", quoting=csv.QUOTE_MINIMAL, lineterminator="\n")
        for rec in records:
            row = []
            for col in columns:
                val = rec.get(col)
                if val is None:
                    row.append("")
                else:
                    row.append(str(val))
            writer.writerow(row)

        buf.seek(0)
        col_str = ", ".join(columns)
        copy_sql = (
            f"COPY {table_name} ({col_str}) FROM STDIN WITH "  # noqa: S608
            f"(FORMAT csv, HEADER false, NULL '')"
        )

        engine = get_engine()
        raw_conn = engine.raw_connection()
        try:
            cursor = raw_conn.cursor()
            cursor.copy_expert(copy_sql, buf)
            raw_conn.commit()
            logger.info("COPY %d records into %s", len(records), table_name)
            return len(records)
        except Exception:
            raw_conn.rollback()
            raise
        finally:
            raw_conn.close()

    def _batch_upsert(
        self,
        model: Any,
        records: list[dict],
        conflict_columns: list[str] | None = None,
        update_columns: list[str] | None = None,
    ) -> int:
        """Batch INSERT ON CONFLICT with per-batch transactions."""
        if not conflict_columns:
            mapper = sa_inspect(model)
            conflict_columns = [c.name for c in mapper.primary_key]

        if not update_columns:
            all_cols = set(records[0].keys())
            update_columns = list(all_cols - set(conflict_columns))

        total_written = 0
        for i in range(0, len(records), self._batch_size):
            batch = records[i : i + self._batch_size]
            with get_session() as session:
                stmt = insert(model).values(batch)
                if update_columns:
                    update_dict = {col: stmt.excluded[col] for col in update_columns if col in records[0]}
                    stmt = stmt.on_conflict_do_update(
                        index_elements=conflict_columns,
                        set_=update_dict,
                    )
                else:
                    stmt = stmt.on_conflict_do_nothing(index_elements=conflict_columns)
                session.execute(stmt)
            total_written += len(batch)
            log_upsert_commit(f"bulk_writer.{getattr(model, '__tablename__', model)}", len(batch))

        logger.info(
            "upsert %d records into %s (%d batches)",
            len(records),
            model.__tablename__,
            (len(records) + self._batch_size - 1) // self._batch_size,
        )
        return total_written
