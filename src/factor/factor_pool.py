"""因子池管理

管理QMT 400+因子和自定义因子的统一注册与查询。
"""
from typing import List, Dict, Optional

from src.common.db import get_session
from src.common.logger import get_logger
from src.data.models import FactorMeta

logger = get_logger(__name__)


class FactorPool:
    """因子池"""

    def __init__(self):
        self._meta_cache: Dict[str, int] = {}

    def load_meta(self) -> Dict[str, int]:
        """加载因子元信息缓存"""
        with get_session() as session:
            rows = session.query(FactorMeta).all()
            self._meta_cache = {r.factor_name: r.factor_id for r in rows}
        return self._meta_cache

    def list_factors(self, category: Optional[str] = None) -> List[dict]:
        """列出所有因子"""
        with get_session() as session:
            q = session.query(FactorMeta)
            if category:
                q = q.filter(FactorMeta.category == category)
            return [
                {
                    "factor_id": r.factor_id,
                    "factor_name": r.factor_name,
                    "category": r.category,
                    "description": r.description,
                    "data_source": r.data_source,
                }
                for r in q.all()
            ]

    def get_categories(self) -> List[str]:
        """获取所有因子分类"""
        with get_session() as session:
            rows = session.query(FactorMeta.category).distinct().all()
            return [r[0] for r in rows if r[0]]

    def get_factor_id(self, name: str) -> Optional[int]:
        if not self._meta_cache:
            self.load_meta()
        return self._meta_cache.get(name)
