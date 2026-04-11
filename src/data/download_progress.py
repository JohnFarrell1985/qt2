"""下载进度 DAO — 断点续传支持

提供 StockDownloadProgress 表的 CRUD 操作，供下载器在批量拉取
历史行情时追踪每只股票的下载状态，支持失败重试与进度查询。
"""
from datetime import datetime

from sqlalchemy import func

from src.common.db import get_session
from src.common.logger import get_logger
from src.data.models import StockDownloadProgress

logger = get_logger(__name__)


class DownloadProgressDAO:
    """StockDownloadProgress 表的数据访问对象"""

    @staticmethod
    def init_progress(
        codes: list[str],
        sync_type: str,
        start_date=None,
        end_date=None,
        max_retries: int = 3,
    ) -> int:
        """批量初始化下载进度记录。

        对已存在的 (code, sync_type) 记录做 UPDATE（重置为 pending），
        对不存在的做 INSERT，保证幂等。

        Returns:
            实际新建 + 更新的记录数
        """
        if not codes:
            return 0

        with get_session() as session:
            existing = (
                session.query(StockDownloadProgress.code)
                .filter(
                    StockDownloadProgress.sync_type == sync_type,
                    StockDownloadProgress.code.in_(codes),
                )
                .all()
            )
            existing_codes = {row.code for row in existing}

            if existing_codes:
                session.query(StockDownloadProgress).filter(
                    StockDownloadProgress.sync_type == sync_type,
                    StockDownloadProgress.code.in_(existing_codes),
                ).update(
                    {
                        StockDownloadProgress.status: "pending",
                        StockDownloadProgress.start_date: start_date,
                        StockDownloadProgress.end_date: end_date,
                        StockDownloadProgress.max_retries: max_retries,
                        StockDownloadProgress.retry_count: 0,
                        StockDownloadProgress.records_count: None,
                        StockDownloadProgress.actual_start_date: None,
                        StockDownloadProgress.actual_end_date: None,
                        StockDownloadProgress.completed_at: None,
                        StockDownloadProgress.error_message: None,
                        StockDownloadProgress.updated_at: datetime.now(),
                    },
                    synchronize_session=False,
                )

            new_codes = [c for c in codes if c not in existing_codes]
            if new_codes:
                session.bulk_save_objects(
                    [
                        StockDownloadProgress(
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
                "init_progress: sync_type=%s, 更新=%d, 新增=%d",
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
    ) -> bool:
        """更新单只股票的下载进度。

        Returns:
            是否找到并更新了记录
        """
        with get_session() as session:
            values: dict = {
                StockDownloadProgress.status: status,
                StockDownloadProgress.updated_at: datetime.now(),
            }
            if records_count is not None:
                values[StockDownloadProgress.records_count] = records_count
            if actual_start_date is not None:
                values[StockDownloadProgress.actual_start_date] = actual_start_date
            if actual_end_date is not None:
                values[StockDownloadProgress.actual_end_date] = actual_end_date

            rows = (
                session.query(StockDownloadProgress)
                .filter(
                    StockDownloadProgress.code == code,
                    StockDownloadProgress.sync_type == sync_type,
                )
                .update(values, synchronize_session=False)
            )
            if rows == 0:
                logger.warning("update_progress: 未找到记录 code=%s, sync_type=%s", code, sync_type)
                return False
            return True

    @staticmethod
    def mark_failed(code: str, sync_type: str, error_message: str) -> None:
        """标记下载失败，自动判断是否还可重试。

        retry_count +1；若已达到 max_retries 则 status='failed'，否则回退到 'pending'。
        """
        with get_session() as session:
            record = (
                session.query(StockDownloadProgress)
                .filter(
                    StockDownloadProgress.code == code,
                    StockDownloadProgress.sync_type == sync_type,
                )
                .first()
            )
            if record is None:
                logger.warning("mark_failed: 未找到记录 code=%s, sync_type=%s", code, sync_type)
                return

            record.retry_count = (record.retry_count or 0) + 1
            record.error_message = error_message[:500] if error_message else None
            record.updated_at = datetime.now()

            if record.retry_count >= (record.max_retries or 3):
                record.status = "failed"
                logger.warning(
                    "mark_failed: code=%s 重试耗尽 (%d/%d)",
                    code,
                    record.retry_count,
                    record.max_retries,
                )
            else:
                record.status = "pending"
                logger.info(
                    "mark_failed: code=%s 第 %d 次失败, 等待重试",
                    code,
                    record.retry_count,
                )

    @staticmethod
    def mark_completed(code: str, sync_type: str, records_count: int) -> None:
        """标记下载完成"""
        now = datetime.now()
        with get_session() as session:
            rows = (
                session.query(StockDownloadProgress)
                .filter(
                    StockDownloadProgress.code == code,
                    StockDownloadProgress.sync_type == sync_type,
                )
                .update(
                    {
                        StockDownloadProgress.status: "success",
                        StockDownloadProgress.records_count: records_count,
                        StockDownloadProgress.completed_at: now,
                        StockDownloadProgress.updated_at: now,
                    },
                    synchronize_session=False,
                )
            )
            if rows == 0:
                logger.warning("mark_completed: 未找到记录 code=%s, sync_type=%s", code, sync_type)

    @staticmethod
    def get_incomplete_stocks(sync_type: str) -> list[str]:
        """获取尚未完成的股票代码列表（可重试的 pending/running/failed）"""
        with get_session() as session:
            rows = (
                session.query(StockDownloadProgress.code)
                .filter(
                    StockDownloadProgress.sync_type == sync_type,
                    StockDownloadProgress.status.in_(["pending", "running", "failed"]),
                    StockDownloadProgress.retry_count < StockDownloadProgress.max_retries,
                )
                .all()
            )
            return [r.code for r in rows]

    @staticmethod
    def get_download_summary(sync_type: str) -> dict:
        """按状态统计下载进度

        Returns:
            {"pending": N, "running": N, "success": N, "failed": N, "total": N}
        """
        with get_session() as session:
            rows = (
                session.query(
                    StockDownloadProgress.status,
                    func.count().label("cnt"),
                )
                .filter(StockDownloadProgress.sync_type == sync_type)
                .group_by(StockDownloadProgress.status)
                .all()
            )
            summary = {"pending": 0, "running": 0, "success": 0, "failed": 0}
            for status, cnt in rows:
                if status in summary:
                    summary[status] = cnt
            summary["total"] = sum(summary.values())
            return summary

    @staticmethod
    def reset_failed(sync_type: str) -> int:
        """将所有 failed 记录重置为 pending，retry_count 归零。

        Returns:
            重置的记录数
        """
        with get_session() as session:
            rows = (
                session.query(StockDownloadProgress)
                .filter(
                    StockDownloadProgress.sync_type == sync_type,
                    StockDownloadProgress.status == "failed",
                )
                .update(
                    {
                        StockDownloadProgress.status: "pending",
                        StockDownloadProgress.retry_count: 0,
                        StockDownloadProgress.error_message: None,
                        StockDownloadProgress.updated_at: datetime.now(),
                    },
                    synchronize_session=False,
                )
            )
            logger.info("reset_failed: sync_type=%s, 重置 %d 条记录", sync_type, rows)
            return rows


if __name__ == "__main__":
    import sys

    def _usage():
        logger.info(
            "用法: python -m src.data.download_progress <command> [sync_type]\n"
            "  status [sync_type]       查看下载进度摘要\n"
            "  reset-failed <sync_type> 重置失败记录"
        )
        sys.exit(1)

    args = sys.argv[1:]
    if not args:
        _usage()

    dao = DownloadProgressDAO()
    command = args[0]

    if command == "status":
        sync_type = args[1] if len(args) > 1 else None
        if sync_type:
            summary = dao.get_download_summary(sync_type)
            logger.info("下载进度 [%s]: %s", sync_type, summary)
        else:
            for st in ("history_full", "history_inc", "fundamental"):
                summary = dao.get_download_summary(st)
                if summary["total"] > 0:
                    logger.info("下载进度 [%s]: %s", st, summary)
    elif command == "reset-failed":
        if len(args) < 2:
            logger.error("reset-failed 需要指定 sync_type")
            sys.exit(1)
        count = dao.reset_failed(args[1])
        logger.info("已重置 %d 条失败记录", count)
    else:
        _usage()
