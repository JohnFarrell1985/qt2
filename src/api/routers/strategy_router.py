"""策略池 / 标的池 / 宏观环境 / 三档策略引擎 API"""
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from src.common.logger import get_logger
from src.strategy.strategy_pool import StrategyPool
from src.strategy.instrument_pool import InstrumentPoolManager
from src.strategy.macro_env import MacroEnvironment
from src.strategy.orchestrator import StrategyOrchestrator
from src.strategy.registry import registry

logger = get_logger(__name__)
router = APIRouter(prefix="/strategy", tags=["策略管理"])


def get_strategy_pool() -> StrategyPool:
    return StrategyPool()


def get_instrument_mgr() -> InstrumentPoolManager:
    return InstrumentPoolManager()


def get_macro_env() -> MacroEnvironment:
    return MacroEnvironment()


def get_orchestrator() -> StrategyOrchestrator:
    return StrategyOrchestrator()


# ================================================================
# Strategy CRUD (支持三档)
# ================================================================

class StrategyCreate(BaseModel):
    name: str
    strategy_tier: str = "ml"
    strategy_class: str = ""
    config: dict = {}
    factor_names: List[str] = []
    factor_weights: dict = {}
    model_params: dict = {}
    description: str = ""
    applicable_macro: List[str] = []


@router.post("/strategies")
def create_strategy(req: StrategyCreate, pool_mgr: StrategyPool = Depends(get_strategy_pool)):
    sid = pool_mgr.create_strategy(
        name=req.name,
        strategy_tier=req.strategy_tier,
        strategy_class=req.strategy_class,
        config=req.config,
        factor_names=req.factor_names,
        factor_weights=req.factor_weights,
        model_params=req.model_params,
        description=req.description,
        applicable_macro=req.applicable_macro,
    )
    return {"strategy_id": sid}


@router.get("/strategies")
def list_strategies(pool_mgr: StrategyPool = Depends(get_strategy_pool), status: Optional[str] = None, tier: Optional[str] = None):
    strats = pool_mgr.list_strategies(status=status)
    if tier:
        strats = [s for s in strats if s.get("strategy_tier") == tier]
    return strats


@router.get("/strategies/{name}")
def get_strategy(name: str, pool_mgr: StrategyPool = Depends(get_strategy_pool)):
    s = pool_mgr.get_strategy(name)
    if not s:
        raise HTTPException(404, f"策略 {name} 不存在")
    return s


@router.put("/strategies/{name}/status")
def set_strategy_status(name: str, status: str, pool_mgr: StrategyPool = Depends(get_strategy_pool)):
    pool_mgr.set_status(name, status)
    return {"ok": True}


@router.get("/strategies/rank/{metric}")
def rank_strategies(metric: str = "backtest_sharpe", pool_mgr: StrategyPool = Depends(get_strategy_pool)):
    df = pool_mgr.rank_strategies(metric)
    return df.to_dict(orient="records") if not df.empty else []


# ================================================================
# Registry — 查询已注册的策略类
# ================================================================

@router.get("/registry")
def list_registered():
    """查看全局 registry 中已注册的所有策略类"""
    return registry.list_all()


@router.get("/registry/{tier}")
def list_registered_by_tier(tier: str):
    return registry.list_by_tier(tier)


# ================================================================
# Signal Generation — 三档策略信号生成
# ================================================================

class SignalRequest(BaseModel):
    strategy_class: str
    config: dict = {}
    universe: List[str] = []
    pool_name: str = ""
    trade_date: Optional[str] = None


@router.post("/signals/generate")
def generate_signals(req: SignalRequest, instrument_mgr: InstrumentPoolManager = Depends(get_instrument_mgr)):
    """直接调用指定策略类生成信号"""
    td = date.fromisoformat(req.trade_date) if req.trade_date else date.today()

    universe = req.universe
    if not universe and req.pool_name:
        universe = instrument_mgr.get_pool_codes(req.pool_name)
    if not universe:
        raise HTTPException(400, "需要提供 universe 或 pool_name")

    try:
        strat = registry.create(req.strategy_class, config=req.config)
    except KeyError as e:
        raise HTTPException(404, str(e))

    try:
        signals = strat.generate_signals(td, universe)
    except Exception as e:
        logger.error(f"策略 {req.strategy_class} 信号生成失败: {e}")
        raise HTTPException(500, f"信号生成失败: {e}")

    return {
        "strategy": req.strategy_class,
        "trade_date": td.isoformat(),
        "n_signals": len(signals),
        "signals": [
            {
                "code": s.code, "direction": s.direction,
                "score": s.score, "reason": s.reason,
            }
            for s in signals
        ],
    }


class ExecuteRequest(BaseModel):
    trade_date: Optional[str] = None
    total_capital: float = 1_000_000.0
    available_cash: float = 0.0
    holdings: List[dict] = []
    price_map: dict = {}


@router.post("/execute")
def execute_plan(req: ExecuteRequest, orch: StrategyOrchestrator = Depends(get_orchestrator)):
    """完整执行: 策略信号 → 持仓监控 → 仲裁 → 仓位 → 操作清单

    输入当前持仓和资金, 输出今日操作指令。
    """
    from src.strategy.base import HoldingPosition

    td = date.fromisoformat(req.trade_date) if req.trade_date else None
    holdings = []
    for h in req.holdings:
        holdings.append(HoldingPosition(
            code=h["code"],
            buy_date=date.fromisoformat(h.get("buy_date", "2025-01-01")),
            buy_price=h.get("buy_price", 0),
            quantity=h.get("quantity", 0),
            current_price=h.get("current_price", 0),
            highest_price=h.get("highest_price", 0),
            hold_days=h.get("hold_days", 0),
            strategy_name=h.get("strategy_name", ""),
            profit_pct=h.get("profit_pct", 0),
            can_sell=h.get("can_sell", True),
        ))

    result = orch.execute(
        trade_date=td,
        holdings=holdings,
        total_capital=req.total_capital,
        available_cash=req.available_cash or req.total_capital * 0.5,
        price_map=req.price_map,
    )

    actions_out = []
    for a in result.get("actions", []):
        actions_out.append({
            "code": a.code,
            "direction": a.direction,
            "priority": a.priority,
            "target_quantity": a.target_quantity,
            "target_amount": a.target_amount,
            "target_weight_pct": a.target_weight_pct,
            "reasons": a.reasons,
        })

    return {
        "summary": result.get("summary", {}),
        "actions": actions_out,
    }


# ================================================================
# Instrument Pool
# ================================================================

class PoolCreate(BaseModel):
    name: str
    codes: List[str] = []
    filter_rules: dict = {}
    description: str = ""


@router.post("/pools")
def create_pool(req: PoolCreate, instrument_mgr: InstrumentPoolManager = Depends(get_instrument_mgr)):
    pid = instrument_mgr.create_pool(
        name=req.name,
        codes=req.codes,
        filter_rules=req.filter_rules,
        description=req.description,
    )
    return {"pool_id": pid}


@router.get("/pools")
def list_pools(instrument_mgr: InstrumentPoolManager = Depends(get_instrument_mgr), status: Optional[str] = None):
    return instrument_mgr.list_pools(status=status)


@router.get("/pools/{name}")
def get_pool(name: str, instrument_mgr: InstrumentPoolManager = Depends(get_instrument_mgr)):
    p = instrument_mgr.get_pool(name)
    if not p:
        raise HTTPException(404, f"标的池 {name} 不存在")
    return p


@router.post("/pools/{name}/refresh")
def refresh_pool(name: str, instrument_mgr: InstrumentPoolManager = Depends(get_instrument_mgr)):
    codes = instrument_mgr.refresh_dynamic_pool(name)
    return {"pool_name": name, "n_stocks": len(codes)}


@router.post("/pools/init-builtin")
def init_builtin_pools(instrument_mgr: InstrumentPoolManager = Depends(get_instrument_mgr)):
    count = instrument_mgr.init_builtin_pools()
    return {"initialized": count}


# ================================================================
# Macro Environment
# ================================================================

@router.get("/macro/summary")
def macro_summary(macro_env: MacroEnvironment = Depends(get_macro_env)):
    return macro_env.summary()


@router.get("/macro/states")
def macro_states(macro_env: MacroEnvironment = Depends(get_macro_env)):
    return macro_env.get_all_states()


@router.put("/macro/state")
def set_macro_state(state_key: str, macro_env: MacroEnvironment = Depends(get_macro_env), determined_by: str = "manual"):
    try:
        macro_env.set_current_state(state_key, determined_by=determined_by)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return macro_env.summary()


@router.get("/macro/history")
def macro_history(macro_env: MacroEnvironment = Depends(get_macro_env), limit: int = 30):
    return macro_env.get_state_history(limit)


@router.get("/macro/mapping")
def macro_strategy_mapping(macro_env: MacroEnvironment = Depends(get_macro_env)):
    return macro_env.get_strategy_macro_mapping()


# ================================================================
# Orchestrator — 分配与执行计划
# ================================================================

class AllocationCreate(BaseModel):
    strategy_name: str
    pool_name: str
    macro_state: str = ""
    weight: float = 1.0


@router.post("/allocations")
def create_allocation(req: AllocationCreate, orch: StrategyOrchestrator = Depends(get_orchestrator)):
    try:
        aid = orch.create_allocation(
            strategy_name=req.strategy_name,
            pool_name=req.pool_name,
            macro_state=req.macro_state,
            weight=req.weight,
        )
        return {"allocation_id": aid}
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.get("/allocations")
def list_allocations(orch: StrategyOrchestrator = Depends(get_orchestrator), macro_state: Optional[str] = None):
    return orch.get_active_allocations(macro_state)


@router.get("/plan")
def current_plan(orch: StrategyOrchestrator = Depends(get_orchestrator)):
    """获取基于当前宏观环境的策略执行计划"""
    return orch.get_current_plan()


@router.delete("/allocations/{allocation_id}")
def deactivate_allocation(allocation_id: int, orch: StrategyOrchestrator = Depends(get_orchestrator)):
    orch.deactivate_allocation(allocation_id)
    return {"ok": True}
