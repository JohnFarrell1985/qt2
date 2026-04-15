"""实验历史 Trace (P2-18)

记录每轮迭代: 假设 → 实现 → 结果 → 反馈。
支持智能过滤: 做因子时只看因子历史 + 最新成功模型, 反之亦然。

参考: RD-Agent rdagent/core/proposal.py (Trace)
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.common.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ExperimentRecord:
    """单轮实验记录"""
    round_id: int
    action: str
    hypothesis: str = ""
    implementation: str = ""
    metrics: Dict[str, float] = field(default_factory=dict)
    reward: float = 0.0
    success: bool = False
    timestamp: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)


class ExperimentTrace:
    """实验历史追踪器"""

    def __init__(self, max_history: int = 200):
        self.records: List[ExperimentRecord] = []
        self.max_history = max_history
        self._round_counter = 0

    def append(
        self,
        action: str,
        hypothesis: str = "",
        implementation: str = "",
        metrics: Optional[Dict[str, float]] = None,
        reward: float = 0.0,
        success: bool = False,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExperimentRecord:
        self._round_counter += 1
        record = ExperimentRecord(
            round_id=self._round_counter,
            action=action,
            hypothesis=hypothesis,
            implementation=implementation,
            metrics=metrics or {},
            reward=reward,
            success=success,
            metadata=metadata or {},
        )
        self.records.append(record)
        if len(self.records) > self.max_history:
            self.records = self.records[-self.max_history:]
        return record

    def last_metrics(self) -> Optional[Dict[str, float]]:
        """获取最近一轮的指标"""
        if not self.records:
            return None
        return self.records[-1].metrics

    def filter_by_action(self, action: str, limit: int = 20) -> List[ExperimentRecord]:
        """按动作类型过滤历史"""
        filtered = [r for r in self.records if r.action == action]
        return filtered[-limit:]

    def get_context_for_action(self, action: str, limit: int = 10) -> List[Dict]:
        """获取上下文供 LLM 参考

        做因子时: 因子历史 + 最新成功模型
        做模型时: 模型历史 + 最新成功因子
        """
        same = self.filter_by_action(action, limit=limit)
        other = "model" if action == "factor" else "factor"
        best_other = [r for r in self.records if r.action == other and r.success]
        best_other = best_other[-3:] if best_other else []

        context = [asdict(r) for r in same + best_other]
        for c in context:
            c.pop("timestamp", None)
        return context

    def get_best_record(self, action: Optional[str] = None) -> Optional[ExperimentRecord]:
        """获取奖励最高的记录"""
        candidates = self.records
        if action:
            candidates = [r for r in candidates if r.action == action]
        if not candidates:
            return None
        return max(candidates, key=lambda r: r.reward)

    def success_rate(self, action: Optional[str] = None) -> float:
        candidates = self.records
        if action:
            candidates = [r for r in candidates if r.action == action]
        if not candidates:
            return 0.0
        return sum(1 for r in candidates if r.success) / len(candidates)

    def save(self, path: str) -> None:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = [asdict(r) for r in self.records]
        p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("实验历史已保存: %s (%d 条)", path, len(self.records))

    def load(self, path: str) -> None:
        p = Path(path)
        if not p.exists():
            return
        data = json.loads(p.read_text(encoding="utf-8"))
        self.records = [ExperimentRecord(**d) for d in data]
        self._round_counter = max((r.round_id for r in self.records), default=0)
        logger.info("实验历史已加载: %s (%d 条)", path, len(self.records))
