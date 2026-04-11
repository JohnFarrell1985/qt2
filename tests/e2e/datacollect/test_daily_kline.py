"""E2E: 日线数据采集 → stock_daily 表

只取 1-2 只股票最近 5 个交易日的日线, 验证落盘和字段完整性。
选用流动性高、不易退市的标的 (贵州茅台 600519、平安银行 000001)
以保证数据源有数据返回。
"""
import pytest
import time
from datetime import date, timedelta

from sqlalchemy import func

from src.data.models import Stock, StockDaily


RATE_LIMIT_PAUSE = 3

SAMPLE_STOCKS_BS = [
    ("sh.600519", "600519.SH", "贵州茅台"),
]
SAMPLE_STOCKS_AK = [
    ("000001", "000001.SZ", "平安银行"),
]

TODAY = date.today()
START_DATE = TODAY - timedelta(days=15)
END_DATE = TODAY


def _ensure_stock(session, code: str, name: str, exchange: str):
    """确保 stocks 表中存在该股票"""
    existing = session.query(Stock).filter_by(code=code).first()
    if not existing:
        session.add(Stock(code=code, name=name, exchange=exchange))
        session.flush()


class TestDailyKlineBaostock:
    """baostock 日线采集 → stock_daily"""

    @pytest.mark.timeout(60)
    def test_download_daily(self, dc_session):
        import baostock as bs

        lg = bs.login()
        assert lg.error_code == "0"

        try:
            for bs_code, our_code, name in SAMPLE_STOCKS_BS:
                exchange = our_code.split(".")[-1]
                _ensure_stock(dc_session, our_code, name, exchange)

                rs = bs.query_history_k_data_plus(
                    bs_code,
                    "date,open,high,low,close,preclose,volume,amount,turn",
                    start_date=START_DATE.strftime("%Y-%m-%d"),
                    end_date=END_DATE.strftime("%Y-%m-%d"),
                    frequency="d",
                    adjustflag="2",
                )
                assert rs.error_code == "0", (
                    f"baostock query failed: {rs.error_msg}"
                )

                rows_inserted = 0
                while rs.next():
                    row = rs.get_row_data()
                    trade_date = date.fromisoformat(row[0])

                    exists = (
                        dc_session.query(StockDaily)
                        .filter_by(code=our_code, trade_date=trade_date)
                        .first()
                    )
                    if exists:
                        continue

                    def _safe_float(v, default=0.0):
                        try:
                            return float(v) if v else default
                        except (ValueError, TypeError):
                            return default

                    daily = StockDaily(
                        code=our_code,
                        trade_date=trade_date,
                        open=_safe_float(row[1]),
                        high=_safe_float(row[2]),
                        low=_safe_float(row[3]),
                        close=_safe_float(row[4]),
                        pre_close=_safe_float(row[5]),
                        volume=int(float(row[6])) if row[6] else 0,
                        amount=_safe_float(row[7]),
                        turnover_rate=_safe_float(row[8]),
                    )
                    dc_session.add(daily)
                    rows_inserted += 1

                dc_session.commit()
                assert rows_inserted > 0, (
                    f"baostock {our_code} 无数据写入 "
                    f"({START_DATE} ~ {END_DATE})"
                )

        finally:
            bs.logout()

    def test_daily_data_integrity(self, dc_session):
        """验证已落盘日线数据的字段完整性"""
        rows = (
            dc_session.query(StockDaily)
            .filter(StockDaily.code == "600519.SH")
            .order_by(StockDaily.trade_date.desc())
            .limit(5)
            .all()
        )
        if not rows:
            pytest.skip("600519.SH 无日线数据, 先运行 download 测试")

        for r in rows:
            assert r.open > 0
            assert r.high >= r.low
            assert r.close > 0
            assert r.volume >= 0


class TestDailyKlineAkshare:
    """akshare 日线采集 → stock_daily (补充验证)"""

    @pytest.mark.timeout(60)
    def test_download_daily_akshare(self, dc_session):
        import akshare as ak
        from requests.exceptions import (
            ConnectionError, ProxyError, Timeout,
        )

        time.sleep(RATE_LIMIT_PAUSE)

        for raw_code, our_code, name in SAMPLE_STOCKS_AK:
            exchange = our_code.split(".")[-1]
            _ensure_stock(dc_session, our_code, name, exchange)

            try:
                df = ak.stock_zh_a_hist(
                    symbol=raw_code,
                    period="daily",
                    start_date=START_DATE.strftime("%Y%m%d"),
                    end_date=END_DATE.strftime("%Y%m%d"),
                    adjust="qfq",
                )
            except (ConnectionError, ProxyError, Timeout) as exc:
                pytest.skip(f"akshare 网络不可达: {exc}")
            assert df is not None and len(df) > 0, (
                f"akshare {our_code} 返回空数据"
            )

            rows_inserted = 0
            for _, row in df.iterrows():
                trade_date = row["日期"]
                if isinstance(trade_date, str):
                    trade_date = date.fromisoformat(trade_date)
                elif hasattr(trade_date, "date"):
                    trade_date = trade_date.date()

                exists = (
                    dc_session.query(StockDaily)
                    .filter_by(code=our_code, trade_date=trade_date)
                    .first()
                )
                if exists:
                    continue

                daily = StockDaily(
                    code=our_code,
                    trade_date=trade_date,
                    open=float(row.get("开盘", 0)),
                    high=float(row.get("最高", 0)),
                    low=float(row.get("最低", 0)),
                    close=float(row.get("收盘", 0)),
                    volume=int(row.get("成交量", 0)),
                    amount=float(row.get("成交额", 0)),
                    change=float(row.get("涨跌额", 0)),
                    change_pct=float(row.get("涨跌幅", 0)),
                    turnover_rate=float(row.get("换手率", 0)),
                    amplitude=float(row.get("振幅", 0)),
                )
                dc_session.add(daily)
                rows_inserted += 1

            dc_session.commit()
            assert rows_inserted > 0, (
                f"akshare {our_code} 无新数据写入"
            )

    def test_no_duplicate_records(self, dc_session):
        """验证 unique index 防重: 同 code + trade_date 不重复"""
        for _, our_code, _ in SAMPLE_STOCKS_AK:
            dupes = (
                dc_session.query(
                    StockDaily.code,
                    StockDaily.trade_date,
                    func.count(StockDaily.id),
                )
                .filter(StockDaily.code == our_code)
                .group_by(StockDaily.code, StockDaily.trade_date)
                .having(func.count(StockDaily.id) > 1)
                .all()
            )
            assert len(dupes) == 0, f"发现重复日线记录: {dupes}"
