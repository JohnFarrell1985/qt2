"""可转债数据同步模块

数据来源: xtdata (QMT 终端)
  - download_cb_data()  → 下载全部可转债基础信息
  - get_cb_info(code)   → 获取指定转债详情
  - download_history_data2 + get_market_data_ex → 转债日线行情

API 文档: http://dict.thinktrader.net/nativeApi/xtdata.html
"""
from datetime import datetime, date
from typing import List, Dict, Any, Optional

import pandas as pd
from sqlalchemy.dialects.postgresql import insert

from src.common.db import get_session
from src.common.logger import get_logger
from src.data.models import ConvertibleBond, CBDaily
from src.data.qmt_client import QMTClient
from src.data.download_engine import DownloadEngine

logger = get_logger(__name__)

CB_INFO_FIELD_MAP = {
    "bondName": "bond_name",
    "underlyingCode": "stock_code",
    "convPrice": "convert_price",
    "convStartDate": "convert_start_date",
    "convEndDate": "convert_end_date",
    "maturityDate": "maturity_date",
    "issueAmount": "issue_amount",
    "remainAmount": "remain_amount",
    "level": "level",
    "analConvpremiumratio": "analConvpremiumratio",
    "pureBondValue": "pure_bond_value",
}


class CBDataSync:
    """可转债数据同步管理器"""

    def __init__(self, client: Optional[QMTClient] = None):
        self.client = client or QMTClient()
        self.engine = DownloadEngine(self.client)

    def get_cb_code_list(self) -> List[str]:
        """获取全部可转债代码列表 (通过板块接口)"""
        try:
            codes = self.client.get_stock_list_in_sector("沪深转债")
            if not codes:
                codes = self.client.get_stock_list_in_sector("可转债")
            logger.info(f"获取到 {len(codes)} 只可转债")
            return codes
        except Exception as e:
            logger.error(f"获取可转债列表失败: {e}")
            return []

    def sync_cb_info(self) -> int:
        """同步全部可转债基础信息到 DB

        流程: download_cb_data() → get_cb_info(code) → upsert
        """
        self.client.download_cb_data()

        cb_codes = self.get_cb_code_list()
        if not cb_codes:
            logger.warning("未获取到可转债列表, 跳过同步")
            return 0

        count = 0
        for code in cb_codes:
            try:
                info = self.client.get_cb_info(code)
                if not info:
                    continue
                row = {"code": code}
                for src_key, db_col in CB_INFO_FIELD_MAP.items():
                    row[db_col] = info.get(src_key)

                with get_session() as session:
                    stmt = insert(ConvertibleBond).values(**row).on_conflict_do_update(
                        index_elements=["code"],
                        set_={k: v for k, v in row.items() if k != "code"},
                    )
                    session.execute(stmt)
                count += 1
            except Exception as e:
                logger.warning(f"同步可转债 {code} 基础信息失败: {e}")

        logger.info(f"可转债基础信息同步完成: {count}/{len(cb_codes)} 只")
        return count

    def sync_cb_daily(self, start_time: str = "", end_time: str = "") -> int:
        """同步可转债日线行情到 DB

        使用标准 download_history_data2 + get_market_data_ex 接口
        """
        cb_codes = self.get_cb_code_list()
        if not cb_codes:
            return 0

        progress = self.engine.download_kline(
            stock_list=cb_codes,
            period="1d",
            start_time=start_time,
            end_time=end_time,
        )
        logger.info(f"可转债日线下载: {progress.finished_stocks}/{progress.total_stocks}")

        if not end_time:
            end_time = datetime.now().strftime("%Y%m%d")

        count = 0
        for code, df in self.engine.get_local_kline_batched(
            cb_codes, period="1d", start_time=start_time, end_time=end_time,
        ):
            if df is None or df.empty:
                continue
            rows = self._df_to_cb_daily_rows(code, df)
            if rows:
                self._upsert_cb_daily(rows)
                count += len(rows)

        logger.info(f"可转债日线入库: {count} 条")
        return count

    @staticmethod
    def _df_to_cb_daily_rows(code: str, df: pd.DataFrame) -> List[Dict[str, Any]]:
        rows = []
        for idx, row in df.iterrows():
            td = idx if isinstance(idx, (date, datetime)) else pd.Timestamp(str(idx))
            rows.append({
                "code": code,
                "trade_date": td.date() if hasattr(td, "date") else td,
                "open": float(row.get("open", 0)),
                "high": float(row.get("high", 0)),
                "low": float(row.get("low", 0)),
                "close": float(row.get("close", 0)),
                "volume": int(row.get("volume", 0)),
                "amount": float(row.get("amount", 0)),
            })
        return rows

    @staticmethod
    def _upsert_cb_daily(rows: List[Dict[str, Any]]) -> None:
        with get_session() as session:
            for row in rows:
                stmt = insert(CBDaily).values(**row).on_conflict_do_update(
                    constraint="idx_cbd_code_date",
                    set_={k: v for k, v in row.items() if k not in ("code", "trade_date")},
                )
                session.execute(stmt)
