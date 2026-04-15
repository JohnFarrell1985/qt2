"""数据查询与同步触发 API

提供股票、行情、指数、财务、板块、日历等数据的查询接口,
以及手动触发数据同步的操作接口。
"""
from typing import Optional

from fastapi import APIRouter, Query, HTTPException, BackgroundTasks

from src.api.deps import SessionDep
from src.common.logger import get_logger
from src.data.models import (
    Stock, StockDaily, StockMinute, MarketIndex,
    StockFinancialReport, StockFinancialIndicator,
    IndexWeight,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/api/data", tags=["数据查询"])


# ================================================================
# 股票
# ================================================================

@router.get("/stocks", summary="获取股票列表")
def list_stocks(
    session: SessionDep,
    exchange: Optional[str] = Query(None, description="交易所: SH/SZ/BJ"),
    industry: Optional[str] = Query(None, description="所属行业"),
    keyword: Optional[str] = Query(None, description="代码或名称模糊搜索"),
    limit: int = Query(default=100, le=5000),
    offset: int = 0,
):
    q = session.query(Stock)
    if exchange:
        q = q.filter(Stock.exchange == exchange)
    if industry:
        q = q.filter(Stock.industry == industry)
    if keyword:
        q = q.filter(
            (Stock.code.contains(keyword)) | (Stock.name.contains(keyword))
        )
    stocks = q.offset(offset).limit(limit).all()
    return {"total": q.count(), "items": [s.to_dict() for s in stocks]}


@router.get("/stock/{code}/info", summary="股票基本信息")
def get_stock_info(code: str, session: SessionDep):
    stock = session.query(Stock).filter_by(code=code).first()
    if not stock:
        raise HTTPException(status_code=404, detail=f"股票 {code} 不存在")
    return stock.to_dict()


# ================================================================
# 行情 — 日线
# ================================================================

@router.get("/stock/{code}/daily", summary="股票日线行情")
def get_stock_daily(
    code: str,
    session: SessionDep,
    start_date: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    limit: int = Query(default=60, le=2000),
):
    q = session.query(StockDaily).filter(StockDaily.code == code)
    if start_date:
        q = q.filter(StockDaily.trade_date >= start_date)
    if end_date:
        q = q.filter(StockDaily.trade_date <= end_date)
    rows = q.order_by(StockDaily.trade_date.desc()).limit(limit).all()
    return [r.to_dict() for r in rows]


# ================================================================
# 行情 — 分钟线
# ================================================================

@router.get("/stock/{code}/minute", summary="股票分钟线行情")
def get_stock_minute(
    code: str,
    session: SessionDep,
    period: str = Query(default="5m", description="周期: 1m/5m/15m/30m/1h"),
    start_date: Optional[str] = Query(None, description="起始日期 YYYY-MM-DD"),
    end_date: Optional[str] = Query(None, description="结束日期 YYYY-MM-DD"),
    limit: int = Query(default=200, le=5000),
):
    q = session.query(StockMinute).filter(
        StockMinute.code == code,
        StockMinute.period == period,
    )
    if start_date:
        q = q.filter(StockMinute.trade_time >= start_date)
    if end_date:
        q = q.filter(StockMinute.trade_time <= end_date + " 23:59:59")
    rows = q.order_by(StockMinute.trade_time.desc()).limit(limit).all()
    return [{
        "code": r.code,
        "trade_time": r.trade_time.isoformat() if r.trade_time else None,
        "period": r.period,
        "open": r.open, "high": r.high, "low": r.low, "close": r.close,
        "volume": r.volume, "amount": r.amount,
    } for r in rows]


# ================================================================
# 指数数据
# ================================================================

@router.get("/indices", summary="可用指数列表")
def list_indices(session: SessionDep):
    from sqlalchemy import func
    rows = session.query(
        MarketIndex.index_code,
        MarketIndex.index_name,
        func.count(MarketIndex.id).label("data_points"),
    ).group_by(MarketIndex.index_code, MarketIndex.index_name).all()
    return [{"index_code": r[0], "index_name": r[1], "data_points": r[2]} for r in rows]


@router.get("/index/{index_code}/daily", summary="指数日线行情")
def get_index_daily(
    index_code: str,
    session: SessionDep,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    limit: int = Query(default=60, le=2000),
):
    q = session.query(MarketIndex).filter(MarketIndex.index_code == index_code)
    if start_date:
        q = q.filter(MarketIndex.trade_date >= start_date)
    if end_date:
        q = q.filter(MarketIndex.trade_date <= end_date)
    rows = q.order_by(MarketIndex.trade_date.desc()).limit(limit).all()
    if not rows:
        raise HTTPException(404, f"指数 {index_code} 无数据")
    return [{
        "index_code": r.index_code, "index_name": r.index_name,
        "trade_date": r.trade_date.isoformat() if r.trade_date else None,
        "open": r.open, "high": r.high, "low": r.low, "close": r.close,
        "volume": r.volume, "amount": r.amount,
    } for r in rows]


# ================================================================
# 财务数据
# ================================================================

@router.get("/stock/{code}/financial/report", summary="财务报表数据")
def get_financial_report(
    code: str,
    session: SessionDep,
    limit: int = Query(default=20, le=200),
):
    rows = (
        session.query(StockFinancialReport)
        .filter(StockFinancialReport.code == code)
        .order_by(StockFinancialReport.report_date.desc())
        .limit(limit)
        .all()
    )
    return [{
        "code": r.code, "report_date": r.report_date.isoformat() if r.report_date else None,
        "total_assets": r.total_assets, "total_liabilities": r.total_liabilities,
        "total_equity": r.total_equity, "total_revenue": r.total_revenue,
        "net_profit": r.net_profit, "operating_cash_flow": r.operating_cash_flow,
    } for r in rows]


@router.get("/stock/{code}/financial/indicator", summary="财务指标数据")
def get_financial_indicator(
    code: str,
    session: SessionDep,
    limit: int = Query(default=20, le=200),
):
    rows = (
        session.query(StockFinancialIndicator)
        .filter(StockFinancialIndicator.code == code)
        .order_by(StockFinancialIndicator.report_date.desc())
        .limit(limit)
        .all()
    )
    return [{
        "code": r.code, "report_date": r.report_date.isoformat() if r.report_date else None,
        "eps_basic": r.eps_basic, "bps": r.bps,
        "roe_weighted": r.roe_weighted,
        "net_profit_margin": r.net_profit_margin,
        "gross_profit_margin": r.gross_profit_margin,
    } for r in rows]


# ================================================================
# 指数权重
# ================================================================

@router.get("/index/{index_code}/weight", summary="指数成分权重")
def get_index_weight(
    index_code: str,
    session: SessionDep,
    limit: int = Query(default=500, le=2000),
):
    rows = (
        session.query(IndexWeight)
        .filter(IndexWeight.index_code == index_code)
        .order_by(IndexWeight.weight.desc())
        .limit(limit)
        .all()
    )
    return [{
        "index_code": r.index_code,
        "stock_code": r.stock_code,
        "weight": r.weight,
    } for r in rows]


# ================================================================
# 同步操作
# ================================================================

@router.post("/sync/full", summary="触发全量数据同步 (后台执行)")
def trigger_full_sync(
    background_tasks: BackgroundTasks,
    start_date: str = Query(default="", description="起始日期yyyymmdd, 空=按周期使用默认值"),
    end_date: str = Query(default=""),
    sync_minute: bool = Query(default=False, description="是否同步分钟线"),
    minute_periods: str = Query(default="5m", description="分钟周期, 逗号分隔: 1m,5m,15m"),
    incremental: bool = Query(default=True, description="增量续传(推荐) / 全量重下"),
):
    mp_list = [p.strip() for p in minute_periods.split(",") if p.strip()]
    background_tasks.add_task(
        _run_full_sync, start_date, end_date, sync_minute, mp_list, incremental,
    )
    return {
        "status": "started",
        "message": "全量同步已在后台启动",
        "config": {
            "start_date": start_date or "(各周期默认值)",
            "incremental": incremental,
            "sync_minute": sync_minute,
            "minute_periods": mp_list,
        },
    }


@router.post("/sync/incremental", summary="触发增量数据同步 (后台执行)")
def trigger_incremental_sync(
    background_tasks: BackgroundTasks,
    days_back: int = Query(default=5, ge=1, le=30),
):
    background_tasks.add_task(_run_incremental_sync, days_back)
    return {"status": "started", "message": f"增量同步(最近{days_back}天)已在后台启动"}


def _run_full_sync(
    start_date: str, end_date: str, sync_minute: bool,
    minute_periods: list, incremental: bool,
):
    try:
        from src.data.sync import DataSyncManager
        mgr = DataSyncManager()
        result = mgr.full_sync(
            start_date, end_date,
            sync_minute=sync_minute,
            minute_periods=minute_periods,
            incremental=incremental,
        )
        logger.info(f"后台全量同步完成: {result}")
    except Exception as e:
        logger.error(f"后台全量同步失败: {e}", exc_info=True)


def _run_incremental_sync(days_back: int):
    try:
        from src.data.sync import DataSyncManager
        mgr = DataSyncManager()
        result = mgr.incremental_sync(days_back)
        logger.info(f"后台增量同步完成: {result}")
    except Exception as e:
        logger.error(f"后台增量同步失败: {e}", exc_info=True)
