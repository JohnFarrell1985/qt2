from datetime import date

from sqlalchemy import text

from src.common.db import get_session

FLOOR = date(2000, 1, 4)

with get_session() as s:
    rows = s.execute(text(
        "SELECT st.code, st.list_date, d.dmin, d.cnt "
        "FROM stocks st "
        "LEFT JOIN ("
        "  SELECT code, MIN(trade_date) AS dmin, COUNT(*) AS cnt "
        "  FROM stock_daily GROUP BY code"
        ") d ON st.code = d.code"
    )).fetchall()

no_daily = []
late_start = []
for code, list_date, dmin, cnt in rows:
    if dmin is None:
        no_daily.append(code)
        continue
    eff = FLOOR
    if list_date and list_date > eff:
        eff = list_date
    if dmin > eff:
        late_start.append((code, str(eff), str(dmin), cnt))

print("no_daily", len(no_daily), no_daily[:10])
print("late_start", len(late_start))
if late_start:
    print("sample", late_start[:5])
