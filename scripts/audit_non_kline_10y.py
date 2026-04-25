"""统计「非 K 线」业务表库内规模, 并对日频类表对照近 10 年窗口与 trading_date 估算缺口.

K 线类(本脚本仅作对照展示, 不计入「需补非 K」): stock_daily, etf_daily, market_index, cb_daily, stock_minute.

用法:
  uv run python scripts/audit_non_kline_10y.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta

from sqlalchemy import text

from src.common.db import get_engine


def _win() -> tuple[date, date]:
    end = date.today()
    start = end - timedelta(days=3650)
    return start, end


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except (OSError, ValueError):
            pass
    start, end = _win()
    eng = get_engine()
    print(f"近 10 年窗口(自然日地板): {start} ~ {end}\n")

    with eng.connect() as c:
        td_n = c.execute(
            text(
                "SELECT COUNT(*) FROM trading_date "
                "WHERE trade_date >= :a AND trade_date <= :b",
            ),
            {"a": start, "b": end},
        ).scalar()
        print(f"trading_date 在窗内行数: {td_n} (沪/深各一行/日, 实际约 {td_n // 2 if td_n else 0} 个交易日/所 或合并口径见库)\n")

        blocks: list[tuple[str, str]] = [
            ("基础/元数据", "stocks"),
            ("基础/元数据", "etf_info"),
            ("基础/元数据", "convertible_bond"),
            ("财务", "stock_financial_report"),
            ("财务", "stock_financial_indicator"),
            ("因子", "factor_meta"),
            ("因子", "factor_values"),
            ("关系/权重", "sector_stock"),
            ("关系/权重", "index_weight"),
            ("另类日频", "hsgt_market_daily"),
            ("另类日频", "stock_moneyflow_daily"),
            ("另类日频", "stock_lhb_daily"),
            ("另类日频", "institution_survey"),
            ("板块行情(类K)", "sector_data"),
            ("全球快照", "global_market_snapshot"),
            ("K线(对照)", "stock_daily"),
            ("K线(对照)", "etf_daily"),
            ("K线(对照)", "market_index"),
            ("K线(对照)", "cb_daily"),
        ]

        for cat, tbl in blocks:
            try:
                r = c.execute(
                    text(
                        f"SELECT COUNT(*) FROM {tbl}",  # noqa: S608
                    ),
                ).scalar()
            except Exception as e:
                print(f"[{cat}] {tbl}: 查询失败 {e}")
                continue
            extra = ""
            if tbl in (
                "stock_financial_report",
                "stock_financial_indicator",
                "hsgt_market_daily",
                "stock_moneyflow_daily",
                "stock_lhb_daily",
                "institution_survey",
                "factor_values",
                "sector_data",
                "global_market_snapshot",
            ):
                col = "report_date" if "financial" in tbl else (
                    "survey_date" if tbl == "institution_survey" else "trade_date"
                )
                mm = c.execute(
                    text(
                        f"SELECT MIN({col})::text, MAX({col})::text, "
                        f"COUNT(DISTINCT {col}) FROM {tbl}",  # noqa: S608
                    ),
                ).fetchone()
                if mm and mm[0]:
                    nwin = c.execute(
                        text(
                            f"SELECT COUNT(*) FROM {tbl} WHERE {col} >= :a AND {col} <= :b",  # noqa: S608
                        ),
                        {"a": start, "b": end},
                    ).scalar()
                    extra = f" | 窗内 {nwin} 行 | 日期 {mm[0][:10]}~{mm[1][:10]} | 不重复日/报告日 {mm[2]}"
            elif tbl in ("stocks", "etf_info", "convertible_bond"):
                extra = f" | 主键(标的) 数: {r}"
            elif tbl == "factor_meta":
                extra = f" | 定义条数(非时序值)"
            elif tbl == "sector_stock":
                extra = ""
            elif tbl == "index_weight":
                extra = ""
            if tbl in ("stock_daily", "etf_daily", "market_index", "cb_daily") and r:
                col = "index_code" if tbl == "market_index" else "code"
                mm = c.execute(
                    text(
                        f"SELECT MIN(trade_date)::text, MAX(trade_date)::text, "
                        f"COUNT(DISTINCT trade_date) FROM {tbl} WHERE trade_date >= :a AND trade_date <= :b",  # noqa: S608
                    ),
                    {"a": start, "b": end},
                ).fetchone()
                if mm and mm[0]:
                    extra = f" | 窗内 dist 日 {mm[2]} (对照)"
            print(f"[{cat}] {tbl}: 总行 {r}{extra}")

    print(
        "\n说明: 个股/全市场日频的「应有多少行」依赖标的数*交易日, 上表以窗内行数+日期范围为主;"
        "\n      moneyflow/lhb 需按交易日循环灌库, 见 python -m src.data.alt_data_sync moneyflow|lhb --start-date ...",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
