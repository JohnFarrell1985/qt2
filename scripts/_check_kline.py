"""Diagnose K-line data coverage issues."""
from src.common.db import get_session
from sqlalchemy import text

with get_session() as s:
    print("=" * 60)
    print("STOCK DAILY ANALYSIS")
    print("=" * 60)

    total_stocks = s.execute(text("SELECT COUNT(*) FROM stocks")).scalar()
    stocks_with_any_daily = s.execute(text(
        "SELECT COUNT(DISTINCT code) FROM stock_daily"
    )).scalar()
    stocks_recent = s.execute(text(
        "SELECT COUNT(DISTINCT code) FROM stock_daily "
        "WHERE trade_date >= '2026-03-18'"
    )).scalar()
    stocks_before = s.execute(text(
        "SELECT COUNT(DISTINCT code) FROM stock_daily "
        "WHERE trade_date <= '2026-03-17'"
    )).scalar()

    print(f"Total stocks in DB:                     {total_stocks:,}")
    print(f"Stocks with ANY daily data:              {stocks_with_any_daily:,}")
    print(f"Stocks with data up to 2026-03-17:       {stocks_before:,}")
    print(f"Stocks with NEW data (after 2026-03-17): {stocks_recent:,}")

    # sample: stocks that had old data but got no new data
    gap = s.execute(text("""
        SELECT s.code, MAX(sd.trade_date) as last_date
        FROM stocks s
        JOIN stock_daily sd ON s.code = sd.code
        WHERE sd.trade_date <= '2026-03-17'
        AND s.code NOT IN (
            SELECT DISTINCT code FROM stock_daily WHERE trade_date > '2026-03-17'
        )
        GROUP BY s.code
        ORDER BY last_date DESC
        LIMIT 10
    """)).fetchall()
    print(f"\nSample: stocks with old data but NO new data:")
    for row in gap:
        print(f"  {row[0]}: last_date={row[1]}")

    # stocks with NO daily data at all
    no_data = s.execute(text("""
        SELECT s.code, s.name FROM stocks s
        LEFT JOIN (SELECT DISTINCT code FROM stock_daily) sd ON s.code = sd.code
        WHERE sd.code IS NULL
        LIMIT 10
    """)).fetchall()
    print(f"\nSample: stocks with ZERO daily data:")
    for row in no_data:
        print(f"  {row[0]}: {row[1]}")

    print()
    print("=" * 60)
    print("ETF DAILY ANALYSIS")
    print("=" * 60)

    total_etfs = s.execute(text("SELECT COUNT(*) FROM etf_info")).scalar()
    etfs_with_data = s.execute(text("SELECT COUNT(DISTINCT code) FROM etf_daily")).scalar()
    print(f"Total ETFs in DB:           {total_etfs:,}")
    print(f"ETFs with daily data:       {etfs_with_data:,}")
    print(f"ETFs WITHOUT daily data:    {total_etfs - etfs_with_data:,}")

    # sample ETFs that DID get data
    got_data = s.execute(text("""
        SELECT e.code, e.name, COUNT(*) as rows
        FROM etf_info e JOIN etf_daily ed ON e.code = ed.code
        GROUP BY e.code, e.name ORDER BY rows DESC LIMIT 5
    """)).fetchall()
    print(f"\nTop ETFs with data:")
    for row in got_data:
        print(f"  {row[0]} {row[1]}: {row[2]} days")

    # sample ETFs that did NOT get data
    no_etf_data = s.execute(text("""
        SELECT e.code, e.name FROM etf_info e
        LEFT JOIN (SELECT DISTINCT code FROM etf_daily) ed ON e.code = ed.code
        WHERE ed.code IS NULL
        LIMIT 10
    """)).fetchall()
    print(f"\nSample ETFs WITHOUT data:")
    for row in no_etf_data:
        print(f"  {row[0]} {row[1]}")
