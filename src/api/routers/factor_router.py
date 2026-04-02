"""因子分析API"""
from typing import List, Optional

from fastapi import APIRouter, Query

from src.factor.factor_pool import FactorPool

router = APIRouter(prefix="/api/factor", tags=["因子分析"])

_pool = FactorPool()


@router.get("/list")
def list_factors(category: Optional[str] = None):
    """获取因子列表"""
    return _pool.list_factors(category)


@router.get("/categories")
def list_categories():
    """获取因子分类"""
    return _pool.get_categories()
