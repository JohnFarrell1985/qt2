"""
选股接口 — 回测用 picker 抽象层

- MockPicker: 预设日期 → 股票列表
- RandomPicker: 随机基线对照
- CachedPicker: 从 selection 输出的 candidates JSON 读取
"""
import json
import os
import random
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional


@dataclass
class PickResult:
    """选股结果"""
    trade_date: date
    codes: List[str]
    confidence: Dict[str, float] = field(default_factory=dict)
    reason: Dict[str, str] = field(default_factory=dict)


class StockPicker(ABC):
    """选股抽象接口"""

    @abstractmethod
    def pick(self, trade_date: date) -> PickResult:
        ...


class MockPicker(StockPicker):
    """预设选股结果 — 用于回测验证策略框架"""

    def __init__(
        self,
        schedule: Dict[date, List[str]] | None = None,
        schedule_file: str | None = None,
    ):
        self.schedule: Dict[date, List[str]] = {}
        if schedule:
            self.schedule = schedule
        elif schedule_file:
            self._load_from_file(schedule_file)

    def _load_from_file(self, path: str) -> None:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        for date_str, codes in raw.items():
            self.schedule[date.fromisoformat(date_str)] = codes

    def pick(self, trade_date: date) -> PickResult:
        codes = self.schedule.get(trade_date, [])
        return PickResult(
            trade_date=trade_date,
            codes=codes,
            confidence={c: 80.0 for c in codes},
            reason={c: "MockPicker 预设选股" for c in codes},
        )


class RandomPicker(StockPicker):
    """随机选股 — 基线对照组"""

    def __init__(self, stock_pool: List[str], pick_count: int = 1, seed: int = 42):
        self.stock_pool = stock_pool
        self.pick_count = pick_count
        self.rng = random.Random(seed)

    def pick(self, trade_date: date) -> PickResult:
        n = min(self.pick_count, len(self.stock_pool))
        codes = self.rng.sample(self.stock_pool, n)
        return PickResult(
            trade_date=trade_date,
            codes=codes,
            confidence={c: 50.0 for c in codes},
            reason={c: "RandomPicker 随机选股" for c in codes},
        )


class CachedPicker(StockPicker):
    """从 selection workflow 输出的 candidates JSON 读取历史选股结果."""

    def __init__(self, picks_file: str | None = None, picks_dir: str | None = None):
        self.schedule: Dict[date, List[str]] = {}
        self._meta: Dict[date, Dict[str, dict]] = {}

        if picks_file:
            self._load_picks_file(picks_file)
        elif picks_dir:
            self._load_picks_dir(picks_dir)

    def _load_picks_file(self, path: str) -> None:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        td = date.fromisoformat(data["trade_date"])
        codes = list(data.get("candidates") or [])
        snaps = data.get("ma_snapshots") or {}
        if not codes and data.get("final_picks"):
            picks = data["final_picks"]
            codes = [p["code"] for p in picks]
            snaps = {
                p["code"]: {**p.get("ma_snapshot", {}), **({"score": p["score"]} if "score" in p else {})}
                for p in picks
            }
        self.schedule[td] = codes
        self._meta[td] = {}
        for code in codes:
            snap = dict(snaps.get(code, {}))
            self._meta[td][code] = snap

    def _load_picks_dir(self, directory: str) -> None:
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".json"):
                continue
            if not (name.startswith("candidates_") or name.startswith("picks_")):
                continue
            self._load_picks_file(os.path.join(directory, name))

    def pick(self, trade_date: date) -> PickResult:
        codes = self.schedule.get(trade_date, [])
        meta = self._meta.get(trade_date, {})
        return PickResult(
            trade_date=trade_date,
            codes=codes,
            confidence={
                c: float(
                    meta.get(c, {}).get("composite_score")
                    or meta.get(c, {}).get("score")
                    or 80
                )
                for c in codes
            },
            reason={c: f"tier={meta.get(c, {}).get('tier', '')}" for c in codes},
        )
