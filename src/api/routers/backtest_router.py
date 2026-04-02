"""回测API"""
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/backtest", tags=["回测"])


class BacktestRequest(BaseModel):
    schedule_file: Optional[str] = None
    stock_pool: Optional[str] = None
    start_date: str = "2025-01-01"
    end_date: str = "2025-12-31"
    initial_capital: float = 1_000_000
    max_position_pct: float = 0.30
    max_holdings: int = 3
    continuous: bool = False


@router.post("/run")
def run_backtest(req: BacktestRequest):
    """运行回测"""
    from src.backtest.strategy_runner import run_strategy, run_continuous, StrategyConfig
    from src.backtest.stock_picker import MockPicker, RandomPicker
    from src.backtest.performance import full_performance_report

    try:
        start = datetime.strptime(req.start_date, "%Y-%m-%d").date()
        end = datetime.strptime(req.end_date, "%Y-%m-%d").date()

        config = StrategyConfig(
            initial_capital=req.initial_capital,
            max_position_pct=req.max_position_pct,
            max_holdings=req.max_holdings,
        )

        if req.schedule_file:
            picker = MockPicker(schedule_file=req.schedule_file)
        elif req.stock_pool:
            pool = [c.strip() for c in req.stock_pool.split(",")]
            picker = RandomPicker(pool, pick_count=1)
        else:
            raise HTTPException(status_code=400, detail="需要 schedule_file 或 stock_pool")

        if req.continuous:
            result = run_continuous(picker, start, end, config)
        else:
            result = run_strategy(picker, start, end, config)

        perf = full_performance_report(result.equity_curve)
        return {**result.to_dict(), "performance": perf}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
