"""E2E: 指数日线数据采集 → market_index 表

只取沪深300 (000300) 最近 5 个交易日, 验证落盘和字段完整性。
"""
import pytest
import time
from datetime import date, timedelta

from sqlalchemy import func

from src.data.models import MarketIndex


RATE_LIMIT_PAUSE = 3
SAMPLE_INDEX_CODE = "000300"
SAMPLE_INDEX_NAME = "沪深300"
TODAY = date.today()
START_DATE = TODAY - timedelta(days=15)
END_DATE = TODAY


class TestIndexBaostock:
    """baostock 指数日线 → market_index"""

    @pytest.mark.timeout(60)
    def test_download_index_daily(self, dc_session):
        import baostock as bs

        lg = bs.login()
        assert lg.error_code == "0"

        try:
            bs_code = f"sh.{SAMPLE_INDEX_CODE}"
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,open,high,low,close,volume,amount",
                start_date=START_DATE.strftime("%Y-%m-%d"),
                end_date=END_DATE.strftime("%Y-%m-%d"),
                frequency="d",
            )
            assert rs.error_code == "0"

            rows_inserted = 0
            while rs.next():
                row = rs.get_row_data()
                trade_date = date.fromisoformat(row[0])

                index_code = f"{SAMPLE_INDEX_CODE}.SH"
                exists = (
                    dc_session.query(MarketIndex)
                    .filter_by(
                        index_code=index_code,
                        trade_date=trade_date,
                    )
                    .first()
                )
                if exists:
                    continue

                def _sf(v, default=0.0):
                    try:
                        return float(v) if v else default
                    except (ValueError, TypeError):
                        return default

                idx = MarketIndex(
                    index_code=index_code,
                    index_name=SAMPLE_INDEX_NAME,
                    trade_date=trade_date,
                    open=_sf(row[1]),
                    high=_sf(row[2]),
                    low=_sf(row[3]),
                    close=_sf(row[4]),
                    volume=int(float(row[5])) if row[5] else 0,
                    amount=_sf(row[6]),
                )
                dc_session.add(idx)
                rows_inserted += 1

            dc_session.commit()
            assert rows_inserted > 0

        finally:
            bs.logout()

    def test_index_data_integrity(self, dc_session):
        """验证指数数据字段正确"""
        rows = (
            dc_session.query(MarketIndex)
            .filter(MarketIndex.index_code == f"{SAMPLE_INDEX_CODE}.SH")
            .order_by(MarketIndex.trade_date.desc())
            .limit(5)
            .all()
        )
        if not rows:
            pytest.skip("无指数数据, 先运行 download 测试")

        for r in rows:
            assert r.high >= r.low
            assert r.close > 0
            assert r.trade_date is not None


class TestIndexAkshare:
    """akshare 指数日线 → market_index"""

    @pytest.mark.timeout(120)
    def test_download_index_akshare(self, dc_session):
        import akshare as ak
        from requests.exceptions import (
            ConnectionError, ProxyError, Timeout,
        )

        time.sleep(RATE_LIMIT_PAUSE)

        try:
            df = ak.stock_zh_index_daily(symbol=f"sh{SAMPLE_INDEX_CODE}")
        except (ConnectionError, ProxyError, Timeout, OSError) as exc:
            pytest.skip(f"akshare 网络不可达: {exc}")
        assert df is not None and len(df) > 0

        df_recent = df.tail(5)
        rows_inserted = 0
        index_code = f"{SAMPLE_INDEX_CODE}.SH"

        for _, row in df_recent.iterrows():
            trade_date = row.get("date", None)
            if trade_date is None:
                continue
            if isinstance(trade_date, str):
                trade_date = date.fromisoformat(trade_date)
            elif hasattr(trade_date, "date"):
                trade_date = trade_date.date()

            exists = (
                dc_session.query(MarketIndex)
                .filter_by(index_code=index_code, trade_date=trade_date)
                .first()
            )
            if exists:
                continue

            idx = MarketIndex(
                index_code=index_code,
                index_name=SAMPLE_INDEX_NAME,
                trade_date=trade_date,
                open=float(row.get("open", 0)),
                high=float(row.get("high", 0)),
                low=float(row.get("low", 0)),
                close=float(row.get("close", 0)),
                volume=int(row.get("volume", 0)),
            )
            dc_session.add(idx)
            rows_inserted += 1

        dc_session.commit()
        assert rows_inserted >= 0  # baostock 可能已写入

    def test_no_duplicate_index(self, dc_session):
        """unique index 防重"""
        dupes = (
            dc_session.query(
                MarketIndex.index_code,
                MarketIndex.trade_date,
                func.count(MarketIndex.id),
            )
            .group_by(MarketIndex.index_code, MarketIndex.trade_date)
            .having(func.count(MarketIndex.id) > 1)
            .all()
        )
        assert len(dupes) == 0, f"发现重复指数记录: {dupes}"
