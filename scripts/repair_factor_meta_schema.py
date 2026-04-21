"""将旧版 factor_meta 表升级到当前 ORM (含 version + 复合唯一键).

旧库常见形态: 仅有 UNIQUE(factor_name), 无 version 列.
升级后: version INTEGER NOT NULL DEFAULT 1, UNIQUE(factor_name, version).

用法 (项目根目录):
  uv run python scripts/repair_factor_meta_schema.py
"""
from __future__ import annotations

import sys

sys.path.insert(0, ".")

from sqlalchemy import text

from src.common.db import get_engine, init_database
from src.common.logger import get_logger

logger = get_logger(__name__)

# 显式 public 限定, 避免 search_path 下多张 factor_meta 时 DROP 落到错误表
_UPGRADE_SQL = """
ALTER TABLE public.factor_meta
    ADD COLUMN IF NOT EXISTS version INTEGER NOT NULL DEFAULT 1;

DO $$
DECLARE
    r RECORD;
    tbl regclass := 'public.factor_meta'::regclass;
BEGIN
    FOR r IN
        SELECT c.conname
        FROM pg_constraint c
        WHERE c.conrelid = tbl AND c.contype = 'u'
    LOOP
        EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', tbl::text, r.conname);
    END LOOP;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint c
        WHERE c.conrelid = 'public.factor_meta'::regclass
          AND c.conname = 'uq_factor_name_version'
    ) THEN
        ALTER TABLE public.factor_meta
            ADD CONSTRAINT uq_factor_name_version
            UNIQUE (factor_name, version);
    END IF;
END $$;
"""


def main() -> None:
    init_database()
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(text(_UPGRADE_SQL))
    logger.info("factor_meta 表结构已对齐 ORM (version + uq_factor_name_version)")


if __name__ == "__main__":
    main()
