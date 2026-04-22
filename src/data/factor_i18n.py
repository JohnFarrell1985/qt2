"""QMT 财务字段中文说明: 自迅投文档 ``dict.thinktrader`` 与列名一一对应.

- 全量表由 ``scripts/build_qmt_field_zh_json.py`` 从抓页/``doc/`` 生成 ``qmt_field_labels.zh.json``.
- 未出现的字段, 用「{表中文}·{原列名}（迅投列名）」回退.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Tuple

_TABEL_CN = {
    "Balance": "资产负债表",
    "Income": "利润表",
    "CashFlow": "现金流量表",
    "Pershareindex": "主要指标/每股",
    "Capital": "股本",
    "Holdernum": "股东户数",
    "Top10holder": "十大股东",
    "Top10flowholder": "十大流通股东",
}


@lru_cache(maxsize=1)
def _load_nested_zh() -> dict[str, Any]:
    p = Path(__file__).with_name("qmt_field_labels.zh.json")
    if not p.exists():
        return {}
    with p.open(encoding="utf-8") as f:
        return json.load(f)


def infer_factor_meta(qmt_field: str, data_source: str) -> Tuple[str, str, str]:
    """返回 (factor_kind, update_freq, storage_hint) — 与因子库/特征仓常见维度对齐.

    - factor_kind: 因子语义类 (fundamental / per_share / price_volume 等)
    - update_freq: 更新频率 (daily / quarterly / per_report)
    - storage_hint: 值是否默认写入 ``factor_values`` (factor_values / not_stored)
    """
    if data_source in ("calculated", "qlib") or not (qmt_field or "").strip():
        return "price_volume", "daily", "not_stored"
    t = (qmt_field or "").split(".", 1)[0]
    if t in ("Balance", "Income", "CashFlow"):
        return "fundamental", "quarterly", "factor_values"
    if t == "Pershareindex":
        return "per_share", "quarterly", "factor_values"
    if t == "Capital":
        return "capital", "quarterly", "factor_values"
    if t == "Holdernum":
        return "shareholder", "per_report", "factor_values"
    if t in ("Top10holder", "Top10flowholder"):
        return "top10", "per_report", "factor_values"
    return "unknown", "unknown", "factor_values"


def describe_qmt_field(table: str, field: str) -> str:
    """QMT 表+列 的中文说明(用于 ``factor_meta.description``)."""
    data = _load_nested_zh()
    tc = _TABEL_CN.get(table, table)
    zh = (data.get(table) or {}).get(field) if data else None
    if zh:
        return f"{tc}·{zh}"
    return f"{tc}·{field}（迅投列名）"


def describe_qlib_alpha158_column(name: str) -> str:
    """Qlib/Alpha158 价量类因子中文简述."""
    if name.startswith("KBAR_"):
        return f"K线形态类·{name}"
    if "ROC" in name:
        return f"历史变动率·{name}"
    if name.startswith("MA") or "MA" in name[:3]:
        return f"移动均线类·{name}"
    if "STD" in name:
        return f"波动率(标准差)类·{name}"
    if "VOLUME" in name or "VOL" in name:
        return f"成交量类·{name}"
    if "CORR" in name or "CORD" in name:
        return f"价量相关类·{name}"
    if "RSRS" in name or "BETA" in name:
        return f"价量/趋势类·{name}"
    if "QTL" in name or "MAX" in name or "MIN" in name or "RSV" in name or "RANK" in name:
        return f"极值/分位/区间类·{name}"
    return f"价量因子(类 Alpha158)·{name}"
