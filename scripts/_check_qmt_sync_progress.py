"""Check QMT sync progress in DB."""
from sqlalchemy import text
from src.common.db import get_session

queries = {
    "sector_stock": "SELECT COUNT(*) FROM sector_stock",
    "sector_stock_recent": (
        "SELECT COUNT(*) FROM sector_stock WHERE updated_at >= NOW() - INTERVAL '2 hours'"
    ),
    "stock_divid_factor": "SELECT COUNT(*) FROM stock_divid_factor",
    "stock_divid_recent": (
        "SELECT COUNT(*) FROM stock_divid_factor WHERE updated_at >= NOW() - INTERVAL '2 hours'"
    ),
    "index_weight": "SELECT COUNT(*) FROM index_weight",
    "convertible_bond": "SELECT COUNT(*) FROM convertible_bond",
    "cb_daily": "SELECT COUNT(*) FROM cb_daily",
    "factor_values": "SELECT COUNT(*) FROM factor_values",
    "stock_financial_report": "SELECT COUNT(*) FROM stock_financial_report",
}

with get_session() as s:
    for name, sql in queries.items():
        try:
            n = s.execute(text(sql)).scalar()
            print(f"{name}: {n}")
        except Exception as e:
            print(f"{name}: ERR {e}")
