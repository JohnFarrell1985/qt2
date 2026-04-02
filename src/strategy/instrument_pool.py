"""标的池管理

将股票按不同规则分组管理, 支持:
- 静态池: 手动指定股票列表
- 动态池: 根据筛选规则自动更新 (市值/行业/流动性等)
"""
import json
from datetime import datetime
from typing import Dict, Any, List, Optional

from sqlalchemy.dialects.postgresql import insert

from src.common.db import get_session
from src.common.logger import get_logger
from src.data.models import InstrumentPool

logger = get_logger(__name__)

BUILTIN_POOLS = {
    "沪深300": {
        "description": "沪深300成分股",
        "filter_rules": {"sector": "沪深300"},
    },
    "中证500": {
        "description": "中证500成分股",
        "filter_rules": {"sector": "中证500"},
    },
    "创业板": {
        "description": "创业板全部股票",
        "filter_rules": {"sector": "创业板"},
    },
    "科创板": {
        "description": "科创板全部股票",
        "filter_rules": {"sector": "科创板"},
    },
    "大市值": {
        "description": "总市值 > 500亿",
        "filter_rules": {"min_market_cap": 500},
    },
    "中小市值": {
        "description": "50亿 < 总市值 < 300亿",
        "filter_rules": {"min_market_cap": 50, "max_market_cap": 300},
    },
}


class InstrumentPoolManager:
    """标的池管理器"""

    def create_pool(
        self,
        name: str,
        codes: Optional[List[str]] = None,
        filter_rules: Optional[Dict[str, Any]] = None,
        description: str = "",
    ) -> int:
        """创建标的池"""
        with get_session() as session:
            stmt = insert(InstrumentPool).values(
                pool_name=name,
                description=description,
                codes_json=json.dumps(codes or [], ensure_ascii=False),
                filter_rules_json=json.dumps(filter_rules or {}, ensure_ascii=False),
                n_stocks=len(codes) if codes else 0,
                status="active",
            ).on_conflict_do_update(
                index_elements=["pool_name"],
                set_={
                    "description": description,
                    "codes_json": json.dumps(codes or [], ensure_ascii=False),
                    "filter_rules_json": json.dumps(filter_rules or {}, ensure_ascii=False),
                    "n_stocks": len(codes) if codes else 0,
                    "updated_at": datetime.now(),
                },
            ).returning(InstrumentPool.id)
            result = session.execute(stmt)
            pool_id = result.scalar_one()
            logger.info(f"标的池已创建/更新: {name} ({len(codes or [])} 只)")
            return pool_id

    def get_pool(self, name: str) -> Optional[Dict[str, Any]]:
        """获取标的池"""
        with get_session() as session:
            pool = session.query(InstrumentPool).filter_by(pool_name=name).first()
            return self._to_dict(pool) if pool else None

    def get_pool_codes(self, name: str) -> List[str]:
        """获取标的池中的股票代码列表"""
        pool = self.get_pool(name)
        if not pool:
            return []
        return pool.get("codes", [])

    def list_pools(self, status: Optional[str] = None) -> List[Dict[str, Any]]:
        """列出所有标的池"""
        with get_session() as session:
            q = session.query(InstrumentPool)
            if status:
                q = q.filter_by(status=status)
            rows = q.order_by(InstrumentPool.pool_name).all()
            return [self._to_dict(r) for r in rows]

    def update_pool_codes(self, name: str, codes: List[str]) -> None:
        """更新标的池股票列表"""
        with get_session() as session:
            pool = session.query(InstrumentPool).filter_by(pool_name=name).first()
            if pool:
                pool.codes_json = json.dumps(codes, ensure_ascii=False)
                pool.n_stocks = len(codes)
                pool.updated_at = datetime.now()
                logger.info(f"标的池 {name} 已更新: {len(codes)} 只")

    def refresh_dynamic_pool(self, name: str) -> List[str]:
        """根据筛选规则刷新动态标的池

        从数据库 stocks 表按规则查询后更新 codes。
        """
        pool = self.get_pool(name)
        if not pool:
            logger.warning(f"标的池 {name} 不存在")
            return []

        rules = pool.get("filter_rules", {})
        if not rules:
            return pool.get("codes", [])

        codes = self._apply_filter_rules(rules)
        self.update_pool_codes(name, codes)
        return codes

    def _apply_filter_rules(self, rules: Dict[str, Any]) -> List[str]:
        """应用筛选规则"""
        from sqlalchemy import text
        conditions = ["1=1"]
        params: Dict[str, Any] = {}

        if "sector" in rules:
            conditions.append("sector = :sector")
            params["sector"] = rules["sector"]
        if "exchange" in rules:
            conditions.append("exchange = :exchange")
            params["exchange"] = rules["exchange"]
        if "industry" in rules:
            conditions.append("industry = :industry")
            params["industry"] = rules["industry"]
        if "min_market_cap" in rules:
            conditions.append("market_cap >= :min_cap")
            params["min_cap"] = rules["min_market_cap"]
        if "max_market_cap" in rules:
            conditions.append("market_cap <= :max_cap")
            params["max_cap"] = rules["max_market_cap"]
        if "min_roe" in rules:
            conditions.append("roe >= :min_roe")
            params["min_roe"] = rules["min_roe"]
        if "max_pe" in rules:
            conditions.append("pe_ttm <= :max_pe AND pe_ttm > 0")
            params["max_pe"] = rules["max_pe"]

        where = " AND ".join(conditions)
        sql = text(f"SELECT code FROM stocks WHERE {where} ORDER BY code")

        with get_session() as session:
            result = session.execute(sql, params)
            return [row[0] for row in result.fetchall()]

    def init_builtin_pools(self) -> int:
        """初始化内置标的池"""
        count = 0
        for name, cfg in BUILTIN_POOLS.items():
            self.create_pool(
                name=name,
                filter_rules=cfg.get("filter_rules"),
                description=cfg.get("description", ""),
            )
            count += 1
        logger.info(f"已初始化 {count} 个内置标的池")
        return count

    @staticmethod
    def _to_dict(pool: InstrumentPool) -> Dict[str, Any]:
        return {
            "id": pool.id,
            "pool_name": pool.pool_name,
            "description": pool.description,
            "codes": json.loads(pool.codes_json) if pool.codes_json else [],
            "filter_rules": json.loads(pool.filter_rules_json) if pool.filter_rules_json else {},
            "n_stocks": pool.n_stocks,
            "status": pool.status,
            "created_at": pool.created_at.isoformat() if pool.created_at else None,
            "updated_at": pool.updated_at.isoformat() if pool.updated_at else None,
        }
