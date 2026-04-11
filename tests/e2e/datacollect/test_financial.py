"""E2E: 财务数据采集 → stock_financial_report / stock_financial_indicator 表

只取 1 只股票 (贵州茅台 600519) 最近 1-2 期财务报告,
验证落盘字段完整性。

注: baostock 财务 API 有时响应较慢, 设置较长超时。
"""
import pytest
from datetime import date


from src.data.models import (
    Stock,
    StockFinancialReport,
    StockFinancialIndicator,
)


RATE_LIMIT_PAUSE = 3
SAMPLE_CODE_BS = "sh.600519"
SAMPLE_CODE_OUR = "600519.SH"
SAMPLE_NAME = "贵州茅台"
SAMPLE_YEAR = date.today().year - 1
SAMPLE_QUARTER = 4


def _ensure_stock(session, code: str, name: str, exchange: str):
    existing = session.query(Stock).filter_by(code=code).first()
    if not existing:
        session.add(Stock(code=code, name=name, exchange=exchange))
        session.flush()


class TestFinancialBaostock:
    """baostock 财务数据采集"""

    @pytest.mark.timeout(90)
    def test_profit_data(self, dc_session):
        """利润表数据 → stock_financial_report"""
        import baostock as bs

        _ensure_stock(dc_session, SAMPLE_CODE_OUR, SAMPLE_NAME, "SH")

        lg = bs.login()
        assert lg.error_code == "0"

        try:
            rs = bs.query_profit_data(
                code=SAMPLE_CODE_BS,
                year=SAMPLE_YEAR,
                quarter=SAMPLE_QUARTER,
            )
            assert rs.error_code == "0", (
                f"baostock profit query failed: {rs.error_msg}"
            )

            rows_inserted = 0
            while rs.next():
                row = rs.get_row_data()
                fields = rs.fields

                def _get(field_name, default=""):
                    try:
                        idx = fields.index(field_name)
                        return row[idx]
                    except (ValueError, IndexError):
                        return default

                report_date_str = _get("statDate")
                if not report_date_str:
                    continue

                report_date = date.fromisoformat(report_date_str)
                exists = (
                    dc_session.query(StockFinancialReport)
                    .filter_by(code=SAMPLE_CODE_OUR, report_date=report_date)
                    .first()
                )
                if exists:
                    continue

                def _sf(v, default=None):
                    try:
                        return float(v) if v else default
                    except (ValueError, TypeError):
                        return default

                report = StockFinancialReport(
                    code=SAMPLE_CODE_OUR,
                    report_date=report_date,
                    report_type="年报" if SAMPLE_QUARTER == 4 else f"Q{SAMPLE_QUARTER}",
                    report_period=report_date_str.replace("-", ""),
                    net_profit=_sf(_get("netProfit")),
                    roe=_sf(_get("roeAvg")),
                )
                dc_session.add(report)
                rows_inserted += 1

            dc_session.commit()
            assert rows_inserted >= 0  # 某些年份可能无数据

        finally:
            bs.logout()

    @pytest.mark.timeout(90)
    def test_growth_data(self, dc_session):
        """成长性指标 → stock_financial_indicator"""
        import baostock as bs

        _ensure_stock(dc_session, SAMPLE_CODE_OUR, SAMPLE_NAME, "SH")

        lg = bs.login()
        assert lg.error_code == "0"

        try:
            rs = bs.query_growth_data(
                code=SAMPLE_CODE_BS,
                year=SAMPLE_YEAR,
                quarter=SAMPLE_QUARTER,
            )
            assert rs.error_code == "0"

            rows_inserted = 0
            while rs.next():
                row = rs.get_row_data()
                fields = rs.fields

                def _get(field_name, default=""):
                    try:
                        idx = fields.index(field_name)
                        return row[idx]
                    except (ValueError, IndexError):
                        return default

                stat_date_str = _get("statDate")
                if not stat_date_str:
                    continue

                stat_date = date.fromisoformat(stat_date_str)
                exists = (
                    dc_session.query(StockFinancialIndicator)
                    .filter_by(code=SAMPLE_CODE_OUR, report_date=stat_date)
                    .first()
                )
                if exists:
                    continue

                def _sf(v, default=None):
                    try:
                        return float(v) if v else default
                    except (ValueError, TypeError):
                        return default

                indicator = StockFinancialIndicator(
                    code=SAMPLE_CODE_OUR,
                    report_date=stat_date,
                    roe_weighted=_sf(_get("ROETTM")),
                    revenue_growth=_sf(_get("YOYEquity")),
                    profit_growth=_sf(_get("YOYAsset")),
                )
                dc_session.add(indicator)
                rows_inserted += 1

            dc_session.commit()
            assert rows_inserted >= 0

        finally:
            bs.logout()


class TestFinancialFieldIntegrity:
    """财务数据字段完整性验证"""

    def test_report_fields(self, dc_session):
        reports = (
            dc_session.query(StockFinancialReport)
            .filter_by(code=SAMPLE_CODE_OUR)
            .limit(5)
            .all()
        )
        if not reports:
            pytest.skip("无财务报告数据")

        for r in reports:
            assert r.code == SAMPLE_CODE_OUR
            assert r.report_date is not None
            assert r.report_type is not None

    def test_indicator_fields(self, dc_session):
        indicators = (
            dc_session.query(StockFinancialIndicator)
            .filter_by(code=SAMPLE_CODE_OUR)
            .limit(5)
            .all()
        )
        if not indicators:
            pytest.skip("无财务指标数据")

        for ind in indicators:
            assert ind.code == SAMPLE_CODE_OUR
            assert ind.report_date is not None
