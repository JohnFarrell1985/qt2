"""选股 workflow 编排与输出."""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

import src.selection.strategies  # noqa: F401 — 注册策略
from src.common.config import PROJECT_ROOT, get_strategy_meta, settings
from src.common.logger import get_logger
from src.selection.strategy import get_strategy

logger = get_logger(__name__)


def candidates_filename(trade_date: date) -> str:
    sid = get_strategy_meta().get("id", settings.selection.active_strategy)
    return f"candidates_{sid}_{trade_date.strftime('%Y%m%d')}.json"


def output_path(trade_date: date, filename: str | None = None) -> Path:
    out_dir = Path(settings.selection.output_dir)
    if not out_dir.is_absolute():
        out_dir = PROJECT_ROOT / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / (filename or candidates_filename(trade_date))


def build_screen_report(
    trade_date: date,
    candidates: list[str],
    ma_snapshots: dict[str, dict],
) -> dict[str, Any]:
    meta = get_strategy_meta()
    export_n = settings.selection.rank.export_top_n
    shortlist = candidates[:export_n] if export_n > 0 else list(candidates)
    return {
        "trade_date": trade_date.isoformat(),
        "strategy": meta.get("id", settings.selection.active_strategy),
        "strategy_label": meta.get("label", ""),
        "ma_candidates": len(candidates),
        "export_top_n": export_n,
        "export_shortlist": shortlist,
        "candidates": candidates,
        "ma_snapshots": ma_snapshots,
    }


def save_report(report: dict[str, Any], path: Path, csv_also: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("清单已保存: %s", path)

    if csv_also:
        csv_path = path.with_suffix(".csv")
        snaps = report.get("ma_snapshots") or {}
        export_codes = report.get("export_shortlist") or report.get("candidates") or []
        with csv_path.open("w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "code",
                    "composite_score",
                    "tier",
                    "close",
                    "ma5_dist_pct",
                    "avg_turnover_20d",
                ],
            )
            writer.writeheader()
            for code in export_codes:
                snap = snaps.get(code, {})
                writer.writerow(
                    {
                        "code": code,
                        "composite_score": snap.get("composite_score", ""),
                        "tier": snap.get("tier", ""),
                        "close": snap.get("close", ""),
                        "ma5_dist_pct": snap.get("ma5_dist_pct", ""),
                        "avg_turnover_20d": snap.get("avg_turnover_20d", ""),
                    }
                )
        logger.info("CSV 已保存: %s", csv_path)


def run_ma_screen(trade_date: date, strategy_id: str | None = None) -> tuple[list[str], dict[str, dict]]:
    sid = strategy_id or settings.selection.active_strategy
    result = get_strategy(sid).screen("stock", trade_date, None)
    candidates = result.candidates
    if result.export_top_n:
        candidates = candidates[: result.export_top_n]
    return candidates, result.snapshots


def run_screen(
    trade_date: date,
    output: Path | None = None,
    csv_also: bool = False,
) -> dict[str, Any]:
    """MA 初筛并写入 JSON (及可选 CSV)."""
    candidates, ma_snapshots = run_ma_screen(trade_date)
    report = build_screen_report(trade_date, candidates, ma_snapshots)
    out = output or output_path(trade_date)
    save_report(report, out, csv_also)
    return report


def load_candidates_file(path: Path) -> tuple[list[str], dict[str, dict], date | None]:
    data = json.loads(path.read_text(encoding="utf-8"))
    td = data.get("trade_date")
    trade_date = date.fromisoformat(td) if td else None
    codes = list(data.get("candidates") or [])
    if not codes and data.get("final_picks"):
        codes = [p["code"] for p in data["final_picks"]]
    snaps = data.get("ma_snapshots") or {}
    if not snaps and data.get("final_picks"):
        snaps = {p["code"]: p.get("ma_snapshot", {}) for p in data["final_picks"]}
    return codes, snaps, trade_date
