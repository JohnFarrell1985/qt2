"""数据源注册中心 — JSON 驱动的多数据源管理

DataSourceDef: 数据源描述 (含能力矩阵和限流参数)
DataSourceRegistry: 注册 / 查询 / 启停 / 降级链查询
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from src.common.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_JSON = Path(__file__).parent / "data_sources.json"


@dataclass
class DataSourceDef:
    """数据源定义。

    Attributes:
        name: 唯一名称标识
        display_name: 显示名称
        priority: 优先级 (越小越优先)
        collector_class: 采集器类的完整路径 (如 "src.datacollect.collectors.xx.Cls")
        package: 依赖的 Python 包名 (用于可用性检测)
        needs_token: 是否需要 API Token
        token_env: Token 环境变量名
        rate_domain: 限流域名
        rate: 令牌桶速率 (tokens/sec)
        burst: 令牌桶突发上限
        capabilities: 支持的数据类型列表
        enabled: 是否启用
    """
    name: str
    display_name: str = ""
    priority: int = 99
    collector_class: str | None = None
    package: str | None = None
    needs_token: bool = False
    token_env: str = ""
    rate_domain: str = "default"
    rate: float = 1.0
    burst: int = 5
    capabilities: list[str] = field(default_factory=list)
    history_depth_years: int = 10
    supports_realtime: bool = False
    enabled: bool = True
    note: str = ""
    extra: dict = field(default_factory=dict)


class DataSourceRegistry:
    """JSON 驱动的数据源注册中心。

    支持从 data_sources.json 加载数据源定义和降级链配置。
    """

    def __init__(self) -> None:
        self._sources: dict[str, DataSourceDef] = {}
        self._fallback_chains: dict[str, list[str]] = {}

    @classmethod
    def from_json(cls, path: Path | str | None = None) -> DataSourceRegistry:
        """从 JSON 配置文件创建 registry 实例。"""
        path = Path(path) if path else _DEFAULT_JSON
        if not path.exists():
            logger.warning("数据源配置文件不存在: %s", path)
            return cls()

        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        reg = cls()
        for name, src_dict in data.get("sources", {}).items():
            reg.register(name, src_dict)

        for data_type, chain in data.get("fallback_chains", {}).items():
            reg._fallback_chains[data_type] = chain

        logger.info(
            "从 %s 加载 %d 个数据源, %d 条降级链",
            path.name, len(reg._sources), len(reg._fallback_chains),
        )
        return reg

    def register(self, name: str, config: DataSourceDef | dict) -> None:
        """注册一个数据源定义。"""
        if isinstance(config, dict):
            config = DataSourceDef(name=name, **{
                k: v for k, v in config.items()
                if k in DataSourceDef.__dataclass_fields__
            })
        if config.name != name:
            config.name = name
        self._sources[name] = config
        logger.debug("注册数据源: %s (priority=%d, enabled=%s)", name, config.priority, config.enabled)

    def unregister(self, name: str) -> bool:
        """注销一个数据源, 返回是否存在并被移除。"""
        removed = self._sources.pop(name, None)
        return removed is not None

    def get(self, name: str) -> DataSourceDef | None:
        """按名称获取数据源定义。"""
        return self._sources.get(name)

    def list_all(self) -> list[DataSourceDef]:
        """列出所有已注册的数据源 (按 priority 排序)。"""
        return sorted(self._sources.values(), key=lambda s: s.priority)

    def list_enabled(self) -> list[DataSourceDef]:
        """列出所有启用的数据源 (按 priority 排序)。"""
        return sorted(
            (ds for ds in self._sources.values() if ds.enabled),
            key=lambda s: s.priority,
        )

    def list_by_capability(self, capability: str) -> list[DataSourceDef]:
        """列出支持指定能力的所有已启用数据源 (按 priority 排序)。"""
        return sorted(
            (ds for ds in self._sources.values() if ds.enabled and capability in ds.capabilities),
            key=lambda s: s.priority,
        )

    def get_fallback_chain(self, data_type: str) -> list[str]:
        """获取指定数据类型的降级链 (仅返回已启用的数据源名)。"""
        chain = self._fallback_chains.get(data_type, [])
        return [name for name in chain if name in self._sources and self._sources[name].enabled]

    def set_fallback_chain(self, data_type: str, chain: list[str]) -> None:
        """设置指定数据类型的降级链。"""
        self._fallback_chains[data_type] = chain

    def set_enabled(self, name: str, enabled: bool) -> bool:
        """启用或禁用指定数据源, 返回操作是否成功。"""
        ds = self._sources.get(name)
        if ds is None:
            return False
        ds.enabled = enabled
        logger.info("数据源 %s 已%s", name, "启用" if enabled else "禁用")
        return True

    def summary(self) -> list[dict]:
        """返回所有数据源的摘要信息 (供 CLI/API 展示)。"""
        return [
            {
                "name": ds.name,
                "display_name": ds.display_name,
                "priority": ds.priority,
                "enabled": ds.enabled,
                "capabilities": ds.capabilities,
                "needs_token": ds.needs_token,
                "supports_realtime": ds.supports_realtime,
                "note": ds.note,
            }
            for ds in self.list_all()
        ]

    def __len__(self) -> int:
        return len(self._sources)

    def __contains__(self, name: str) -> bool:
        return name in self._sources
