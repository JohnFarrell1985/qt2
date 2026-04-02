"""数据库初始化脚本"""
import sys
sys.path.insert(0, ".")

from src.common.db import init_database
from src.common.logger import get_logger
from src.data.factor_data import FactorDataManager

logger = get_logger(__name__)


def main():
    logger.info("初始化数据库表...")
    init_database()
    logger.info("数据库表创建完成")

    logger.info("初始化因子元信息...")
    mgr = FactorDataManager()
    count = mgr.init_factor_meta()
    logger.info(f"已初始化 {count} 个因子")


if __name__ == "__main__":
    main()
