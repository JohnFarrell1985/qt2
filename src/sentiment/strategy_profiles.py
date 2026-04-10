"""策略参数 Profile 管理

同一策略在不同宏观环境下使用不同参数。
Profile 覆盖 .env 默认值, null 表示使用默认参数。

加载优先级: .env 默认值 → strategy_profiles.json 覆盖

用法:
    profile = get_strategy_config("momentum", "bull_strong")
    merged = {**default_from_env, **profile}
"""
import json
from pathlib import Path
from typing import Optional

from src.common.config import PROJECT_ROOT
from src.common.logger import get_logger

logger = get_logger(__name__)

_PROFILES_CACHE: Optional[dict] = None
_PROFILES_PATH = PROJECT_ROOT / "strategy_profiles.json"


def load_profiles(path: Optional[Path] = None) -> dict:
    """加载策略参数 Profile, 带缓存"""
    global _PROFILES_CACHE

    if _PROFILES_CACHE is not None and path is None:
        return _PROFILES_CACHE

    filepath = path or _PROFILES_PATH
    if not filepath.exists():
        logger.warning(f"[Profile] 未找到配置文件: {filepath}")
        return {}

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    profiles = {k: v for k, v in data.items() if not k.startswith("_")}

    if path is None:
        _PROFILES_CACHE = profiles

    logger.info(f"[Profile] 加载 {len(profiles)} 个策略配置")
    return profiles


def get_strategy_config(
    strategy_name: str,
    macro_state: str,
    profiles: Optional[dict] = None,
) -> dict:
    """获取指定策略在指定宏观状态下的参数覆盖

    Args:
        strategy_name: 策略名 (如 "momentum")
        macro_state: 宏观状态 (如 "bull_strong")
        profiles: 预加载的 profiles dict, None 则从文件加载

    Returns:
        参数覆盖 dict (空 dict 表示使用 .env 默认值,
        特殊情况: 返回值中的 "_disabled" key 表示该策略在此状态下禁用)
    """
    if profiles is None:
        profiles = load_profiles()

    if strategy_name not in profiles:
        return {}

    state_config = profiles[strategy_name].get(macro_state)

    if state_config is None:
        return {}

    return state_config


def is_strategy_disabled(
    strategy_name: str,
    macro_state: str,
    profiles: Optional[dict] = None,
) -> bool:
    """判断策略是否在指定宏观状态下被禁用

    禁用条件: Profile 中该策略该状态的值为 null
    """
    if profiles is None:
        profiles = load_profiles()

    if strategy_name not in profiles:
        return False

    strategy_profiles = profiles[strategy_name]
    if macro_state not in strategy_profiles:
        return False

    return strategy_profiles[macro_state] is None


def list_active_strategies(macro_state: str) -> list[str]:
    """列出在指定宏观状态下未被禁用的所有策略"""
    profiles = load_profiles()
    active = []
    for strategy_name, state_map in profiles.items():
        if macro_state not in state_map:
            active.append(strategy_name)
        elif state_map[macro_state] is not None:
            active.append(strategy_name)
    return active


def reload_profiles() -> dict:
    """强制重新加载配置文件 (热更新)"""
    global _PROFILES_CACHE
    _PROFILES_CACHE = None
    return load_profiles()
