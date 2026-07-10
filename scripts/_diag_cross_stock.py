"""Diagnose MA5/MA10 direction for a stock."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from sqlalchemy import text

from src.common.config import apply_strategy, settings
from src.common.db import get_session
from src.selection.ma_screener import compute_mas, detect_ma5_ma10_cross, passes_ma_filter


def main(code: str = "688209", td: date = date(2026, 7, 10)) -> None:
    apply_strategy("bull_launch")
    cfg = settings.selection.ma_filter

    sql = text("""
        SELECT trade_date, close FROM stock_daily
        WHERE code=:c AND trade_date<=:td ORDER BY trade_date DESC LIMIT 80
    """)
    with get_session() as session:
        rows = session.execute(sql, {"c": code, "td": td}).fetchall()
    df = pd.DataFrame(rows, columns=["trade_date", "close"]).sort_values("trade_date")
    df["close"] = pd.to_numeric(df["close"])
    mas = compute_mas(df["close"], [5, 10])
    df["ma5"] = mas[5].values
    df["ma10"] = mas[10].values
    df["gap_pct"] = (df["ma5"] - df["ma10"]) / df["ma10"] * 100

    print(f"=== {code} @ {td} ===")
    print(df.tail(12).to_string(index=False))
    print()
    print("detect:", detect_ma5_ma10_cross(mas, cfg))
    print("passes_ma_filter:", passes_ma_filter(mas, cfg))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "688209")
