#!/usr/bin/env python3
"""
将 Vibe-Trading 仓库中的 AgentSkills 目录同步到本仓库 openclaw/workspace/skills/（与 OpenClaw workspace 根下的 /skills 一致）。

用法:
  cd C:\\Users\\dongg\\git\\qt
  python openclaw/scripts/sync_vibe_skills.py --source C:\\Users\\dongg\\git\\Vibe-Trading

  # 仅同步 SKILL.md（体积小，不含 tushare/references 等大目录）
  python openclaw/scripts/sync_vibe_skills.py --source ... --shallow

  # 同步「除排除列表外」的全部 Vibe skills（含大目录）
  python openclaw/scripts/sync_vibe_skills.py --source ... --all-vibe

环境变量:
  VIBE_TRADING_ROOT  可替代 --source

参考: OpenClaw / AgentSkills — workspace 根下 skills/<name>/SKILL.md
      https://docs.openclaw.ai/skills
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

# qt 项目优先使用的技能（A 股 / 因子 / 执行 / 报告；已排除纯加密/DeFi 等）
QT_DEFAULT_SKILLS: tuple[str, ...] = (
    "data-routing",
    "tushare",
    "akshare",
    "factor-research",
    "multi-factor",
    "fundamental-filter",
    "financial-statement",
    "valuation-model",
    "earnings-forecast",
    "earnings-revision",
    "quant-statistics",
    "backtest-diagnose",
    "regulatory-knowledge",
    "market-microstructure",
    "execution-model",
    "event-driven",
    "corporate-events",
    "convertible-bond",
    "etf-analysis",
    "sector-rotation",
    "hk-connect-flow",
    "fund-analysis",
    "risk-analysis",
    "performance-attribution",
    "correlation-analysis",
    "volatility",
    "trade-journal",
    "shadow-account",
    "behavioral-finance",
    "report-generate",
    "doc-reader",
    "web-reader",
    "strategy-generate",
    "vnpy-export",
    "pine-script",
    "technical-basic",
    "candlestick",
    "minute-analysis",
    "ichimoku",
    "chanlun",
    "smc",
    "elliott-wave",
    "harmonic",
    "seasonal",
    "pair-trading",
    "macro-analysis",
    "global-macro",
    "asset-allocation",
    "credit-analysis",
    "options-strategy",
    "options-advanced",
    "options-payoff",
    "cross-market-strategy",
    "adr-hshare",
    "yfinance",
    "us-etf-flow",
    "commodity-analysis",
    "sentiment-analysis",
    "ml-strategy",
)

# --all-vibe 时默认排除（与 qt A 股主战场弱相关）
QT_EXCLUDE_FROM_ALL: frozenset[str] = frozenset(
    {
        "crypto-derivatives",
        "perp-funding-basis",
        "stablecoin-flow",
        "defi-yield",
        "onchain-analysis",
        "liquidation-heatmap",
        "okx-market",
        "ccxt",
        "edgar-sec-filings",
        "token-unlock-treasury",
        "geopolitical-risk",
        "social-media-intelligence",
    }
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _vibe_skills_dir(source: Path) -> Path:
    p = source / "agent" / "src" / "skills"
    if not p.is_dir():
        raise FileNotFoundError(f"未找到 Vibe-Trading skills 目录: {p}")
    return p


def _copy_shallow(src: Path, dst: Path) -> None:
    dst.mkdir(parents=True, exist_ok=True)
    skill_md = src / "SKILL.md"
    if not skill_md.is_file():
        raise FileNotFoundError(f"缺少 SKILL.md: {src}")
    shutil.copy2(skill_md, dst / "SKILL.md")
    for name in ("examples.md", "example_signal_engine.py"):
        f = src / name
        if f.is_file():
            shutil.copy2(f, dst / name)
    ex = src / "examples"
    if ex.is_dir():
        shutil.copytree(ex, dst / "examples", dirs_exist_ok=True)


def _copy_full(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def main() -> int:
    parser = argparse.ArgumentParser(description="同步 Vibe-Trading skills → openclaw/workspace/skills")
    parser.add_argument(
        "--source",
        type=Path,
        default=None,
        help="Vibe-Trading 仓库根目录（含 agent/src/skills）",
    )
    parser.add_argument(
        "--shallow",
        action="store_true",
        help="仅复制 SKILL.md、examples.md、examples/ 等，跳过 references/ 等大目录",
    )
    parser.add_argument(
        "--all-vibe",
        action="store_true",
        help="同步源目录下全部技能子目录（仍排除 QT_EXCLUDE_FROM_ALL）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印将执行的操作，不写盘",
    )
    args = parser.parse_args()

    source_root = args.source
    if source_root is None:
        env = os.environ.get("VIBE_TRADING_ROOT", "").strip()
        if not env:
            print("请指定 --source 或设置环境变量 VIBE_TRADING_ROOT", file=sys.stderr)
            return 2
        source_root = Path(env)

    source_root = source_root.expanduser().resolve()
    skills_src = _vibe_skills_dir(source_root)
    out_root = _repo_root() / "openclaw" / "workspace" / "skills"

    if args.all_vibe:
        names = sorted(
            p.name
            for p in skills_src.iterdir()
            if p.is_dir() and (p / "SKILL.md").is_file() and p.name not in QT_EXCLUDE_FROM_ALL
        )
    else:
        names = list(QT_DEFAULT_SKILLS)

    missing = [n for n in names if not (skills_src / n / "SKILL.md").is_file()]
    if missing:
        print("以下技能在源仓库中不存在，已跳过: " + ", ".join(missing), file=sys.stderr)
        names = [n for n in names if n not in missing]

    if args.dry_run:
        print(f"源: {skills_src}")
        print(f"目标: {out_root}")
        print(f"将同步 {len(names)} 个技能: {', '.join(names)}")
        return 0

    out_root.mkdir(parents=True, exist_ok=True)
    for name in names:
        src = skills_src / name
        dst = out_root / name
        if args.shallow:
            _copy_shallow(src, dst)
        else:
            _copy_full(src, dst)
        print(f"ok  {name}")

    print(f"\n完成: {len(names)} 个技能 → {out_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
