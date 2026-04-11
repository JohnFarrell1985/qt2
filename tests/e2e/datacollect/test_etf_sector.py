"""E2E: ETF 与板块数据采集 → etf_info / etf_daily / sector_data 表

原则: 2 分钟无数据 = 不可用, 彻底放弃。

ETF: 手动 seed 1 只 ETF 信息, 只测日线下载 (单只/5天, 秒级)
板块: 手动写入 1 条板块记录验证落盘, 不调分页接口
"""
import pytest
import time
from datetime import date, timedelta

from requests.exceptions import ConnectionError, ProxyError, Timeout

from sqlalchemy import func

from src.data.models import ETFInfo, ETFDaily, SectorData


RATE_LIMIT_PAUSE = 3
TODAY = date.today()
START_DATE = TODAY - timedelta(days=15)

SAMPLE_ETF_CODE = "510300"
SAMPLE_ETF_NAME = "沪深300ETF"

_NETWORK_ERRORS = (ConnectionError, ProxyError, Timeout, OSError)


class TestETFDailyAkshare:
    """akshare ETF 日线 → etf_daily (单只 ETF, 秒级完成)"""

    @pytest.mark.timeout(120)
    def test_download_etf_daily(self, dc_session):
        import akshare as ak

        existing = dc_session.query(ETFInfo).filter_by(
            code=SAMPLE_ETF_CODE
        ).first()
        if not existing:
            dc_session.add(ETFInfo(code=SAMPLE_ETF_CODE, name=SAMPLE_ETF_NAME))
            dc_session.flush()

        time.sleep(RATE_LIMIT_PAUSE)
        try:
            df = ak.fund_etf_hist_em(
                symbol=SAMPLE_ETF_CODE,
                period="daily",
                start_date=START_DATE.strftime("%Y%m%d"),
                end_date=TODAY.strftime("%Y%m%d"),
                adjust="qfq",
            )
        except _NETWORK_ERRORS as exc:
            pytest.skip(f"akshare ETF 网络不可达: {exc}")

        assert df is not None and len(df) > 0

        rows_inserted = 0
        for _, row in df.iterrows():
            trade_date = row["日期"]
            if isinstance(trade_date, str):
                trade_date = date.fromisoformat(trade_date)
            elif hasattr(trade_date, "date"):
                trade_date = trade_date.date()

            exists = (
                dc_session.query(ETFDaily)
                .filter_by(code=SAMPLE_ETF_CODE, trade_date=trade_date)
                .first()
            )
            if exists:
                continue

            daily = ETFDaily(
                code=SAMPLE_ETF_CODE,
                trade_date=trade_date,
                open=float(row.get("开盘", 0)),
                high=float(row.get("最高", 0)),
                low=float(row.get("最低", 0)),
                close=float(row.get("收盘", 0)),
                volume=int(row.get("成交量", 0)),
                amount=float(row.get("成交额", 0)),
            )
            dc_session.add(daily)
            rows_inserted += 1

        dc_session.commit()
        assert rows_inserted > 0

    @pytest.mark.timeout(120)
    def test_etf_daily_integrity(self, dc_session):
        rows = (
            dc_session.query(ETFDaily)
            .filter_by(code=SAMPLE_ETF_CODE)
            .order_by(ETFDaily.trade_date.desc())
            .limit(5)
            .all()
        )
        if not rows:
            pytest.skip("etf_daily 表为空")
        for r in rows:
            assert r.close > 0
            assert r.high >= r.low


class TestSectorManualSeed:
    """板块数据落盘验证 — 手动 seed, 不调分页接口

    stock_board_industry_name_em 分页 4 页, 每页 5s+ = 20s+,
    且受限于代理稳定性; 这里只验证 ORM → DB 写入正确。
    """

    @pytest.mark.timeout(120)
    def test_sector_write_and_read(self, dc_session):
        sector = SectorData(
            sector_name="计算机",
            trade_date=TODAY,
            change_pct=1.25,
            net_inflow=3.5,
            leading_stock="中科曙光",
        )
        existing = (
            dc_session.query(SectorData)
            .filter_by(sector_name="计算机", trade_date=TODAY)
            .first()
        )
        if not existing:
            dc_session.add(sector)
            dc_session.commit()

        result = (
            dc_session.query(SectorData)
            .filter_by(sector_name="计算机", trade_date=TODAY)
            .first()
        )
        assert result is not None
        assert result.sector_name == "计算机"
        assert result.change_pct == 1.25
        assert result.leading_stock == "中科曙光"

    @pytest.mark.timeout(120)
    def test_sector_unique_constraint(self, dc_session):
        """unique index 防重: 同 sector_name + trade_date 不应重复"""
        dupes = (
            dc_session.query(
                SectorData.sector_name,
                SectorData.trade_date,
                func.count(SectorData.id),
            )
            .group_by(SectorData.sector_name, SectorData.trade_date)
            .having(func.count(SectorData.id) > 1)
            .all()
        )
        assert len(dupes) == 0, f"发现重复板块记录: {dupes}"
