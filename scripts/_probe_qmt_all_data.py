# -*- coding: utf-8 -*-
"""Probe QMT available data APIs and sample payloads."""
from __future__ import annotations

import json
from datetime import datetime

from src.data.qmt_client import QMTClient


def _sample(obj, n=2):
    if isinstance(obj, dict):
        items = list(obj.items())[:n]
        return {k: (type(v).__name__, str(v)[:120]) for k, v in items}
    if isinstance(obj, list):
        return [obj[i] if i < len(obj) else None for i in range(min(n, len(obj)))]
    return str(obj)[:200]


def main() -> int:
    c = QMTClient()
    out: dict = {}

    try:
        out["period_list"] = c.get_period_list()
    except Exception as e:
        out["period_list"] = f"ERR: {e}"
    out["sector_count"] = len(c.get_sector_list())

    for name, fn in [
        ("holidays", lambda: c.get_holidays()[:5]),
        ("ipo_info", lambda: c.get_ipo_info("20240101", datetime.now().strftime("%Y%m%d"))),
    ]:
        try:
            out[name] = _sample(fn())
        except Exception as e:
            out[name] = f"ERR: {e}"

    try:
        c.download_etf_info()
        out["etf_info"] = _sample(c.get_etf_info())
    except Exception as e:
        out["etf_info"] = f"ERR: {e}"

    try:
        c.download_cb_data()
        codes = c.get_stock_list_in_sector("沪深转债") or c.get_stock_list_in_sector("可转债")
        out["cb_count"] = len(codes)
        if codes:
            out["cb_info_sample"] = _sample(c.get_cb_info(codes[0]))
    except Exception as e:
        out["cb"] = f"ERR: {e}"

    codes = c.get_stock_list_in_sector("沪深A股")[:1]
    if codes:
        try:
            df = c.get_divid_factors(codes[0], "20000101", datetime.now().strftime("%Y%m%d"))
            if df is not None and hasattr(df, "head"):
                out["divid_factors_cols"] = list(df.columns)
                out["divid_factors_rows"] = len(df)
                out["divid_factors_head"] = df.head(2).to_dict()
            else:
                out["divid_factors"] = str(df)[:200]
        except Exception as e:
            out["divid_factors"] = f"ERR: {e}"

    print(json.dumps(out, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
