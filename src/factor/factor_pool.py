"""因子池管理

管理QMT 400+因子和自定义因子的统一注册与查询。
P2-36 增强: 支持因子版本追溯 (version 字段 + UniqueConstraint)。
"""
from typing import List, Dict, Optional

from sqlalchemy import func as sa_func

from src.common.db import get_session
from src.common.logger import get_logger
from src.data.models import FactorMeta

logger = get_logger(__name__)


class FactorPool:
    """因子池 — 支持版本追溯"""

    def __init__(self):
        self._meta_cache: Dict[str, int] = {}

    def load_meta(self) -> Dict[str, int]:
        """加载因子元信息缓存 (最新版本)"""
        with get_session(readonly=True) as session:
            rows = session.query(FactorMeta).all()
            self._meta_cache = {r.factor_name: r.factor_id for r in rows}
        return self._meta_cache

    def list_factors(
        self,
        category: Optional[str] = None,
        latest_only: bool = True,
    ) -> List[dict]:
        """列出因子

        Args:
            category: 按分类过滤
            latest_only: True 则每个 factor_name 只返回最新版本
        """
        with get_session(readonly=True) as session:
            q = session.query(FactorMeta)
            if category:
                q = q.filter(FactorMeta.category == category)

            all_rows = q.all()

        if latest_only:
            latest: Dict[str, FactorMeta] = {}
            for r in all_rows:
                if r.factor_name not in latest or r.version > latest[r.factor_name].version:
                    latest[r.factor_name] = r
            all_rows = list(latest.values())

        return [
            {
                "factor_id": r.factor_id,
                "factor_name": r.factor_name,
                "version": r.version,
                "category": r.category,
                "description": r.description,
                "data_source": r.data_source,
                "qmt_field": r.qmt_field,
                "factor_kind": r.factor_kind,
                "update_freq": r.update_freq,
                "storage_hint": r.storage_hint,
            }
            for r in all_rows
        ]

    def get_categories(self) -> List[str]:
        with get_session(readonly=True) as session:
            rows = session.query(FactorMeta.category).distinct().all()
            return [r[0] for r in rows if r[0]]

    def get_factor_id(self, name: str, version: Optional[int] = None) -> Optional[int]:
        """获取因子 ID, 默认返回最新版本"""
        if version is None and self._meta_cache:
            return self._meta_cache.get(name)
        if not self._meta_cache and version is None:
            self.load_meta()
            return self._meta_cache.get(name)
        with get_session(readonly=True) as session:
            q = session.query(FactorMeta.factor_id).filter(FactorMeta.factor_name == name)
            if version is not None:
                q = q.filter(FactorMeta.version == version)
            else:
                q = q.order_by(FactorMeta.version.desc())
            row = q.first()
            return row[0] if row else None

    def get_versions(self, name: str) -> List[dict]:
        """获取指定因子所有版本 (P2-36)"""
        with get_session(readonly=True) as session:
            rows = (
                session.query(FactorMeta)
                .filter(FactorMeta.factor_name == name)
                .order_by(FactorMeta.version)
                .all()
            )
            return [
                {
                    "factor_id": r.factor_id,
                    "version": r.version,
                    "description": r.description,
                    "created_at": r.created_at,
                }
                for r in rows
            ]

    def register_new_version(
        self,
        name: str,
        category: str = "",
        description: str = "",
        data_source: str = "calculated",
        factor_kind: Optional[str] = "calculated",
        update_freq: Optional[str] = "daily",
        storage_hint: Optional[str] = "factor_values",
    ) -> int:
        """注册因子新版本, 自动递增 version (P2-36)

        Returns:
            新版本的 factor_id
        """
        with get_session() as session:
            max_ver = (
                session.query(sa_func.coalesce(sa_func.max(FactorMeta.version), 0))
                .filter(FactorMeta.factor_name == name)
                .scalar()
            )
            new_ver = max_ver + 1
            meta = FactorMeta(
                factor_name=name,
                version=new_ver,
                category=category,
                description=description,
                data_source=data_source,
                factor_kind=factor_kind,
                update_freq=update_freq,
                storage_hint=storage_hint,
            )
            session.add(meta)
            session.flush()
            fid = meta.factor_id
            logger.info("注册因子 %s v%d (id=%d)", name, new_ver, fid)
            return fid
