from sqlalchemy import text
from src.common.db import get_session

with get_session() as s:
    r = s.execute(text(
        "SELECT COUNT(*), COUNT(*) FILTER (WHERE dmin > '2000-01-04'), "
        "MIN(dmin), MAX(dmin) "
        "FROM (SELECT code, MIN(trade_date) dmin FROM stock_daily GROUP BY code) t"
    )).fetchone()
    print("codes_with_daily", r[0], "need_backfill", r[1], "global_min", r[2], "latest_earliest", r[3])
    no = s.execute(text(
        "SELECT COUNT(*) FROM stocks st "
        "WHERE NOT EXISTS (SELECT 1 FROM stock_daily d WHERE d.code=st.code)"
    )).scalar()
    print("stocks_no_daily", no)
