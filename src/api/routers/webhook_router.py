"""Webhook 推送模块

主动推送事件到 OpenClaw/飞书:
- 风控告警 (止损/止盈/日亏损)
- 迭代完成通知
- 数据同步异常

使用 httpx 连接池复用 TCP 连接, 带重试和超时保护。
"""
from datetime import datetime
from typing import Dict, Any

import httpx
from fastapi import APIRouter

from src.common.logger import get_logger
from src.common.config import settings

logger = get_logger(__name__)
router = APIRouter(prefix="/webhook", tags=["Webhook推送"])

OPENCLAW_WEBHOOK_URL = settings.webhook.openclaw_url

_wh = settings.webhook
_TIMEOUT = httpx.Timeout(
    connect=_wh.http_connect_timeout,
    read=_wh.http_read_timeout,
    write=_wh.http_connect_timeout,
    pool=_wh.http_connect_timeout,
)
_LIMITS = httpx.Limits(
    max_connections=_wh.max_connections,
    max_keepalive_connections=max(1, _wh.max_connections // 2),
)
_sync_client: httpx.Client = None
_MAX_RETRIES = _wh.max_retries


def _get_sync_client() -> httpx.Client:
    global _sync_client
    if _sync_client is None or _sync_client.is_closed:
        _sync_client = httpx.Client(timeout=_TIMEOUT, limits=_LIMITS)
    return _sync_client


def configure_webhook(url: str) -> None:
    """配置 OpenClaw webhook URL (运行时动态修改)"""
    global OPENCLAW_WEBHOOK_URL
    OPENCLAW_WEBHOOK_URL = url
    logger.info(f"Webhook 已配置: {url}")


def _build_payload(event_type: str, data: Dict[str, Any]) -> dict:
    return {
        "source": "qt-quant",
        "event_type": event_type,
        "timestamp": datetime.now().isoformat(),
        "data": data,
    }


async def push_event(event_type: str, data: Dict[str, Any]) -> bool:
    """异步推送事件到 OpenClaw"""
    if not OPENCLAW_WEBHOOK_URL:
        logger.debug(f"Webhook 未配置, 跳过推送: {event_type}")
        return False

    payload = _build_payload(event_type, data)
    for attempt in range(1, _MAX_RETRIES + 2):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, limits=_LIMITS) as client:
                resp = await client.post(OPENCLAW_WEBHOOK_URL, json=payload)
                if resp.status_code == 200:
                    logger.info(f"Webhook 推送成功: {event_type}")
                    return True
                logger.warning(f"Webhook 推送失败: HTTP {resp.status_code} (第{attempt}次)")
        except Exception as e:
            logger.warning(f"Webhook 推送异常 (第{attempt}次): {e}")
        if attempt <= _MAX_RETRIES:
            import asyncio
            await asyncio.sleep(attempt * 0.5)
    return False


def push_event_sync(event_type: str, data: Dict[str, Any]) -> bool:
    """同步推送 (用于非 async 上下文), 带重试"""
    if not OPENCLAW_WEBHOOK_URL:
        return False

    payload = _build_payload(event_type, data)
    client = _get_sync_client()
    for attempt in range(1, _MAX_RETRIES + 2):
        try:
            resp = client.post(OPENCLAW_WEBHOOK_URL, json=payload)
            if resp.status_code == 200:
                return True
            logger.warning(f"Webhook 同步推送失败: HTTP {resp.status_code} (第{attempt}次)")
        except Exception as e:
            logger.warning(f"Webhook 同步推送异常 (第{attempt}次): {e}")
        if attempt <= _MAX_RETRIES:
            import time
            time.sleep(attempt * 0.5)
    return False


# ---- API 端点 ----

@router.post("/configure")
def configure(url: str):
    """配置 OpenClaw webhook URL"""
    configure_webhook(url)
    return {"status": "configured", "url": url}


@router.get("/config")
def get_config():
    """查看当前 webhook 配置"""
    return {"url": OPENCLAW_WEBHOOK_URL, "configured": bool(OPENCLAW_WEBHOOK_URL)}


@router.post("/test")
async def test_push():
    """测试推送"""
    ok = await push_event("test", {"message": "qt-quant webhook test"})
    return {"pushed": ok}


# ---- 预定义事件推送函数 ----

def notify_stop_loss(code: str, loss_pct: float, order_id: int = 0) -> None:
    push_event_sync("risk_stop_loss", {
        "code": code,
        "loss_pct": round(loss_pct, 2),
        "order_id": order_id,
        "message": f"[止损] {code} 浮亏 {loss_pct:.2f}%, 已触发止损卖出",
    })


def notify_take_profit(code: str, profit_pct: float, order_id: int = 0) -> None:
    push_event_sync("risk_take_profit", {
        "code": code,
        "profit_pct": round(profit_pct, 2),
        "order_id": order_id,
        "message": f"[止盈] {code} 浮盈 {profit_pct:.2f}%, 已触发止盈卖出",
    })


def notify_daily_loss_limit(loss_pct: float) -> None:
    push_event_sync("risk_daily_loss", {
        "loss_pct": round(loss_pct, 2),
        "message": f"[风控] 日内亏损 {loss_pct:.2f}%, 已停止交易",
    })


def notify_iterate_complete(best_score: float, best_factors: list, total_iterations: int) -> None:
    push_event_sync("iterate_complete", {
        "best_score": round(best_score, 4),
        "best_factors": best_factors,
        "total_iterations": total_iterations,
        "message": f"[迭代完成] {total_iterations}轮, 最佳评分={best_score:.4f}, {len(best_factors)}因子",
    })


def notify_sync_error(sync_type: str, error: str) -> None:
    push_event_sync("sync_error", {
        "sync_type": sync_type,
        "error": error,
        "message": f"[同步异常] {sync_type}: {error}",
    })
