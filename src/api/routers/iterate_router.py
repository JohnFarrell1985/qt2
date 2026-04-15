"""自动迭代优化 API"""
import gc
import threading
import traceback
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from src.common.logger import get_logger
from src.ml.auto_iterate import AutoIterateEngine

logger = get_logger(__name__)
router = APIRouter(prefix="/iterate", tags=["自动迭代"])

_running_engine: Optional[AutoIterateEngine] = None
_is_running = False
_running_lock = threading.Lock()
_last_error: Optional[str] = None


class IterateRequest(BaseModel):
    factor_names: List[str]
    stock_pool: List[str]
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    label_period: int = Field(default=5, ge=1, le=60)
    max_iterations: int = Field(default=50, ge=1, le=500)
    target_sharpe: float = Field(default=2.0, ge=0)
    convergence_patience: int = Field(default=10, ge=1)
    initial_top_n: int = Field(default=30, ge=5)
    min_factors: int = Field(default=5, ge=2)


def _parse_date(s: str) -> date:
    s = s.replace("-", "")
    return date(int(s[:4]), int(s[4:6]), int(s[6:8]))


def _run_iterate(req: IterateRequest):
    global _running_engine, _is_running, _last_error
    with _running_lock:
        _last_error = None
    try:
        engine = AutoIterateEngine(
            all_factor_names=req.factor_names,
            stock_pool=req.stock_pool,
            train_start=_parse_date(req.train_start),
            train_end=_parse_date(req.train_end),
            test_start=_parse_date(req.test_start),
            test_end=_parse_date(req.test_end),
            label_period=req.label_period,
            initial_top_n=req.initial_top_n,
            min_factors=req.min_factors,
        )
        with _running_lock:
            _running_engine = engine

        engine.run(
            max_iterations=req.max_iterations,
            target_sharpe=req.target_sharpe,
            convergence_patience=req.convergence_patience,
        )

        try:
            from src.api.routers.webhook_router import notify_iterate_complete
            if engine.best_record:
                notify_iterate_complete(
                    engine.best_record.score,
                    engine.best_record.factor_names,
                    len(engine.history),
                )
        except Exception:
            pass

    except MemoryError:
        with _running_lock:
            _last_error = "内存不足 (OOM), 请减少 stock_pool 或 factor_names 数量"
        logger.error(_last_error)
    except Exception as e:
        with _running_lock:
            _last_error = f"{type(e).__name__}: {e}"
        logger.error(f"迭代异常: {_last_error}\n{traceback.format_exc()}")
    finally:
        with _running_lock:
            _is_running = False
        gc.collect()


@router.post("/start")
def start_iterate(req: IterateRequest, background_tasks: BackgroundTasks):
    """启动自动迭代 (后台运行)"""
    global _is_running
    with _running_lock:
        if _is_running:
            return {"status": "already_running"}
        _is_running = True

    background_tasks.add_task(_run_iterate, req)
    return {"status": "started", "max_iterations": req.max_iterations}


@router.post("/stop")
def stop_iterate():
    """请求停止当前迭代 (将在当前轮次结束后停止)"""
    global _is_running
    if not _is_running:
        raise HTTPException(404, "没有正在运行的迭代任务")
    _is_running = False
    return {"status": "stop_requested"}


@router.get("/status")
def iterate_status():
    """查询迭代进度"""
    if _running_engine is None:
        return {"status": "idle", "last_error": _last_error}

    history = _running_engine.history
    best = _running_engine.best_record

    return {
        "status": "running" if _is_running else "finished",
        "total_iterations": len(history),
        "best_score": best.score if best else None,
        "best_iteration": best.iteration if best else None,
        "best_factors": best.factor_names if best else [],
        "best_ic_mean": best.backtest_metrics.get("ic_mean") if best else None,
        "best_icir": best.backtest_metrics.get("icir") if best else None,
        "last_error": _last_error,
    }


@router.get("/convergence")
def convergence_curve():
    """获取收敛曲线数据"""
    if _running_engine is None:
        return []
    df = _running_engine.get_convergence_curve()
    return df.to_dict(orient="records") if not df.empty else []


@router.get("/factor-frequency")
def factor_frequency():
    """获取因子出现频率统计"""
    if _running_engine is None:
        return {}
    freq = _running_engine.get_factor_frequency()
    return freq.to_dict()


@router.get("/best")
def best_result():
    """获取最佳迭代结果"""
    if _running_engine is None or _running_engine.best_record is None:
        return {"status": "no_result"}
    return _running_engine.best_record.to_dict()
