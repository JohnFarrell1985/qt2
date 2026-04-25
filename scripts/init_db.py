"""数据库初始化 — 建表 + 与 ORM 对齐的增量补列.

等价于应用启动时的 ``init_database()`` (见 ``src.common.db``).

用法 (项目根目录)::

    uv run python scripts/init_db.py

可选跳过因子元信息种子 (仅建表)::

    uv run python scripts/init_db.py --schema-only

旧库 ``factor_meta`` 仅 UNIQUE(factor_name) 等形态, 需额外执行::

    uv run python scripts/repair_factor_meta_schema.py
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, ".")

from src.common.db import init_database
from src.common.logger import get_logger

logger = get_logger(__name__)


def main() -> None:
    p = argparse.ArgumentParser(description="初始化 PostgreSQL 表结构 (SQLAlchemy create_all + 补列)")
    p.add_argument(
        "--schema-only",
        action="store_true",
        help="仅执行 init_database, 不写入 factor_meta 种子",
    )
    args = p.parse_args()

    logger.info("执行 init_database() (create_all + 幂等补列)...")
    init_database()
    logger.info("表结构就绪")

    if args.schema_only:
        return

    logger.info("初始化因子元信息种子...")
    from src.data.factor_data import FactorDataManager

    mgr = FactorDataManager()
    count = mgr.init_factor_meta()
    logger.info("已初始化 %d 个因子元信息", count)


if __name__ == "__main__":
    main()
