"""启动突破 —— 当前唯一已实现的选股策略。

股票: ``ma_screener.screen_universe``; ETF: ``etf_screener.screen_etf_universe`` (跳过 ST/涨停等股票专有过滤)。
参数预设见 ``config/strategies/bull_launch.json``; UI 覆盖存浏览器 localStorage。
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict, List, Tuple

from src.common.config import MaFilterConfig, RankConfig, load_strategy
from src.selection.strategy import ScreenResult, SelectionStrategy, register_strategy

# UI 可编辑参数 (全中文标签); 未列出的项沿用 JSON 预设默认值
PARAM_SCHEMA: List[Dict[str, Any]] = [
    # —— 均线 / 金叉 ——
    {"key": "filter_periods", "section": "ma_filter", "label": "短期均线周期", "type": "list",
     "hint": "逗号分隔，如 5,10"},
    {"key": "require_rising", "section": "ma_filter", "label": "均线须上行", "type": "bool"},
    {"key": "require_ma5_ma10_cross", "section": "ma_filter", "label": "要求5/10金叉或即将金叉", "type": "bool"},
    {"key": "ma5_ma10_fresh_cross_days", "section": "ma_filter", "label": "金叉后最多N日", "type": "int"},
    {"key": "ma5_ma10_touch_pct", "section": "ma_filter", "label": "贴合交叉阈值%", "type": "number", "step": 0.1},
    {"key": "ma5_ma10_imminent_pct", "section": "ma_filter", "label": "即将金叉最大差距%", "type": "number", "step": 0.1},
    {"key": "ma5_ma10_max_days_to_cross", "section": "ma_filter", "label": "预测金叉最长N日", "type": "number", "step": 0.5},
    {"key": "ma5_ma10_require_next_day", "section": "ma_filter", "label": "须预测次日金叉", "type": "bool"},
    {"key": "require_ma5_ma10_above_long", "section": "ma_filter", "label": "5/10须在长均线上方", "type": "bool"},
    {"key": "ma5_ma10_above_groups", "section": "ma_filter", "label": "长均线条件组", "type": "ma_groups",
     "hint": "组内逗号、组间竖线。例: 20,30|40,50 表示 (均在20/30上) 或 (均在40/50上)",
     "default_when_enabled": "20,30|40,50"},
    # —— 价格 / 缩量 ——
    {"key": "anchor_ma_period", "section": "ma_filter", "label": "锚点均线周期", "type": "int"},
    {"key": "ma5_proximity_pct", "section": "ma_filter", "label": "贴近锚点均线上限%", "type": "number", "step": 0.5},
    {"key": "require_close_above_ma5", "section": "ma_filter", "label": "收盘须在锚点均线上方", "type": "bool"},
    {"key": "require_volume_pullback", "section": "ma_filter", "label": "要求缩量回调", "type": "bool"},
    {"key": "volume_shrink_ratio", "section": "ma_filter", "label": "缩量比例(<1更严)", "type": "number", "step": 0.05},
    # —— 涨幅 / 前期大涨 ——
    {"key": "prior_surge_lookback_days", "section": "ma_filter", "label": "前期大涨回溯(交易日)", "type": "int"},
    {"key": "prior_surge_min_pct", "section": "ma_filter", "label": "单日大涨阈值%", "type": "number", "step": 0.5},
    {"key": "max_gain_lookback_days", "section": "ma_filter", "label": "近N日涨幅统计窗口", "type": "int"},
    {"key": "max_gain_total_pct", "section": "ma_filter", "label": "近N日累计涨幅上限%", "type": "number", "step": 1},
    {"key": "max_gain_1m_lookback_days", "section": "ma_filter", "label": "近一月统计窗口(交易日)", "type": "int"},
    {"key": "max_gain_1m_pct", "section": "ma_filter", "label": "近一月涨幅上限%", "type": "number", "step": 1},
    # —— 输出 / 分层 ——
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
    if schema_type == "list":
        if isinstance(val, list):
            return [int(x) for x in val]
        return [int(x.strip()) for x in str(val).split(",") if x.strip()]
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


def _default_ma5_ma10_above_groups(cfg: MaFilterConfig) -> List[List[int]]:
    """用户开启长均线过滤但未填条件组时的默认: (均在20/30上) 或 (均在40/50上)。"""
    _ = cfg  # 预留: 未来可按 compute_periods 推导
    return [[20, 30], [40, 50]]


def _resolve_ma5_ma10_above_groups(cfg: MaFilterConfig) -> None:
    if cfg.require_ma5_ma10_above_long and not cfg.ma5_ma10_above_groups:
        cfg.ma5_ma10_above_groups = _default_ma5_ma10_above_groups(cfg)


def _ensure_compute_periods(cfg: MaFilterConfig) -> None:
    extra = set(cfg.filter_periods) | {5, 10}
    if cfg.require_ma5_ma10_above_long and cfg.ma5_ma10_above_groups:
        for group in cfg.ma5_ma10_above_groups:
            extra.update(group)
    missing = [p for p in extra if p not in cfg.compute_periods]
    if missing:
        cfg.compute_periods = sorted(set(cfg.compute_periods) | set(extra))


def build_configs(
    overrides: Dict[str, Any] | None = None,
) -> Tuple[MaFilterConfig, RankConfig, Dict[str, str]]:
    """由 bull_launch 预设 JSON + UI 覆盖构造本地配置 (不修改全局 settings)。"""
    preset = load_strategy("bull_launch")
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

    _resolve_ma5_ma10_above_groups(cfg)
    _ensure_compute_periods(cfg)

    meta = {
        "id": preset.get("id", "bull_launch"),
        "label": preset.get("label", "启动突破"),
        "description": preset.get("description", ""),
    }
    return cfg, rank_cfg, meta


@register_strategy
class BullLaunchStrategy(SelectionStrategy):
    """启动突破选股策略。"""

    @classmethod
    def strategy_id(cls) -> str:
        return "bull_launch"

    @classmethod
    def screen(
        cls,
        kind: str,
        trade_date: date,
        params: Dict[str, Any] | None = None,
    ) -> ScreenResult:
        if kind not in _SUPPORTS:
            raise ValueError(f"启动突破不支持 kind={kind}")
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
        preset = load_strategy("bull_launch")
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
            "id": preset.get("id", "bull_launch"),
            "label": preset.get("label", "启动突破"),
            "description": preset.get("description", ""),
            "supports": sorted(_SUPPORTS),
            "params": [
                {**item, "default": defaults.get(item["key"])}
                for item in PARAM_SCHEMA
            ],
        }
