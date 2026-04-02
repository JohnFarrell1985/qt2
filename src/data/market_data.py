"""行情数据下载与同步

负责从QMT下载日线、分钟线、指数数据并存入PostgreSQL。

优化策略 (基于社区经验):
- 使用 DownloadEngine 分批下载, 每批 500 只
- 通过 callback + Event 等待异步 download 真正完成
- 使用 get_local_data 分批读取 (内存友好)
- 增量下载: incrementally=None 自动跳过已有数据
- 分批入库: 每读完一批就 upsert, 不全部加载到内存
"""
import pandas as pd
from datetime import datetime
from typing import List, Optional, Callable

from sqlalchemy.dialects.postgresql import insert

from src.common.db import get_session
from src.common.logger import get_logger
from src.data.models import StockDaily, StockMinute, Stock, MarketIndex
from src.data.qmt_client import QMTClient
from src.data.download_engine import DownloadEngine, get_default_start

logger = get_logger(__name__)

VALID_MINUTE_PERIODS = ("1m", "5m", "15m", "30m", "1h")
VALID_DAY_PLUS_PERIODS = ("1d", "1w", "1mon", "1q", "1hy", "1y")

MAJOR_INDICES = [
    ("000001.SH", "上证指数"),
    ("399001.SZ", "深证成指"),
    ("399006.SZ", "创业板指"),
    ("000300.SH", "沪深300"),
    ("000905.SH", "中证500"),
    ("000852.SH", "中证1000"),
    ("000688.SH", "科创50"),
    ("899050.BJ", "北证50"),
]


class MarketDataSync:
    """行情数据同步器"""

    def __init__(self, client: Optional[QMTClient] = None):
        self.client = client or QMTClient()
        self.engine = DownloadEngine(self.client)

    # ----------------------------------------------------------------
    # 股票列表
    # ----------------------------------------------------------------
    def sync_stock_list(self) -> int:
        """同步沪深A股股票列表到数据库"""
        codes = self.client.get_stock_list_in_sector("沪深A股")
        logger.info(f"获取到 {len(codes)} 只A股")

        count = 0
        with get_session() as session:
            for code in codes:
                try:
                    detail = self.client.get_instrument_detail(code)
                    stock_data = {
                        "code": code.split(".")[0],
                        "name": detail.get("InstrumentName", ""),
                        "exchange": code.split(".")[-1] if "." in code else "",
                        "list_date": _parse_open_date(detail.get("OpenDate")),
                    }
                    stmt = insert(Stock).values(**stock_data).on_conflict_do_update(
                        index_elements=["code"],
                        set_={
                            "name": stock_data["name"],
                            "exchange": stock_data["exchange"],
                            "list_date": stock_data["list_date"],
                        },
                    )
                    session.execute(stmt)
                    count += 1
                except Exception as e:
                    logger.warning(f"同步股票 {code} 失败: {e}")
        logger.info(f"已同步 {count} 只股票基础信息")
        return count

    # ----------------------------------------------------------------
    # 日线数据
    # ----------------------------------------------------------------
    def sync_daily_data(
        self,
        stock_list: List[str],
        start_date: str = "",
        end_date: str = "",
        incremental: bool = True,
    ) -> int:
        """同步日线数据

        流程: 分批download → 分批get_local_data → 分批upsert
        start_date 为空时自动使用配置 DL_START_1D (默认20160101, 近10年)
        """
        if not start_date:
            start_date = get_default_start("1d")
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")

        dl_progress = self.engine.download_kline(
            stock_list, period="1d",
            start_time=start_date, end_time=end_date,
            incremental=incremental,
        )

        total = 0
        with get_session() as session:
            for qmt_code, df in self.engine.get_local_kline_batched(
                stock_list, period="1d",
                start_time=start_date, end_time=end_date,
                dividend_type="front",
            ):
                code = qmt_code.split(".")[0]
                records = _kline_df_to_daily_records(code, df)
                if records:
                    _bulk_upsert_daily(session, records)
                    total += len(records)

        logger.info(
            f"已同步 {total} 条日线数据 "
            f"(下载: {dl_progress.finished_stocks}/{dl_progress.total_stocks}只, "
            f"失败{dl_progress.failed_batches}批)"
        )
        return total

    # ----------------------------------------------------------------
    # 分钟线数据
    # ----------------------------------------------------------------
    def sync_minute_data(
        self,
        stock_list: List[str],
        period: str = "5m",
        start_date: str = "",
        end_date: str = "",
        incremental: bool = True,
    ) -> int:
        """同步分钟线数据

        start_date 为空时按周期使用默认值:
        - 1m: 最近1年 (数据量巨大, ~5000只 x 240条/天 x 250天)
        - 5m: 最近3年
        - 15m/30m/1h: 最近3年
        """
        if period not in VALID_MINUTE_PERIODS:
            raise ValueError(f"无效周期 {period}, 支持: {VALID_MINUTE_PERIODS}")
        if not start_date:
            start_date = get_default_start(period)
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")

        dl_progress = self.engine.download_kline(
            stock_list, period=period,
            start_time=start_date, end_time=end_date,
            incremental=incremental,
        )

        total = 0
        with get_session() as session:
            for qmt_code, df in self.engine.get_local_kline_batched(
                stock_list, period=period,
                start_time=start_date, end_time=end_date,
                dividend_type="front",
            ):
                code = qmt_code.split(".")[0]
                records = _kline_df_to_minute_records(code, df, period)
                if records:
                    _bulk_upsert_minute(session, records)
                    total += len(records)

        logger.info(
            f"已同步 {total} 条 {period} 分钟线 "
            f"(下载: {dl_progress.finished_stocks}/{dl_progress.total_stocks}只)"
        )
        return total

    # ----------------------------------------------------------------
    # 指数数据
    # ----------------------------------------------------------------
    def sync_index_data(
        self,
        start_date: str = "",
        end_date: str = "",
        index_list: Optional[List[tuple]] = None,
        incremental: bool = True,
    ) -> int:
        """同步主要指数日线数据"""
        if not start_date:
            start_date = get_default_start("1d")
        if not end_date:
            end_date = datetime.now().strftime("%Y%m%d")
        if index_list is None:
            index_list = MAJOR_INDICES

        index_codes = [c for c, _ in index_list]
        name_map = {c: n for c, n in index_list}

        self.engine.download_kline(
            index_codes, period="1d",
            start_time=start_date, end_time=end_date,
            incremental=incremental,
        )

        total = 0
        with get_session() as session:
            for qmt_code, df in self.engine.get_local_kline_batched(
                index_codes, period="1d",
                start_time=start_date, end_time=end_date,
                dividend_type="none",
            ):
                idx_code = qmt_code.split(".")[0]
                idx_name = name_map.get(qmt_code, "")
                records = _kline_df_to_index_records(idx_code, idx_name, df)
                if records:
                    _bulk_upsert_index(session, records)
                    total += len(records)

        logger.info(f"已同步 {total} 条指数日线数据")
        return total


# ====================================================================
# 内部工具函数
# ====================================================================

def _parse_open_date(v) -> Optional[object]:
    if not v:
        return None
    try:
        s = str(v).strip()
        if len(s) >= 8:
            return datetime.strptime(s[:8], "%Y%m%d").date()
    except Exception:
        pass
    return None


def _parse_kline_timestamp(ts):
    try:
        if isinstance(ts, (int, float)):
            return pd.Timestamp(ts, unit="ms").date()
        return pd.Timestamp(ts).date()
    except Exception:
        return None


def _kline_df_to_daily_records(code: str, df) -> List[dict]:
    records = []
    for ts, row in df.iterrows():
        trade_date = _parse_kline_timestamp(ts)
        if trade_date is None:
            continue
        records.append({
            "code": code,
            "trade_date": trade_date,
            "open": float(row.get("open", 0)),
            "high": float(row.get("high", 0)),
            "low": float(row.get("low", 0)),
            "close": float(row.get("close", 0)),
            "volume": int(row.get("volume", 0)),
            "amount": float(row.get("amount", 0)),
            "pre_close": _safe_float(row, "preClose"),
        })
    return records


def _kline_df_to_minute_records(code: str, df, period: str) -> List[dict]:
    records = []
    for ts, row in df.iterrows():
        try:
            trade_time = pd.Timestamp(ts, unit="ms") if isinstance(ts, (int, float)) else pd.Timestamp(ts)
            trade_time = trade_time.to_pydatetime()
        except Exception:
            continue
        records.append({
            "code": code,
            "trade_time": trade_time,
            "period": period,
            "open": float(row.get("open", 0)),
            "high": float(row.get("high", 0)),
            "low": float(row.get("low", 0)),
            "close": float(row.get("close", 0)),
            "volume": int(row.get("volume", 0)),
            "amount": float(row.get("amount", 0)),
        })
    return records


def _kline_df_to_index_records(idx_code: str, idx_name: str, df) -> List[dict]:
    records = []
    for ts, row in df.iterrows():
        trade_date = _parse_kline_timestamp(ts)
        if trade_date is None:
            continue
        records.append({
            "index_code": idx_code,
            "index_name": idx_name,
            "trade_date": trade_date,
            "open": float(row.get("open", 0)),
            "high": float(row.get("high", 0)),
            "low": float(row.get("low", 0)),
            "close": float(row.get("close", 0)),
            "volume": int(row.get("volume", 0)),
            "amount": float(row.get("amount", 0)),
        })
    return records


def _safe_float(row, col):
    try:
        v = row.get(col) if hasattr(row, "get") else getattr(row, col, None)
        if v is not None and not pd.isna(v):
            return float(v)
    except Exception:
        pass
    return None


def _bulk_upsert_daily(session, records: List[dict], batch_size: int = 1000):
    for i in range(0, len(records), batch_size):
        batch = records[i: i + batch_size]
        stmt = insert(StockDaily).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=["code", "trade_date"],
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "amount": stmt.excluded.amount,
                "pre_close": stmt.excluded.pre_close,
            },
        )
        session.execute(stmt)


def _bulk_upsert_minute(session, records: List[dict], batch_size: int = 1000):
    for i in range(0, len(records), batch_size):
        batch = records[i: i + batch_size]
        stmt = insert(StockMinute).values(batch)
        stmt = stmt.on_conflict_do_nothing(constraint="uq_minute")
        session.execute(stmt)


def _bulk_upsert_index(session, records: List[dict], batch_size: int = 1000):
    for i in range(0, len(records), batch_size):
        batch = records[i: i + batch_size]
        stmt = insert(MarketIndex).values(batch)
        stmt = stmt.on_conflict_do_update(
            index_elements=["index_code", "trade_date"],
            set_={
                "index_name": stmt.excluded.index_name,
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
                "amount": stmt.excluded.amount,
            },
        )
        session.execute(stmt)
