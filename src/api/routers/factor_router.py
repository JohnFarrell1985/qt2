"""因子分析API"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query

from src.factor.factor_pool import FactorPool

router = APIRouter(prefix="/api/factor", tags=["因子分析"])


def get_factor_pool() -> FactorPool:
    return FactorPool()


@router.get("/list")
def list_factors(pool: FactorPool = Depends(get_factor_pool), category: Optional[str] = None):
    """获取因子列表"""
    return pool.list_factors(category)


@router.get("/categories")
def list_categories(pool: FactorPool = Depends(get_factor_pool)):
    """获取因子分类"""
    return pool.get_categories()
