"""宏观环境状态管理

读取项目根目录 macro_env.json, 维护当前宏观环境状态,
根据状态自动选择适用策略。
"""
import json
from datetime import date, datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

from src.common.logger import get_logger
from src.common.config import PROJECT_ROOT
from src.common.db import get_session
from src.data.models import MacroStateLog

logger = get_logger(__name__)

MACRO_CONFIG_PATH = PROJECT_ROOT / "macro_env.json"


class MacroEnvironment:
    """宏观环境管理器"""

    def __init__(self, config_path: Optional[str] = None):
        self._config_path = Path(config_path) if config_path else MACRO_CONFIG_PATH
        self._config: Dict[str, Any] = {}
        self._load_config()

    def _load_config(self) -> None:
        if self._config_path.exists():
            with open(self._config_path, "r", encoding="utf-8") as f:
                self._config = json.load(f)
            logger.info(f"宏观配置已加载: {len(self.get_all_states())} 种状态")
        else:
            logger.warning(f"宏观配置文件不存在: {self._config_path}")
            self._config = {"states": {}, "current_state": "range_bound"}

    def get_all_states(self) -> Dict[str, Any]:
        """获取所有宏观状态定义"""
        return self._config.get("states", {})

    def get_current_state(self) -> str:
        """获取当前宏观状态key"""
        return self._config.get("current_state", "range_bound")

    def get_state_detail(self, state_key: Optional[str] = None) -> Dict[str, Any]:
        """获取状态详细信息"""
        key = state_key or self.get_current_state()
        return self.get_all_states().get(key, {})

    def get_position_multiplier(self, state_key: Optional[str] = None) -> float:
        """获取当前状态的仓位乘数"""
        detail = self.get_state_detail(state_key)
        return detail.get("position_multiplier", 1.0)

    def get_preferred_strategies(self, state_key: Optional[str] = None) -> List[str]:
        """获取当前状态下优先使用的策略"""
        detail = self.get_state_detail(state_key)
        return detail.get("preferred_strategies", [])

    def get_avoid_strategies(self, state_key: Optional[str] = None) -> List[str]:
        """获取当前状态下需要回避的策略"""
        detail = self.get_state_detail(state_key)
        return detail.get("avoid_strategies", [])

    def set_current_state(
        self,
        state_key: str,
        detail_json: Optional[Dict] = None,
        determined_by: str = "manual",
    ) -> None:
        """切换宏观状态并记录"""
        old_state = self.get_current_state()
        if state_key not in self.get_all_states():
            raise ValueError(f"未知宏观状态: {state_key}, 可选: {list(self.get_all_states().keys())}")

        self._config["current_state"] = state_key
        self._save_config()

        try:
            with get_session() as session:
                log = MacroStateLog(
                    state_key=state_key,
                    state_detail_json=json.dumps(detail_json or {}, ensure_ascii=False),
                    determined_by=determined_by,
                    effective_date=date.today(),
                )
                session.add(log)
        except Exception as e:
            logger.warning(f"记录宏观状态到DB失败: {e}")

        logger.info(f"宏观状态切换: {old_state} → {state_key} (by {determined_by})")

    def _save_config(self) -> None:
        """保存配置到文件"""
        with open(self._config_path, "w", encoding="utf-8") as f:
            json.dump(self._config, f, ensure_ascii=False, indent=2)

    def get_strategy_macro_mapping(self) -> Dict[str, List[str]]:
        """获取所有 {宏观状态 -> 推荐策略列表} 映射"""
        mapping = {}
        for key, state in self.get_all_states().items():
            mapping[key] = state.get("preferred_strategies", [])
        return mapping

    def get_state_history(self, limit: int = 30) -> List[Dict[str, Any]]:
        """查询宏观状态变更历史"""
        with get_session() as session:
            rows = (
                session.query(MacroStateLog)
                .order_by(MacroStateLog.effective_date.desc())
                .limit(limit)
                .all()
            )
            return [
                {
                    "state_key": r.state_key,
                    "detail": json.loads(r.state_detail_json) if r.state_detail_json else {},
                    "determined_by": r.determined_by,
                    "effective_date": r.effective_date.isoformat() if r.effective_date else None,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in rows
            ]

    def summary(self) -> Dict[str, Any]:
        """当前宏观环境摘要"""
        state_key = self.get_current_state()
        detail = self.get_state_detail()
        return {
            "current_state": state_key,
            "label": detail.get("label", ""),
            "description": detail.get("description", ""),
            "position_multiplier": detail.get("position_multiplier", 1.0),
            "preferred_strategies": detail.get("preferred_strategies", []),
            "avoid_strategies": detail.get("avoid_strategies", []),
            "indicators": detail.get("indicators", {}),
        }
