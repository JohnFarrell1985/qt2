"""通过 akshare 采集 A 股数据并入库 PostgreSQL

作为 QMT 数据源的备选/主力数据源, 支持:
- A09: 股票列表同步
- A10: 日线增量同步
- A11: 指数数据同步

akshare 始终延迟导入, CI 环境无需安装。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert

from src.common.config import settings
from src.common.db import get_session
from src.common.logger import get_logger
from src.data.models import Stock, StockDaily, MarketIndex

logger = get_logger(__name__)

INDEX_NAME_MAP: dict[str, str] = {
    "000001": "上证综指",
    "399001": "深证成指",
    "000300": "沪深300",
    "000905": "中证500",
    "000852": "中证1000",
    "399006": "创业板指",
    "000688": "科创50",
}

_DAILY_COLUMN_MAP: dict[str, str] = {
    "日期": "trade_date",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "成交额": "amount",
    "振幅": "amplitude",
    "涨跌幅": "change_pct",
    "涨跌额": "change",
    "换手率": "turnover_rate",
}

_INDEX_COLUMN_MAP: dict[str, str] = {
    "日期": "trade_date",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "成交额": "amount",
}


def _exchange_from_code(code: str) -> str:
    """根据股票代码前缀判断交易所"""
    if code.startswith("6"):
        return "SH"
    if code.startswith(("0", "3")):
        return "SZ"
    if code.startswith(("4", "8")):
        return "BJ"
    return ""


class AkshareDataSync:
    """通过 akshare 采集 A 股数据并入库 PostgreSQL"""

    def __init__(self):
        from src.datacollect.rate_limiter import TokenBucketLimiter

        self.limiter = TokenBucketLimiter.for_domain(
            "akshare",
            rate=settings.datacollect.akshare_rate,
            burst=settings.datacollect.akshare_burst,
        )

    def _call_ak(self, func_name: str, **kwargs):
        """调用 akshare 函数, 带限流控制"""
        import akshare as ak

        fn = getattr(ak, func_name, None)
        if fn is None:
            raise AttributeError(f"akshare 没有函数: {func_name}")

        self.limiter.acquire()
        return fn(**kwargs)

    # ----------------------------------------------------------------
    # A09: 股票列表同步
    # ----------------------------------------------------------------
    def sync_stock_list(self) -> int:
        """同步全部 A 股股票列表到 stocks 表

        Returns:
            入库股票数量
        """
        import akshare as ak

        logger.info("开始同步 A 股股票列表 (akshare)...")

        df = None
        try:
            self.limiter.acquire()
            df = ak.stock_info_a_code_name()
        except Exception as e:
            logger.warning("stock_info_a_code_name 失败 (%s), 尝试 stock_zh_a_spot_em 备用源...", e)

        if df is None or df.empty:
            try:
                df = ak.stock_zh_a_spot_em()
                if df is not None and not df.empty:
                    df = df.rename(columns={"代码": "code", "名称": "name"})
            except Exception as e2:
                logger.error("备用源 stock_zh_a_spot_em 也失败: %s", e2)
                return 0

        if df is None or df.empty:
            logger.warning("akshare 所有股票列表源均返回空数据")
            return 0

        records: list[dict] = []
        for _, row in df.iterrows():
            code = str(row.get("code", "")).strip()
            name = str(row.get("name", "")).strip()
            if not code or len(code) != 6:
                continue
            records.append({
                "code": code,
                "name": name,
                "exchange": _exchange_from_code(code),
            })

        if not records:
            logger.warning("未解析到有效的股票记录")
            return 0

        count = 0
        with get_session() as session:
            for i in range(0, len(records), 500):
                batch = records[i: i + 500]
                stmt = insert(Stock).values(batch)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["code"],
                    set_={
                        "name": stmt.excluded.name,
                        "exchange": stmt.excluded.exchange,
                    },
                )
                session.execute(stmt)
                count += len(batch)

        logger.info("A 股股票列表同步完成, 共 %d 只", count)
        return count

    # ----------------------------------------------------------------
    # A10: 日线增量同步
    # ----------------------------------------------------------------
    def sync_daily_incremental(self, days_back: int = 30) -> int:
        """增量同步日线数据: 对每只股票补齐最近 days_back 天内缺失的日线

        Returns:
            入库记录总数
        """
        logger.info("开始增量同步日线数据 (days_back=%d)...", days_back)
        end_date = datetime.now().strftime("%Y%m%d")
        fallback_start = (datetime.now() - timedelta(days=days_back)).strftime("%Y%m%d")

        with get_session() as session:
            stocks = session.query(Stock.code).all()
        stock_codes = [row[0] for row in stocks]

        if not stock_codes:
            logger.warning("stocks 表为空, 请先运行 sync_stock_list()")
            return 0

        max_dates: dict[str, str] = {}
        with get_session() as session:
            rows = (
                session.query(StockDaily.code, func.max(StockDaily.trade_date))
                .group_by(StockDaily.code)
                .all()
            )
            for code, max_date in rows:
                if max_date:
                    max_dates[code] = max_date.strftime("%Y%m%d")

        total_inserted = 0
        total_stocks = len(stock_codes)
        batch_size = settings.download.batch_size or 500

        for batch_idx in range(0, total_stocks, batch_size):
            batch_codes = stock_codes[batch_idx: batch_idx + batch_size]
            batch_num = batch_idx // batch_size + 1
            total_batches = (total_stocks + batch_size - 1) // batch_size
            logger.info(
                "日线同步批次 %d/%d (%d 只股票)...",
                batch_num, total_batches, len(batch_codes),
            )

            batch_records: list[dict] = []
            for code in batch_codes:
                start_date = max_dates.get(code, fallback_start)
                try:
                    records = self._fetch_daily_for_stock(code, start_date, end_date)
                    batch_records.extend(records)
                except Exception as e:
                    logger.warning("获取 %s 日线失败: %s", code, e)

            if batch_records:
                with get_session() as session:
                    inserted = _bulk_upsert_daily(session, batch_records)
                    total_inserted += inserted

            logger.info(
                "批次 %d/%d 完成, 本批入库 %d 条",
                batch_num, total_batches, len(batch_records),
            )

        logger.info("日线增量同步完成, 共入库 %d 条", total_inserted)
        return total_inserted

    def _fetch_daily_for_stock(
        self, code: str, start_date: str, end_date: str
    ) -> list[dict]:
        """获取单只股票的日线数据并转换为入库记录列表"""
        import akshare as ak

        self.limiter.acquire()
        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start_date,
            end_date=end_date,
            adjust="qfq",
        )

        if df is None or df.empty:
            return []

        records: list[dict] = []
        for _, row in df.iterrows():
            trade_date_raw = row.get("日期")
            if trade_date_raw is None:
                continue
            try:
                if hasattr(trade_date_raw, "date"):
                    trade_date = trade_date_raw.date()
                else:
                    trade_date = datetime.strptime(str(trade_date_raw), "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue

            records.append({
                "code": code,
                "trade_date": trade_date,
                "open": _safe_float(row, "开盘"),
                "high": _safe_float(row, "最高"),
                "low": _safe_float(row, "最低"),
                "close": _safe_float(row, "收盘"),
                "volume": _safe_int(row, "成交量"),
                "amount": _safe_float(row, "成交额"),
                "amplitude": _safe_float(row, "振幅"),
                "change_pct": _safe_float(row, "涨跌幅"),
                "change": _safe_float(row, "涨跌额"),
                "turnover_rate": _safe_float(row, "换手率"),
            })
        return records

    # ----------------------------------------------------------------
    # A11: 指数数据同步
    # ----------------------------------------------------------------
    def sync_index_data(self, start_date: str = "20230101") -> int:
        """同步主要指数日线数据到 market_index 表

        Returns:
            入库记录总数
        """
        import akshare as ak

        end_date = datetime.now().strftime("%Y%m%d")
        logger.info(
            "开始同步指数数据 (%s ~ %s, %d 个指数)...",
            start_date, end_date, len(INDEX_NAME_MAP),
        )

        total_inserted = 0

        for index_code, index_name in INDEX_NAME_MAP.items():
            try:
                self.limiter.acquire()
                df = ak.stock_zh_index_daily_em(
                    symbol=index_code,
                    start_date=start_date,
                    end_date=end_date,
                )

                if df is None or df.empty:
                    logger.warning("指数 %s (%s) 无数据", index_code, index_name)
                    continue

                records = self._parse_index_df(index_code, index_name, df)
                if records:
                    with get_session() as session:
                        inserted = _bulk_upsert_index(session, records)
                        total_inserted += inserted

                logger.info(
                    "指数 %s (%s) 同步 %d 条",
                    index_code, index_name, len(records),
                )
            except Exception as e:
                logger.warning("同步指数 %s 失败: %s", index_code, e)

        logger.info("指数数据同步完成, 共入库 %d 条", total_inserted)
        return total_inserted

    def _parse_index_df(
        self, index_code: str, index_name: str, df
    ) -> list[dict]:
        """将 akshare 指数 DataFrame 转换为入库记录, 并补算涨跌额/涨跌幅"""
        records: list[dict] = []
        prev_close: float | None = None

        for _, row in df.iterrows():
            trade_date_raw = row.get("日期")
            if trade_date_raw is None:
                continue
            try:
                if hasattr(trade_date_raw, "date"):
                    trade_date = trade_date_raw.date()
                else:
                    trade_date = datetime.strptime(str(trade_date_raw), "%Y-%m-%d").date()
            except (ValueError, TypeError):
                continue

            close_val = _safe_float(row, "收盘")
            change_val = _safe_float(row, "涨跌额") if "涨跌额" in row.index else None
            change_pct_val = _safe_float(row, "涨跌幅") if "涨跌幅" in row.index else None

            if change_val is None and prev_close is not None and close_val is not None:
                change_val = round(close_val - prev_close, 4)
            if change_pct_val is None and prev_close and close_val is not None:
                change_pct_val = round((close_val - prev_close) / prev_close * 100, 4)

            records.append({
                "index_code": index_code,
                "index_name": index_name,
                "trade_date": trade_date,
                "open": _safe_float(row, "开盘"),
                "high": _safe_float(row, "最高"),
                "low": _safe_float(row, "最低"),
                "close": close_val,
                "volume": _safe_int(row, "成交量"),
                "amount": _safe_float(row, "成交额"),
                "change": change_val,
                "change_pct": change_pct_val,
            })

            if close_val is not None:
                prev_close = close_val

        return records


# ====================================================================
# 内部工具函数
# ====================================================================

def _safe_float(row, col: str) -> float | None:
    try:
        v = row.get(col) if hasattr(row, "get") else getattr(row, col, None)
        if v is not None:
            import pandas as pd
            if not pd.isna(v):
                return float(v)
    except (ValueError, TypeError):
        pass
    return None


def _safe_int(row, col: str) -> int | None:
    try:
        v = row.get(col) if hasattr(row, "get") else getattr(row, col, None)
        if v is not None:
            import pandas as pd
            if not pd.isna(v):
                return int(v)
    except (ValueError, TypeError):
        pass
    return None


def _bulk_upsert_daily(session, records: list[dict], batch_size: int = 1000) -> int:
    count = 0
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
                "amplitude": stmt.excluded.amplitude,
                "change_pct": stmt.excluded.change_pct,
                "change": stmt.excluded.change,
                "turnover_rate": stmt.excluded.turnover_rate,
            },
        )
        session.execute(stmt)
        count += len(batch)
    return count


def _bulk_upsert_index(session, records: list[dict], batch_size: int = 1000) -> int:
    count = 0
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
                "change": stmt.excluded.change,
                "change_pct": stmt.excluded.change_pct,
            },
        )
        session.execute(stmt)
        count += len(batch)
    return count


# ====================================================================
# CLI 入口
# ====================================================================

if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Akshare 数据同步 CLI")
    parser.add_argument(
        "task",
        choices=["stock_list", "daily", "index", "all"],
        help="同步任务: stock_list=股票列表, daily=日线, index=指数, all=全部",
    )
    parser.add_argument("--days-back", type=int, default=30, help="日线增量天数 (默认 30)")
    parser.add_argument("--start-date", type=str, default="20230101", help="指数起始日期 (默认 20230101)")
    args = parser.parse_args()

    syncer = AkshareDataSync()
    try:
        if args.task in ("stock_list", "all"):
            n = syncer.sync_stock_list()
            logger.info("sync_stock_list => %d", n)

        if args.task in ("daily", "all"):
            n = syncer.sync_daily_incremental(days_back=args.days_back)
            logger.info("sync_daily_incremental => %d", n)

        if args.task in ("index", "all"):
            n = syncer.sync_index_data(start_date=args.start_date)
            logger.info("sync_index_data => %d", n)
    except Exception as exc:
        logger.error("同步失败: %s", exc, exc_info=True)
        sys.exit(1)
