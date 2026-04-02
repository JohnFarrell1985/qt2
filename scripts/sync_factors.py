"""因子数据同步脚本"""
import sys
sys.path.insert(0, ".")

from src.common.logger import get_logger
from src.data.sync import DataSyncManager

logger = get_logger(__name__)


def main():
    mgr = DataSyncManager()
    logger.info("开始全量数据同步...")
    results = mgr.full_sync(start_date="20240101", sync_minute=False)
    logger.info(f"同步完成: {results}")


if __name__ == "__main__":
    main()
