"""熊市五日偏离 —— MA5 在长均线组下方 + 收盘价低于 MA5 指定偏离度.

股票: ``ma_screener.screen_universe``; ETF: ``etf_screener.screen_etf_universe``.
参数预设见 ``config/strategies/bear_five_dev.json``; UI 覆盖存浏览器 localStorage。
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Tuple

from src.common.config import MaFilterConfig, RankConfig, load_strategy
from src.selection.strategy import ScreenResult, SelectionStrategy, register_strategy

PARAM_SCHEMA: List[Dict[str, Any]] = [
    {"key": "ma5_below_groups", "section": "ma_filter", "label": "长均线条件组", "type": "ma_groups",
     "hint": "组内逗号、组间竖线。例: 30 表示 MA5 在 MA30 下; 20,30|40,50 表示 (均在20/30下) 或 (均在40/50下)",
     "default_when_enabled": "30"},
    {"key": "ma5_below_pct", "section": "ma_filter", "label": "低于5日线至少偏离%", "type": "number", "step": 0.5},
    {"key": "anchor_ma_period", "section": "ma_filter", "label": "锚点均线周期", "type": "int"},
    {"key": "min_avg_turnover_20d", "section": "ma_filter", "label": "20日均换手率下限%", "type": "number", "step": 0.1},
    {"key": "min_avg_amount_20d", "section": "ma_filter", "label": "20日均成交额下限", "type": "number", "step": 1000000},
    {"key": "max_candidates", "section": "ma_filter", "label": "候选上限", "type": "int"},
    {"key": "export_top_n", "section": "rank", "label": "导出前N名", "type": "int"},
    {"key": "tier_a_min", "section": "rank", "label": "A级最低分", "type": "int"},
    {"key": "tier_b_min", "section": "rank", "label": "B级最低分", "type": "int"},
]

_SUPPORTS = frozenset({"stock", "etf"})


def _coerce(schema_type: str, val: Any):
    if val is None or val == "":
        return None
    if schema_type == "bool":
        if isinstance(val, bool):
            return val
        s = str(val).strip().lower()
        if s in ("1", "true", "yes", "是", "y", "on"):
            return True
        if s in ("0", "false", "no", "否", "n", "off"):
            return False
        return None
    if schema_type == "ma_groups":
        s = str(val).strip()
        if not s:
            return []
        groups: List[List[int]] = []
        for part in s.split("|"):
            periods = [int(x.strip()) for x in part.split(",") if x.strip()]
            if periods:
                groups.append(periods)
        return groups
    if schema_type == "int":
        return int(float(val))
    if schema_type == "number":
        return float(val)
    return val


def _apply(obj, section: Dict[str, Any]) -> None:
    for key, val in section.items():
        if hasattr(obj, key):
            setattr(obj, key, val)


def _format_ma_groups(groups: Any) -> str:
    if not groups:
        return ""
    if isinstance(groups, str):
        return groups
    if isinstance(groups, list) and groups and isinstance(groups[0], list):
        return "|".join(",".join(str(p) for p in g) for g in groups)
    return str(groups)


def _default_ma5_below_groups(cfg: MaFilterConfig) -> List[List[int]]:
    _ = cfg
    return [[30]]


def _resolve_ma5_below_groups(cfg: MaFilterConfig) -> None:
    if cfg.require_ma5_below_long and not cfg.ma5_below_groups:
        cfg.ma5_below_groups = _default_ma5_below_groups(cfg)


def _ensure_compute_periods(cfg: MaFilterConfig) -> None:
    extra = {5, cfg.anchor_ma_period}
    if cfg.ma5_below_groups:
        for group in cfg.ma5_below_groups:
            extra.update(group)
    missing = [p for p in extra if p not in cfg.compute_periods]
    if missing:
        cfg.compute_periods = sorted(set(cfg.compute_periods) | set(extra))


def build_configs(
    overrides: Dict[str, Any] | None = None,
) -> Tuple[MaFilterConfig, RankConfig, Dict[str, str]]:
    preset = load_strategy("bear_five_dev")
    cfg = MaFilterConfig()
    rank_cfg = RankConfig()
    _apply(cfg, preset.get("ma_filter", {}))
    _apply(rank_cfg, preset.get("rank", {}))

    overrides = overrides or {}
    for item in PARAM_SCHEMA:
        key = item["key"]
        if key not in overrides:
            continue
        coerced = _coerce(item["type"], overrides[key])
        if coerced is None:
            continue
        target = cfg if item["section"] == "ma_filter" else rank_cfg
        if hasattr(target, key):
            setattr(target, key, coerced)

    _resolve_ma5_below_groups(cfg)
    _ensure_compute_periods(cfg)

    meta = {
        "id": preset.get("id", "bear_five_dev"),
        "label": preset.get("label", "熊市五日偏离"),
        "description": preset.get("description", ""),
    }
    return cfg, rank_cfg, meta


@register_strategy
class BearFiveDevStrategy(SelectionStrategy):
    """熊市五日偏离选股策略。"""

    @classmethod
    def strategy_id(cls) -> str:
        return "bear_five_dev"

    @classmethod
    def screen(
        cls,
        kind: str,
        trade_date: date,
        params: Dict[str, Any] | None = None,
    ) -> ScreenResult:
        if kind not in _SUPPORTS:
            raise ValueError(f"熊市五日偏离不支持 kind={kind}")
        cfg, rank_cfg, _meta = build_configs(params)
        if kind == "etf":
            from src.selection.etf_screener import screen_etf_universe

            candidates, snaps = screen_etf_universe(trade_date, cfg, rank_cfg)
        else:
            from src.selection.ma_screener import screen_universe

            candidates, snaps = screen_universe(trade_date, cfg, rank_cfg)

        top_n = rank_cfg.export_top_n if rank_cfg.enabled and rank_cfg.export_top_n else None
        return ScreenResult(candidates=candidates, snapshots=snaps, export_top_n=top_n)

    @classmethod
    def catalog_entry(cls) -> Dict[str, Any]:
        preset = load_strategy("bear_five_dev")
        ma = preset.get("ma_filter", {})
        rank = preset.get("rank", {})
        defaults: Dict[str, Any] = {}
        for item in PARAM_SCHEMA:
            src = ma if item["section"] == "ma_filter" else rank
            if item["key"] in src:
                val = src[item["key"]]
                if item["type"] == "ma_groups":
                    defaults[item["key"]] = _format_ma_groups(val)
                elif item["type"] == "bool":
                    defaults[item["key"]] = val
                else:
                    defaults[item["key"]] = val
        return {
            "id": preset.get("id", "bear_five_dev"),
            "label": preset.get("label", "熊市五日偏离"),
            "description": preset.get("description", ""),
            "supports": sorted(_SUPPORTS),
            "params": [
                {**item, "default": defaults.get(item["key"])}
                for item in PARAM_SCHEMA
            ],
        }
