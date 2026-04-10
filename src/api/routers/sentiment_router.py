"""情绪引擎 API 端点

/api/sentiment/latest - 获取最新情绪数据
/api/sentiment/{date} - 获取指定日期情绪数据
/api/sentiment/ingest - 触发情绪数据采集
/api/sentiment/history - 情绪历史列表
/api/sentiment/profiles - 策略参数 Profile
"""
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, Query

from src.api.deps import SessionDep
from src.common.logger import get_logger
from src.sentiment.models import SentimentDaily, SentimentIngestLog
from src.sentiment.price_volume import PriceVolumeCalculator
from src.sentiment.strategy_profiles import (
    load_profiles, get_strategy_config, list_active_strategies,
    reload_profiles,
)

logger = get_logger(__name__)
router = APIRouter(prefix="/api/sentiment", tags=["情绪引擎"])


@router.get("/latest")
def get_latest_sentiment(session: SessionDep):
    """获取最新一日情绪数据"""
    row = (
        session.query(SentimentDaily)
        .order_by(SentimentDaily.trade_date.desc())
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="暂无情绪数据")
    return row.to_dict()


@router.get("/date/{trade_date}")
def get_sentiment_by_date(trade_date: date, session: SessionDep):
    """获取指定日期情绪数据"""
    row = session.query(SentimentDaily).filter_by(trade_date=trade_date).first()
    if not row:
        raise HTTPException(status_code=404, detail=f"{trade_date} 无情绪数据")
    return row.to_dict()


@router.get("/history")
def get_sentiment_history(
    session: SessionDep,
    start_date: Optional[date] = Query(None, description="开始日期"),
    end_date: Optional[date] = Query(None, description="结束日期"),
    limit: int = Query(30, ge=1, le=365, description="返回条数"),
):
    """获取情绪历史数据"""
    query = session.query(SentimentDaily)
    if start_date:
        query = query.filter(SentimentDaily.trade_date >= start_date)
    if end_date:
        query = query.filter(SentimentDaily.trade_date <= end_date)
    rows = query.order_by(SentimentDaily.trade_date.desc()).limit(limit).all()
    return [r.to_dict() for r in rows]


@router.post("/ingest")
def trigger_ingest(session: SessionDep, trade_date: Optional[date] = None):
    """触发量价情绪数据采集 (Layer 1)

    从 stock_daily 表计算量价指标, 写入 sentiment_daily。
    """
    if trade_date is None:
        trade_date = date.today()

    calculator = PriceVolumeCalculator()
    indicators = calculator.calculate(trade_date)

    if not indicators:
        raise HTTPException(status_code=404, detail=f"{trade_date} 无行情数据, 无法计算")

    existing = session.query(SentimentDaily).filter_by(trade_date=trade_date).first()
    if existing:
        for key, value in indicators.items():
            setattr(existing, key, value)
        existing.updated_at = datetime.now()
    else:
        row = SentimentDaily(trade_date=trade_date, **indicators)
        session.add(row)

    log = SentimentIngestLog(
        trade_date=trade_date,
        source_name="price_volume",
        schedule_slot="manual",
        raw_data=indicators,
        cleaned_data=indicators,
        status="success",
        collected_at=datetime.now(),
    )
    session.add(log)

    logger.info(f"[情绪API] {trade_date} Layer 1 量价情绪已更新")
    return {
        "trade_date": trade_date.isoformat(),
        "status": "success",
        "indicators": indicators,
    }


@router.get("/ingest-log")
def get_ingest_log(
    session: SessionDep,
    trade_date: Optional[date] = None,
    limit: int = Query(20, ge=1, le=100),
):
    """查询采集日志"""
    query = session.query(SentimentIngestLog)
    if trade_date:
        query = query.filter(SentimentIngestLog.trade_date == trade_date)
    rows = (
        query.order_by(SentimentIngestLog.created_at.desc())
        .limit(limit)
        .all()
    )
    return [r.to_dict() for r in rows]


@router.get("/profiles")
def get_profiles():
    """获取策略参数 Profile 全量配置"""
    return load_profiles()


@router.get("/profiles/{strategy_name}/{macro_state}")
def get_profile_detail(strategy_name: str, macro_state: str):
    """获取指定策略在指定宏观状态下的参数"""
    config = get_strategy_config(strategy_name, macro_state)
    return {
        "strategy_name": strategy_name,
        "macro_state": macro_state,
        "config": config,
        "using_default": len(config) == 0,
    }


@router.get("/profiles/active/{macro_state}")
def get_active_strategies(macro_state: str):
    """列出指定宏观状态下活跃的策略"""
    strategies = list_active_strategies(macro_state)
    return {
        "macro_state": macro_state,
        "active_strategies": strategies,
        "count": len(strategies),
    }


@router.post("/profiles/reload")
def reload_strategy_profiles():
    """重新加载策略参数 Profile (热更新)"""
    profiles = reload_profiles()
    return {
        "status": "reloaded",
        "strategies_count": len(profiles),
    }
