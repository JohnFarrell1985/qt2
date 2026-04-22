"""ETF 下载进度 DAO — 与 :class:`~src.data.models.EtfDownloadProgress` 及
:class:`~src.data.download_progress.DownloadProgressDAO` 用法对齐, 供
:meth:`AkshareFinancialSync.sync_etf_daily` 按标的、按段断点续下."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func

from src.common.db import get_session
from src.common.logger import get_logger
from src.data.models import EtfDownloadProgress

logger = get_logger(__name__)

# 与 kline/同步器约定, 现仅 etf 日线
ETF_SYNC_TYPE_DAILY = "etf_daily"


class EtfDownloadProgressDAO:
    """EtfDownloadProgress 表的数据访问对象"""

    @staticmethod
    def init_progress(
        codes: list[str],
        sync_type: str,
        start_date=None,
        end_date=None,
        max_retries: int = 3,
    ) -> int:
        if not codes:
            return 0

        with get_session() as session:
            existing = (
                session.query(EtfDownloadProgress.code)
                .filter(
                    EtfDownloadProgress.sync_type == sync_type,
                    EtfDownloadProgress.code.in_(codes),
                )
                .all()
            )
            existing_codes = {row.code for row in existing}

            if existing_codes:
                session.query(EtfDownloadProgress).filter(
                    EtfDownloadProgress.sync_type == sync_type,
                    EtfDownloadProgress.code.in_(existing_codes),
                ).update(
                    {
                        EtfDownloadProgress.status: "pending",
                        EtfDownloadProgress.start_date: start_date,
                        EtfDownloadProgress.end_date: end_date,
                        EtfDownloadProgress.max_retries: max_retries,
                        EtfDownloadProgress.retry_count: 0,
                        EtfDownloadProgress.records_count: None,
                        EtfDownloadProgress.actual_start_date: None,
                        EtfDownloadProgress.actual_end_date: None,
                        EtfDownloadProgress.completed_at: None,
                        EtfDownloadProgress.error_message: None,
                        EtfDownloadProgress.updated_at: datetime.now(),
                    },
                    synchronize_session=False,
                )

            new_codes = [c for c in codes if c not in existing_codes]
            if new_codes:
                session.bulk_save_objects(
                    [
                        EtfDownloadProgress(
                            code=code,
                            sync_type=sync_type,
                            status="pending",
                            start_date=start_date,
                            end_date=end_date,
                            retry_count=0,
                            max_retries=max_retries,
                        )
                        for code in new_codes
                    ]
                )

            total = len(existing_codes) + len(new_codes)
            logger.info(
                "EtfDownloadProgress init: sync_type=%s, 更新=%d, 新增=%d",
                sync_type,
                len(existing_codes),
                len(new_codes),
            )
            return total

    @staticmethod
    def update_progress(
        code: str,
        sync_type: str,
        status: str,
        records_count: int | None = None,
        actual_start_date=None,
        actual_end_date=None,
        session: Any | None = None,
    ) -> bool:
        """``session`` 非空时只在本会话内 UPDATE, 由调用方 ``commit`` (与 K 线同事务)。"""
        def _apply(sess) -> bool:
            values: dict = {
                EtfDownloadProgress.status: status,
                EtfDownloadProgress.updated_at: datetime.now(),
            }
            if records_count is not None:
                values[EtfDownloadProgress.records_count] = records_count
            if actual_start_date is not None:
                values[EtfDownloadProgress.actual_start_date] = actual_start_date
            if actual_end_date is not None:
                values[EtfDownloadProgress.actual_end_date] = actual_end_date

            rows = (
                sess.query(EtfDownloadProgress)
                .filter(
                    EtfDownloadProgress.code == code,
                    EtfDownloadProgress.sync_type == sync_type,
                )
                .update(values, synchronize_session=False)
            )
            if rows == 0:
                logger.warning(
                    "EtfDownloadProgress: 未找到记录 code=%s, sync_type=%s",
                    code, sync_type,
                )
                return False
            return True

        if session is not None:
            return _apply(session)
        with get_session() as sess2:
            return _apply(sess2)

    @staticmethod
    def mark_failed(code: str, sync_type: str, error_message: str) -> None:
        with get_session() as session:
            record = (
                session.query(EtfDownloadProgress)
                .filter(
                    EtfDownloadProgress.code == code,
                    EtfDownloadProgress.sync_type == sync_type,
                )
                .first()
            )
            if record is None:
                logger.warning(
                    "EtfDownloadProgress mark_failed: 无记录 code=%s, sync_type=%s",
                    code, sync_type,
                )
                return

            record.retry_count = (record.retry_count or 0) + 1
            record.error_message = (error_message or "")[:500] if error_message else None
            record.updated_at = datetime.now()

            if record.retry_count >= (record.max_retries or 3):
                record.status = "failed"
            else:
                record.status = "pending"

    @staticmethod
    def mark_completed(code: str, sync_type: str, records_count: int) -> None:
        now = datetime.now()
        with get_session() as session:
            rows = (
                session.query(EtfDownloadProgress)
                .filter(
                    EtfDownloadProgress.code == code,
                    EtfDownloadProgress.sync_type == sync_type,
                )
                .update(
                    {
                        EtfDownloadProgress.status: "success",
                        EtfDownloadProgress.records_count: records_count,
                        EtfDownloadProgress.completed_at: now,
                        EtfDownloadProgress.updated_at: now,
                    },
                    synchronize_session=False,
                )
            )
            if rows == 0:
                logger.warning(
                    "EtfDownloadProgress mark_completed: 无记录 code=%s, sync_type=%s",
                    code, sync_type,
                )

    @staticmethod
    def get_incomplete_codes(sync_type: str) -> list[str]:
        with get_session(readonly=True) as session:
            rows = (
                session.query(EtfDownloadProgress.code)
                .filter(
                    EtfDownloadProgress.sync_type == sync_type,
                    EtfDownloadProgress.status.in_(
                        ["pending", "running", "failed"],
                    ),
                    EtfDownloadProgress.retry_count < EtfDownloadProgress.max_retries,
                )
                .all()
            )
            return [r.code for r in rows]

    @staticmethod
    def get_download_summary(sync_type: str) -> dict:
        with get_session(readonly=True) as session:
            rows = (
                session.query(
                    EtfDownloadProgress.status,
                    func.count().label("cnt"),
                )
                .filter(EtfDownloadProgress.sync_type == sync_type)
                .group_by(EtfDownloadProgress.status)
                .all()
            )
            summary: dict = {"pending": 0, "running": 0, "success": 0, "failed": 0}
            for status, cnt in rows:
                if status in summary:
                    summary[status] = int(cnt)
            summary["total"] = sum(summary.values())
            return summary

    @staticmethod
    def reset_failed(sync_type: str) -> int:
        with get_session() as session:
            n = (
                session.query(EtfDownloadProgress)
                .filter(
                    EtfDownloadProgress.sync_type == sync_type,
                    EtfDownloadProgress.status == "failed",
                )
                .update(
                    {
                        EtfDownloadProgress.status: "pending",
                        EtfDownloadProgress.retry_count: 0,
                        EtfDownloadProgress.error_message: None,
                        EtfDownloadProgress.updated_at: datetime.now(),
                    },
                    synchronize_session=False,
                )
            )
            logger.info("EtfDownloadProgress reset_failed: sync_type=%s, 重置 %d 条", sync_type, n)
            return n
