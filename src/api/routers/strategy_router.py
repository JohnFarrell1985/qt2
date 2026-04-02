"""策略池 / 标的池 / 宏观环境 API"""
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.common.logger import get_logger
from src.strategy.strategy_pool import StrategyPool
from src.strategy.instrument_pool import InstrumentPoolManager
from src.strategy.macro_env import MacroEnvironment
from src.strategy.orchestrator import StrategyOrchestrator

logger = get_logger(__name__)
router = APIRouter(prefix="/strategy", tags=["策略管理"])

pool_mgr = StrategyPool()
instrument_mgr = InstrumentPoolManager()
macro_env = MacroEnvironment()
orchestrator = StrategyOrchestrator()


# ---- Strategy ----

class StrategyCreate(BaseModel):
    name: str
    factor_names: List[str]
    factor_weights: dict = {}
    model_params: dict = {}
    description: str = ""
    applicable_macro: List[str] = []


@router.post("/strategies")
def create_strategy(req: StrategyCreate):
    sid = pool_mgr.create_strategy(
        name=req.name,
        factor_names=req.factor_names,
        factor_weights=req.factor_weights,
        model_params=req.model_params,
        description=req.description,
        applicable_macro=req.applicable_macro,
    )
    return {"strategy_id": sid}


@router.get("/strategies")
def list_strategies(status: Optional[str] = None):
    return pool_mgr.list_strategies(status=status)


@router.get("/strategies/{name}")
def get_strategy(name: str):
    s = pool_mgr.get_strategy(name)
    if not s:
        raise HTTPException(404, f"策略 {name} 不存在")
    return s


@router.put("/strategies/{name}/status")
def set_strategy_status(name: str, status: str):
    pool_mgr.set_status(name, status)
    return {"ok": True}


@router.get("/strategies/rank/{metric}")
def rank_strategies(metric: str = "backtest_sharpe"):
    df = pool_mgr.rank_strategies(metric)
    return df.to_dict(orient="records") if not df.empty else []


# ---- Instrument Pool ----

class PoolCreate(BaseModel):
    name: str
    codes: List[str] = []
    filter_rules: dict = {}
    description: str = ""


@router.post("/pools")
def create_pool(req: PoolCreate):
    pid = instrument_mgr.create_pool(
        name=req.name,
        codes=req.codes,
        filter_rules=req.filter_rules,
        description=req.description,
    )
    return {"pool_id": pid}


@router.get("/pools")
def list_pools(status: Optional[str] = None):
    return instrument_mgr.list_pools(status=status)


@router.get("/pools/{name}")
def get_pool(name: str):
    p = instrument_mgr.get_pool(name)
    if not p:
        raise HTTPException(404, f"标的池 {name} 不存在")
    return p


@router.post("/pools/{name}/refresh")
def refresh_pool(name: str):
    codes = instrument_mgr.refresh_dynamic_pool(name)
    return {"pool_name": name, "n_stocks": len(codes)}


@router.post("/pools/init-builtin")
def init_builtin_pools():
    count = instrument_mgr.init_builtin_pools()
    return {"initialized": count}


# ---- Macro Environment ----

@router.get("/macro/summary")
def macro_summary():
    return macro_env.summary()


@router.get("/macro/states")
def macro_states():
    return macro_env.get_all_states()


@router.put("/macro/state")
def set_macro_state(state_key: str, determined_by: str = "manual"):
    try:
        macro_env.set_current_state(state_key, determined_by=determined_by)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return macro_env.summary()


@router.get("/macro/history")
def macro_history(limit: int = 30):
    return macro_env.get_state_history(limit)


@router.get("/macro/mapping")
def macro_strategy_mapping():
    return macro_env.get_strategy_macro_mapping()


# ---- Orchestrator ----

class AllocationCreate(BaseModel):
    strategy_name: str
    pool_name: str
    macro_state: str = ""
    weight: float = 1.0


@router.post("/allocations")
def create_allocation(req: AllocationCreate):
    try:
        aid = orchestrator.create_allocation(
            strategy_name=req.strategy_name,
            pool_name=req.pool_name,
            macro_state=req.macro_state,
            weight=req.weight,
        )
        return {"allocation_id": aid}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/allocations")
def list_allocations(macro_state: Optional[str] = None):
    return orchestrator.get_active_allocations(macro_state)


@router.get("/plan")
def current_plan():
    """获取基于当前宏观环境的策略执行计划"""
    return orchestrator.get_current_plan()


@router.delete("/allocations/{allocation_id}")
def deactivate_allocation(allocation_id: int):
    orchestrator.deactivate_allocation(allocation_id)
    return {"ok": True}
