"""E2E: 股票列表采集 → 落盘 DB

从多个数据源获取 A 股股票列表, 写入 stocks 表,
验证数据条数和字段完整性。

策略: 只获取列表 (通常 < 5000 行), 不涉及时间序列,
属于最轻量的采集操作。
"""
import pytest
import time

from sqlalchemy import func

from src.data.models import Stock


RATE_LIMIT_PAUSE = 3


class TestStockListBaostock:
    """baostock 股票列表采集 → stocks 表"""

    @pytest.mark.timeout(60)
    def test_sync_stock_list(self, dc_session):
        import baostock as bs

        lg = bs.login()
        assert lg.error_code == "0"

        try:
            rs = bs.query_stock_basic()
            rows = []
            while rs.error_code == "0" and rs.next():
                rows.append(rs.get_row_data())
        finally:
            bs.logout()

        assert len(rows) > 100, f"baostock 返回股票数过少: {len(rows)}"

        count = 0
        for row in rows[:50]:
            code_raw, name = row[0], row[1]
            if not code_raw.startswith("sh.") and not code_raw.startswith("sz."):
                continue

            prefix = code_raw[:3]
            suffix = code_raw[3:]
            exchange = "SH" if prefix == "sh." else "SZ"
            code = f"{suffix}.{exchange}"

            existing = dc_session.query(Stock).filter_by(code=code).first()
            if existing:
                continue

            stock = Stock(
                code=code,
                name=name or f"未知_{suffix}",
                exchange=exchange,
            )
            dc_session.add(stock)
            count += 1

        dc_session.commit()

        total = dc_session.query(func.count(Stock.code)).scalar()
        assert total >= count
        assert total > 0, "stocks 表应至少有记录"

    @pytest.mark.timeout(60)
    def test_stock_fields_complete(self, dc_session):
        """验证写入的 stock 记录字段不为空"""
        stocks = dc_session.query(Stock).limit(10).all()
        if not stocks:
            pytest.skip("stocks 表为空, 需先运行 sync 测试")

        for s in stocks:
            assert s.code is not None
            assert len(s.code) >= 6
            assert s.exchange in ("SH", "SZ", "BJ", None)


class TestStockListAkshare:
    """akshare 股票列表采集 → stocks 表 (仅补充)"""

    @pytest.mark.timeout(60)
    def test_sync_stock_list_akshare(self, dc_session):
        import akshare as ak
        from requests.exceptions import (
            ConnectionError, ProxyError, Timeout,
        )

        time.sleep(RATE_LIMIT_PAUSE)
        try:
            df = ak.stock_info_a_code_name()
        except (ConnectionError, ProxyError, Timeout) as exc:
            pytest.skip(f"akshare 网络不可达: {exc}")
        assert df is not None and len(df) > 100

        count = 0
        for _, row in df.head(20).iterrows():
            raw_code = str(row.get("code", ""))
            name = str(row.get("name", ""))
            if not raw_code or len(raw_code) < 6:
                continue

            if raw_code.startswith("6"):
                exchange = "SH"
            elif raw_code.startswith(("0", "3")):
                exchange = "SZ"
            else:
                exchange = "BJ"

            code = f"{raw_code}.{exchange}"
            existing = dc_session.query(Stock).filter_by(code=code).first()
            if existing:
                continue

            stock = Stock(code=code, name=name, exchange=exchange)
            dc_session.add(stock)
            count += 1

        dc_session.commit()

        total = dc_session.query(func.count(Stock.code)).scalar()
        assert total > 0
