"""BulkWriter E2E — 使用真实 PostgreSQL 验证 COPY / UPSERT 双模式

测试范围:
  - COPY 协议空表批量写入
  - UPSERT (INSERT ON CONFLICT) 增量更新
  - auto 模式自动切换
  - 表名白名单校验
"""
import pytest
from datetime import date
from unittest.mock import patch

from sqlalchemy import text

from src.data.bulk_writer import BulkWriter
from src.data.models import Stock, StockDaily


pytestmark = pytest.mark.timeout(30)


class TestBulkWriterCopy:
    """COPY 协议空表写入"""

    def test_copy_inserts_stocks(self, db_e2e_engine, db_e2e_session, make_e2e_get_session):
        records = [
            {"code": "TEST01", "name": "测试股票A", "industry": "测试", "exchange": "SZ"},
            {"code": "TEST02", "name": "测试股票B", "industry": "测试", "exchange": "SH"},
            {"code": "TEST03", "name": "测试股票C", "industry": "测试", "exchange": "SZ"},
        ]
        writer = BulkWriter(batch_size=100)
        with patch("src.data.bulk_writer.get_session", side_effect=make_e2e_get_session), \
             patch("src.data.bulk_writer.get_engine", return_value=db_e2e_engine):
            count = writer.write(Stock, records, mode="copy")

        assert count == 3
        result = db_e2e_session.execute(text("SELECT count(*) FROM stocks")).scalar()
        assert result >= 3


class TestBulkWriterUpsert:
    """UPSERT 模式增量更新"""

    def test_upsert_inserts_and_updates(self, db_e2e_engine, db_e2e_session, make_e2e_get_session):
        db_e2e_session.execute(text(
            "INSERT INTO stocks (code, name, industry, exchange) "
            "VALUES ('UPSERT01', '原始名称', '测试', 'SZ')"
        ))
        db_e2e_session.commit()

        records = [
            {"code": "UPSERT01", "name": "更新名称", "industry": "金融", "exchange": "SZ"},
            {"code": "UPSERT02", "name": "新增股票", "industry": "科技", "exchange": "SH"},
        ]
        writer = BulkWriter(batch_size=100)
        with patch("src.data.bulk_writer.get_session", side_effect=make_e2e_get_session), \
             patch("src.data.bulk_writer.get_engine", return_value=db_e2e_engine):
            count = writer.write(
                Stock, records, mode="upsert",
                conflict_columns=["code"],
                update_columns=["name", "industry"],
            )

        assert count == 2
        row = db_e2e_session.execute(
            text("SELECT name, industry FROM stocks WHERE code = 'UPSERT01'")
        ).fetchone()
        assert row[0] == "更新名称"
        assert row[1] == "金融"


class TestBulkWriterAutoMode:
    """auto 模式: 空表→COPY, 非空表→UPSERT"""

    def test_auto_empty_table_uses_copy(self, db_e2e_engine, db_e2e_session, make_e2e_get_session):
        count_before = db_e2e_session.execute(
            text("SELECT count(*) FROM stock_daily")
        ).scalar()

        if count_before > 0:
            pytest.skip("stock_daily 非空, 无法测试 auto→copy 路径")

        records = [{
            "code": "TEST99", "trade_date": date(2019, 1, 2),
            "open": 10.0, "high": 10.5, "low": 9.8, "close": 10.2,
            "volume": 100000, "amount": 1020000.0,
        }]
        writer = BulkWriter()
        with patch("src.data.bulk_writer.get_session", side_effect=make_e2e_get_session), \
             patch("src.data.bulk_writer.get_engine", return_value=db_e2e_engine):
            count = writer.write(StockDaily, records, mode="auto")

        assert count == 1


class TestTableWhitelist:
    """表名白名单安全校验"""

    def test_whitelist_rejects_unknown_table(self):
        writer = BulkWriter()
        with pytest.raises(ValueError, match="not in whitelist"):
            writer._is_table_empty("malicious_table; DROP TABLE stocks;--")

    def test_whitelist_allows_known_tables(self, db_e2e_engine, make_e2e_get_session):
        writer = BulkWriter()
        with patch("src.data.bulk_writer.get_session", side_effect=make_e2e_get_session):
            result = writer._is_table_empty("stocks")
        assert isinstance(result, bool)

    def test_whitelist_covers_all_orm_models(self):
        from src.data import models as data_models
        from src.datacollect import models as dc_models

        writer = BulkWriter()
        for module in (data_models, dc_models):
            for attr_name in dir(module):
                cls = getattr(module, attr_name)
                if hasattr(cls, "__tablename__") and not attr_name.startswith("_"):
                    table = cls.__tablename__
                    assert table in writer._ALLOWED_TABLES, \
                        f"ORM model {attr_name} table '{table}' not in whitelist"


class TestWriteFlush:
    """write_flush 批量写入"""

    def test_flush_multiple_models(self, db_e2e_engine, db_e2e_session, make_e2e_get_session):
        batch = [
            (Stock, [
                {"code": "FLUSH01", "name": "Flush测试A", "industry": "测试", "exchange": "SZ"},
            ]),
            (Stock, [
                {"code": "FLUSH02", "name": "Flush测试B", "industry": "测试", "exchange": "SH"},
            ]),
        ]
        writer = BulkWriter()
        with patch("src.data.bulk_writer.get_session", side_effect=make_e2e_get_session), \
             patch("src.data.bulk_writer.get_engine", return_value=db_e2e_engine):
            writer.write_flush(batch)

        count = db_e2e_session.execute(
            text("SELECT count(*) FROM stocks WHERE code LIKE 'FLUSH%'")
        ).scalar()
        assert count >= 2
