"""交易管理API"""

from fastapi import APIRouter
from pydantic import BaseModel

from src.common.logger import get_logger

router = APIRouter(prefix="/api/trading", tags=["交易管理"])
logger = get_logger(__name__)


class OrderRequest(BaseModel):
    code: str
    direction: str
    quantity: int
    price: float = 0
    price_type: str = "LATEST_PRICE"


@router.get("/positions")
def get_positions():
    """获取当前持仓"""
    return {"message": "请先连接QMT交易服务"}


@router.get("/asset")
def get_asset():
    """查询资产"""
    return {"message": "请先连接QMT交易服务"}


@router.get("/orders")
def get_orders():
    """查询当日委托"""
    return {"message": "请先连接QMT交易服务"}


@router.post("/order")
def submit_order(req: OrderRequest):
    """提交委托"""
    return {"message": "请先连接QMT交易服务", "request": req.model_dump()}
