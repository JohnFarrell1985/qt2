"""另类采集进度 DAO — 按 (种类, 范围键, 源 id) 去重, 与 ``StockDownloadProgress``/``EtfDownloadProgress`` 同思路。"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.dialects.postgresql import insert

from src.common.db import get_session
from src.common.logger import get_logger
from src.data.models import AltDatacollectProgress

logger = get_logger(__name__)

# 与 ``AltDatacollectProgress.category`` 约定一致
CAT_HSGT = "hsgt_market"
CAT_LHB = "stock_lhb_daily"
CAT_MF = "stock_moneyflow_daily"
CAT_SURVEY = "institution_survey"
CAT_INDEX_WEIGHT = "index_weight"
CAT_SECTOR_STOCK = "sector_stock"
CAT_SECTOR_DATA = "sector_data"
CAT_INST_HOLDER = "stock_inst_holder"

# ``src.data.alt_data_sync`` 另类 6 类: hsgt / lhb / moneyflow / survey / index_weight / sector_stock
# 另: ``sector_data``(板块K/资金流) 在 ``sector_market_data`` 中维护, 也写入本表 (category=sector_data) — 合计日频「另类+板块」7 类
ALT_DATACOLLECT_CATEGORY_COUNT: int = 7


class AltDatacollectProgressDAO:
    @staticmethod
    def is_ok(category: str, scope_key: str, source_id: str) -> bool:
        with get_session(readonly=True) as session:
            r = (
                session.query(AltDatacollectProgress)
                .filter(
                    AltDatacollectProgress.category == category,
                    AltDatacollectProgress.scope_key == scope_key,
                    AltDatacollectProgress.source_id == source_id,
                    AltDatacollectProgress.status == "ok",
                )
                .first()
            )
            return r is not None

    @staticmethod
    def mark_ok(
        category: str,
        scope_key: str,
        source_id: str,
        row_count: int,
        *,
        status: str = "ok",
    ) -> None:
        if row_count <= 0 and status == "ok":
            return
        now = datetime.now()
        with get_session() as session:
            stmt = insert(AltDatacollectProgress).values(
                category=category,
                scope_key=scope_key,
                source_id=source_id,
                status=status,
                row_count=row_count,
                updated_at=now,
            )
            stmt = stmt.on_conflict_do_update(
                constraint="uq_alt_dcp_cat_scope_src",
                set_={
                    "status": stmt.excluded.status,
                    "row_count": stmt.excluded.row_count,
                    "updated_at": now,
                },
            )
            session.execute(stmt)
        logger.debug(
            "alt_dcp: ok category=%s scope=%s source=%s rows=%d",
            category, scope_key, source_id, row_count,
        )
