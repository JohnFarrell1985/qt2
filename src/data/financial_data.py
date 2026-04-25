"""财务数据同步模块

从QMT获取财务报表数据并存入PostgreSQL。
使用 DownloadEngine 分批下载, 避免限流和超时。
"""
from collections.abc import Callable
from datetime import datetime
from typing import List, Dict, Optional

import pandas as pd
from sqlalchemy.dialects.postgresql import insert

from src.common.db import get_session
from src.common.db_batch import DEFAULT_TABLE_UPSERT_FLUSH, log_upsert_commit
from src.common.logger import get_logger
from src.data.models import Stock, StockFinancialReport, StockFinancialIndicator
from src.data.qmt_client import QMTClient
from src.data.download_engine import DownloadEngine

logger = get_logger(__name__)

ALL_FINANCIAL_TABLES = [
    "Balance", "Income", "CashFlow", "Capital",
    "Holdernum", "Top10holder", "Top10flowholder", "Pershareindex",
]


class FinancialDataSync:
    """财务数据同步"""

    def __init__(self, client: Optional[QMTClient] = None):
        self.client = client or QMTClient()
        self.engine = DownloadEngine(self.client)

    def download_all_financial(
        self,
        stock_list: List[str],
        start_time: str = "",
        end_time: str = "",
    ) -> None:
        """预下载全部财务表到本地 (分批, 带重试)"""
        self.engine.download_financial(
            stock_list,
            table_list=ALL_FINANCIAL_TABLES,
            start_time=start_time,
            end_time=end_time,
        )

    def sync_reports(
        self,
        stock_list: List[str],
        start_time: str = "20200101",
        end_time: str = "",
        skip_download: bool = False,
        stall_check: Callable[[], bool] | None = None,
    ) -> int:
        """同步财务报表 (Balance + Income + CashFlow)"""
        if not end_time:
            end_time = datetime.now().strftime("%Y%m%d")

        report_tables = ["Balance", "Income", "CashFlow"]

        if stall_check and stall_check():
            logger.warning("sync_reports: 开始即滞停, 跳过本批")
            return 0

        if not skip_download:
            if stall_check and stall_check():
                return 0
            self.engine.download_financial(
                stock_list,
                table_list=report_tables,
                start_time=start_time,
                end_time=end_time,
            )

        if stall_check and stall_check():
            return 0

        raw = self.client.get_financial_data(
            stock_list=stock_list,
            table_list=report_tables,
            start_time=start_time,
            end_time=end_time,
            report_type="announce_time",
        )

        field_map = {
            "total_assets": ("Balance", "tot_assets"),
            "total_liabilities": ("Balance", "tot_liab"),
            "total_equity": ("Balance", "total_equity"),
            "total_revenue": ("Income", "revenue"),
            "operating_profit": ("Income", "oper_profit"),
            "net_profit": ("Income", "net_profit_incl_min_int_inc"),
            "gross_profit": ("Income", "revenue_inc"),
            "operating_cash_flow": ("CashFlow", "net_cash_flows_oper_act"),
            "net_cash_flow": ("CashFlow", "net_incr_cash_cash_equ"),
        }

        to_write: list[dict] = []
        for qmt_code in stock_list:
            code = qmt_code.split(".")[0]
            record_by_date: Dict[str, dict] = {}

            for db_field, (table, col) in field_map.items():
                table_df = raw.get(table)
                if table_df is None or not isinstance(table_df, pd.DataFrame):
                    continue
                if col not in table_df.columns:
                    continue
                for idx, val in table_df[col].items():
                    try:
                        dt_key = str(pd.Timestamp(idx).date())
                    except Exception:
                        continue
                    if dt_key not in record_by_date:
                        record_by_date[dt_key] = {
                            "code": code,
                            "report_type": "combined",
                            "report_period": "quarterly",
                            "report_date": pd.Timestamp(idx).date(),
                        }
                    record_by_date[dt_key][db_field] = _safe_float_val(val)

            to_write.extend(record_by_date.values())

        n_written = 0
        for i in range(0, len(to_write), DEFAULT_TABLE_UPSERT_FLUSH):
            if stall_check and stall_check():
                logger.warning("sync_reports: 落盘前滞停, 已落 %d 行, 本批共 %d 行未写完", n_written, len(to_write))
                return n_written
            batch = to_write[i: i + DEFAULT_TABLE_UPSERT_FLUSH]
            with get_session() as session:
                stmt = insert(StockFinancialReport).values(batch)
                stmt = stmt.on_conflict_do_nothing()
                session.execute(stmt)
            log_upsert_commit("qmt.financial_report", len(batch))
            n_written += len(batch)
        total = n_written

        logger.info(f"已同步 {total} 条财务报表记录")
        return total

    def sync_indicators(
        self,
        stock_list: List[str],
        start_time: str = "20200101",
        end_time: str = "",
        skip_download: bool = False,
        stall_check: Callable[[], bool] | None = None,
    ) -> int:
        """同步每股指标 (Pershareindex)"""
        if not end_time:
            end_time = datetime.now().strftime("%Y%m%d")

        if stall_check and stall_check():
            return 0

        if not skip_download:
            if stall_check and stall_check():
                return 0
            self.engine.download_financial(
                stock_list,
                table_list=["Pershareindex"],
                start_time=start_time,
                end_time=end_time,
            )

        if stall_check and stall_check():
            return 0

        raw = self.client.get_financial_data(
            stock_list=stock_list,
            table_list=["Pershareindex"],
            start_time=start_time,
            end_time=end_time,
            report_type="announce_time",
        )

        indicator_df = raw.get("Pershareindex")
        if indicator_df is None or not isinstance(indicator_df, pd.DataFrame) or indicator_df.empty:
            logger.warning("无财务指标数据")
            return 0

        col_map = {
            "eps_basic": "s_fa_eps_basic",
            "bps": "s_fa_bps",
            "roe_weighted": "du_return_on_equity",
            "net_profit_margin": "net_profit",
            "gross_profit_margin": "gross_profit",
        }

        to_write: list[dict] = []
        for qmt_code in stock_list:
            code = qmt_code.split(".")[0]
            for idx, row in indicator_df.iterrows():
                try:
                    report_date = pd.Timestamp(idx).date()
                except Exception:
                    continue
                record = {"code": code, "report_date": report_date}
                for db_col, qmt_col in col_map.items():
                    record[db_col] = _safe_float_from_row(row, qmt_col)
                to_write.append(record)

        n_written = 0
        for i in range(0, len(to_write), DEFAULT_TABLE_UPSERT_FLUSH):
            if stall_check and stall_check():
                logger.warning("sync_indicators: 落盘前滞停, 已落 %d 行, 本批 %d 行", n_written, len(to_write))
                return n_written
            batch = to_write[i: i + DEFAULT_TABLE_UPSERT_FLUSH]
            with get_session() as session:
                stmt = insert(StockFinancialIndicator).values(batch)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["code", "report_date"],
                    set_={
                        "eps_basic": stmt.excluded.eps_basic,
                        "bps": stmt.excluded.bps,
                        "roe_weighted": stmt.excluded.roe_weighted,
                        "net_profit_margin": stmt.excluded.net_profit_margin,
                        "gross_profit_margin": stmt.excluded.gross_profit_margin,
                    },
                )
                session.execute(stmt)
            log_upsert_commit("qmt.financial_indicator", len(batch))
            n_written += len(batch)
        total = n_written

        logger.info(f"已同步 {total} 条财务指标记录")
        return total

    def sync_capital(
        self,
        stock_list: List[str],
        start_time: str = "20200101",
        end_time: str = "",
    ) -> int:
        """同步股本数据 (Capital 表)"""
        if not end_time:
            end_time = datetime.now().strftime("%Y%m%d")

        self.engine.download_financial(
            stock_list, table_list=["Capital"],
            start_time=start_time, end_time=end_time,
        )

        raw = self.client.get_financial_data(
            stock_list=stock_list,
            table_list=["Capital"],
            start_time=start_time,
            end_time=end_time,
            report_type="announce_time",
        )

        cap_df = raw.get("Capital")
        if cap_df is None or not isinstance(cap_df, pd.DataFrame) or cap_df.empty:
            logger.warning("无股本数据")
            return 0

        updates: list[tuple[str, float]] = []
        for qmt_code in stock_list:
            code = qmt_code.split(".")[0]
            total_cap = _safe_float_from_row(cap_df.iloc[-1], "total_capital") if len(cap_df) > 0 else None
            if total_cap is not None:
                updates.append((code, total_cap))

        for i in range(0, len(updates), DEFAULT_TABLE_UPSERT_FLUSH):
            chunk = updates[i: i + DEFAULT_TABLE_UPSERT_FLUSH]
            with get_session() as session:
                for code, total_cap in chunk:
                    stmt = (
                        Stock.__table__.update()
                        .where(Stock.code == code)
                        .values(market_cap=total_cap)
                    )
                    session.execute(stmt)
            log_upsert_commit("qmt.stock_market_cap", len(chunk))
        total = len(updates)

        logger.info(f"已更新 {total} 只股票的股本数据")
        return total


def _safe_float_val(v):
    try:
        if v is not None and not pd.isna(v):
            return float(v)
    except Exception:
        pass
    return None


def _safe_float_from_row(row, col):
    try:
        v = row.get(col) if isinstance(row, dict) else (row[col] if col in row.index else None)
        if v is not None and not pd.isna(v):
            return float(v)
    except Exception:
        pass
    return None
