"""模拟盘交易 Web 服务 (FastAPI)

提供 REST 接口 + 托管响应式前端 (电脑/手机浏览器)。

**与 QMT 终端/MCP 无任何依赖** —— 撮合、行情、选股均基于本地 PostgreSQL + 内存引擎。

多用户: 仅口令注册/登录 (默认用户 root/1234); 每个用户账户与成交流水按用户名隔离,
持久化在独立的 ``paper_*`` 表中, 绝不修改行情等真实业务表。
"""
from __future__ import annotations

import threading
from datetime import date
from pathlib import Path
from typing import Dict, Optional

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import text

from src.common.logger import get_logger
from src.webui.auth import AuthError, AuthManager, default_store
from src.webui.data_sync import get_data_sync_service
from src.webui.paper_engine import PaperAccount, _today_str
from src.webui.quotes import DayBarProvider, QuoteProvider
from src.webui.selection_service import get_selection_service
from src.selection.strategy import strategy_catalog

logger = get_logger(__name__)

_STATIC = Path(__file__).parent / "static"
_DEFAULT_CAPITAL = 1_000_000.0

_quotes = QuoteProvider(enable_live=False)
_bars = DayBarProvider()
_store = default_store()

_accounts: Dict[str, PaperAccount] = {}
_accounts_lock = threading.Lock()


def _get_account(username: str) -> PaperAccount:
    """按用户名获取 (或惰性创建) 账户实例, 进程内缓存。"""
    with _accounts_lock:
        acct = _accounts.get(username)
        if acct is None:
            acct = PaperAccount(
                name=username,
                initial_capital=_DEFAULT_CAPITAL,
                quote_provider=_quotes,
                bar_provider=_bars,
                store=_store,
            )
            _accounts[username] = acct
        return acct


_auth = AuthManager(_store, on_register=lambda u: _get_account(u))


def _settle_all_accounts() -> Dict[str, dict]:
    """同步完成后: 所有已加载账户推进到最新交易日并撮合。"""
    with _accounts_lock:
        items = list(_accounts.items())
    out: Dict[str, dict] = {}
    for name, acct in items:
        try:
            out[name] = acct.settle_to_latest()
        except Exception as e:  # noqa: BLE001
            logger.warning("账户 %s 结算失败: %s", name, e)
            out[name] = {"error": str(e)}
    return out


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------
class AuthReq(BaseModel):
    username: str
    password: str


class OrderReq(BaseModel):
    code: str
    direction: str          # buy / sell
    quantity: int
    price: float = 0.0
    price_type: str = "limit"  # limit / market


class CancelReq(BaseModel):
    order_id: str


class ManualQuoteReq(BaseModel):
    code: str
    price: float


class ResetReq(BaseModel):
    initial_capital: float | None = None


class TradeDateReq(BaseModel):
    date: str


class CapitalReq(BaseModel):
    cash: float


class DeleteTradeReq(BaseModel):
    trade_id: str


class SelectReq(BaseModel):
    kind: str = "stock"          # stock / etf
    strategy_id: str = "bull_launch"
    date: str | None = None      # 选股基准交易日, 缺省用账户当前交易日
    params: dict | None = None   # UI 覆盖参数


class PickItem(BaseModel):
    code: str
    price: float
    quantity: int


class PicksReq(BaseModel):
    kind: str = "stock"
    items: list[PickItem] = []
    screen_date: Optional[str] = None


class SyncKlineReq(BaseModel):
    days_back: int = 15
    concurrency: int = 4
    source: str = "qmt"


def create_app() -> FastAPI:
    app = FastAPI(title="QT 模拟盘交易终端", version="2.0.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _require_user(token: Optional[str]) -> str:
        username = _auth.resolve(token)
        if username is None:
            raise HTTPException(401, detail="未登录或会话已过期")
        return username

    # ------------------------------------------------------------------
    # 鉴权
    # ------------------------------------------------------------------
    @app.post("/api/register")
    def register(req: AuthReq):
        try:
            token = _auth.register(req.username, req.password)
        except AuthError as e:
            raise HTTPException(400, detail=str(e))
        return {"token": token, "username": req.username.strip()}

    @app.post("/api/login")
    def login(req: AuthReq):
        try:
            token = _auth.login(req.username, req.password)
        except AuthError as e:
            raise HTTPException(401, detail=str(e))
        return {"token": token, "username": req.username.strip()}

    @app.post("/api/logout")
    def logout(x_auth_token: Optional[str] = Header(None)):
        _auth.logout(x_auth_token or "")
        return {"ok": True}

    @app.get("/api/me")
    def me(x_auth_token: Optional[str] = Header(None)):
        username = _require_user(x_auth_token)
        return {"username": username}

    # ------------------------------------------------------------------
    # 账户 / 交易 (需登录)
    # ------------------------------------------------------------------
    @app.get("/api/state")
    def get_state(x_auth_token: Optional[str] = Header(None)):
        acct = _get_account(_require_user(x_auth_token))
        return acct.snapshot(refresh=True)

    @app.get("/api/quote")
    def get_quote(code: str):
        q = _quotes.get(code, force=True)
        if q is None:
            raise HTTPException(404, detail=f"无行情: {code}")
        return q.to_dict()

    @app.get("/api/fee_preview")
    def fee_preview(code: str, price: float, quantity: int, direction: str = "buy",
                    x_auth_token: Optional[str] = Header(None)):
        acct = _get_account(_require_user(x_auth_token))
        return acct.estimate_fees(code, price, quantity, direction)

    @app.post("/api/order")
    def place_order(req: OrderReq, x_auth_token: Optional[str] = Header(None)):
        acct = _get_account(_require_user(x_auth_token))
        if req.direction not in ("buy", "sell"):
            raise HTTPException(400, detail="direction 必须为 buy/sell")
        return acct.place_order(
            code=req.code,
            direction=req.direction,
            quantity=req.quantity,
            price=req.price,
            price_type=req.price_type,
        )

    @app.post("/api/cancel")
    def cancel_order(req: CancelReq, x_auth_token: Optional[str] = Header(None)):
        acct = _get_account(_require_user(x_auth_token))
        return {"ok": acct.cancel_order(req.order_id)}

    @app.post("/api/quote/manual")
    def set_manual_quote(req: ManualQuoteReq, x_auth_token: Optional[str] = Header(None)):
        acct = _get_account(_require_user(x_auth_token))
        q = _quotes.set_manual(req.code, req.price)
        acct.match_pending()
        return q.to_dict()

    @app.post("/api/reset")
    def reset(req: ResetReq, x_auth_token: Optional[str] = Header(None)):
        acct = _get_account(_require_user(x_auth_token))
        acct.reset(req.initial_capital)
        return {"ok": True}

    @app.post("/api/capital")
    def set_capital(req: CapitalReq, x_auth_token: Optional[str] = Header(None)):
        acct = _get_account(_require_user(x_auth_token))
        try:
            return acct.set_capital(req.cash)
        except ValueError as e:
            raise HTTPException(400, detail=str(e))

    @app.post("/api/trade/delete")
    def delete_trade(req: DeleteTradeReq, x_auth_token: Optional[str] = Header(None)):
        acct = _get_account(_require_user(x_auth_token))
        return {"ok": acct.delete_trade(req.trade_id)}

    # ------------------------------------------------------------------
    # 每日选股 / 选基 (需登录)
    # ------------------------------------------------------------------
    @app.get("/api/strategies")
    def strategies(x_auth_token: Optional[str] = Header(None)):
        _require_user(x_auth_token)
        return {"strategies": strategy_catalog()}

    @app.post("/api/select")
    def select(req: SelectReq, x_auth_token: Optional[str] = Header(None)):
        username = _require_user(x_auth_token)
        acct = _get_account(username)
        kind = req.kind if req.kind in ("stock", "etf") else "stock"
        d_str = req.date or acct.state.get("trade_date") or _today_str()
        try:
            d = date.fromisoformat(d_str)
        except ValueError:
            raise HTTPException(400, detail=f"日期无效: {d_str}")
        res = get_selection_service().start(username, kind, req.strategy_id, d, req.params or {})
        if not res.get("ok"):
            raise HTTPException(409, detail=res.get("detail", "任务启动失败"))
        return {"ok": True, "kind": kind, "date": d_str}

    @app.get("/api/select/status")
    def select_status(kind: str = "stock", x_auth_token: Optional[str] = Header(None)):
        username = _require_user(x_auth_token)
        return get_selection_service().status(username, kind)

    @app.get("/api/select/result")
    def select_result(kind: str = "stock", x_auth_token: Optional[str] = Header(None)):
        username = _require_user(x_auth_token)
        if kind not in ("stock", "etf"):
            kind = "stock"
        return get_selection_service().current(username, kind)

    @app.get("/api/select/history")
    def select_history(kind: str = "stock", x_auth_token: Optional[str] = Header(None)):
        username = _require_user(x_auth_token)
        if kind not in ("stock", "etf"):
            kind = "stock"
        from src.webui import selection_history as sh

        return {"kind": kind, "runs": sh.list_runs(username, kind)}

    @app.get("/api/select/history/{run_id}")
    def select_history_run(run_id: int, x_auth_token: Optional[str] = Header(None)):
        username = _require_user(x_auth_token)
        from src.webui import selection_history as sh

        run = sh.get_run(username, run_id)
        if not run:
            raise HTTPException(404, detail="选股记录不存在")
        return run

    @app.delete("/api/select/history/{run_id}")
    def delete_select_history(run_id: int, x_auth_token: Optional[str] = Header(None)):
        username = _require_user(x_auth_token)
        from src.webui import selection_history as sh

        if not sh.delete_run(username, run_id):
            raise HTTPException(404, detail="选股记录不存在")
        return {"ok": True, "run_id": run_id}

    @app.get("/api/select/inst-holders/status")
    def inst_holders_status(kind: str = "stock", x_auth_token: Optional[str] = Header(None)):
        username = _require_user(x_auth_token)
        from src.webui.inst_holders import get_inst_holder_fetch_service
        return get_inst_holder_fetch_service().status(username, kind)

    @app.get("/api/select/inst-holders")
    def inst_holders_result(kind: str = "stock", x_auth_token: Optional[str] = Header(None)):
        username = _require_user(x_auth_token)
        from src.webui.inst_holders import get_inst_holder_fetch_service
        return {"kind": kind, "items": get_inst_holder_fetch_service().result(username, kind)}

    @app.post("/api/picks/order")
    def picks_order(req: PicksReq, x_auth_token: Optional[str] = Header(None)):
        username = _require_user(x_auth_token)
        acct = _get_account(username)
        items = [it.model_dump() for it in req.items]
        screen_date = req.screen_date
        if not screen_date:
            cur = get_selection_service().current(username, req.kind)
            screen_date = cur.get("trade_date") if cur else None
        if not screen_date:
            screen_date = acct.state.get("trade_date")
        result = acct.place_picks(items, screen_date=screen_date)
        result["snapshot"] = acct.snapshot(refresh=False)
        return result

    @app.get("/api/search")
    def search(kw: str):
        kw = (kw or "").strip()
        if not kw:
            return []
        try:
            from src.common.db import get_session

            with get_session(readonly=True) as s:
                rows = s.execute(
                    text(
                        "SELECT code, name FROM stocks "
                        "WHERE code LIKE :kw OR name LIKE :kw ORDER BY code LIMIT 15"
                    ),
                    {"kw": f"%{kw}%"},
                ).fetchall()
            return [{"code": r[0], "name": r[1]} for r in rows]
        except Exception as e:  # noqa: BLE001
            logger.debug("search 失败: %s", e)
            return []

    # ------------------------------------------------------------------
    # 交易日 (按日回放, 需登录)
    # ------------------------------------------------------------------
    @app.get("/api/trade_date")
    def get_trade_date(x_auth_token: Optional[str] = Header(None)):
        acct = _get_account(_require_user(x_auth_token))
        return {
            "trade_date": acct.state.get("trade_date"),
            "calendar_today": _today_str(),
            "latest": _bars.latest_trading_day(),
        }

    @app.post("/api/trade_date")
    def set_trade_date(req: TradeDateReq, x_auth_token: Optional[str] = Header(None)):
        acct = _get_account(_require_user(x_auth_token))
        return acct.set_trade_date(req.date)

    @app.get("/api/trade_date/step")
    def step_trade_date(direction: str = "next", x_auth_token: Optional[str] = Header(None)):
        acct = _get_account(_require_user(x_auth_token))
        if direction not in ("prev", "next"):
            raise HTTPException(400, detail="direction 必须为 prev/next")
        cur = acct.state.get("trade_date") or _today_str()
        nxt = _bars.step_trading_day(cur, direction)
        if not nxt:
            raise HTTPException(404, detail="没有更多交易日")
        return acct.set_trade_date(nxt)

    @app.get("/api/calendar")
    def calendar(start: str, end: str):
        return {"days": _bars.trading_days(start, end)}

    # ------------------------------------------------------------------
    # 日 K 同步 + 挂单结算 (需登录)
    # ------------------------------------------------------------------
    @app.post("/api/sync/kline")
    def sync_kline(req: SyncKlineReq, x_auth_token: Optional[str] = Header(None)):
        _require_user(x_auth_token)
        svc = get_data_sync_service()
        res = svc.start(
            _settle_all_accounts,
            days_back=max(1, min(req.days_back, 365)),
            concurrency=max(1, min(req.concurrency, 16)),
            source=req.source if req.source in ("auto", "qmt", "eastmoney", "tencent") else "qmt",
        )
        if not res.get("ok"):
            raise HTTPException(409, detail=res.get("detail", "同步启动失败"))
        return {"ok": True}

    @app.get("/api/sync/status")
    def sync_status(x_auth_token: Optional[str] = Header(None)):
        username = _require_user(x_auth_token)
        st = get_data_sync_service().status()
        if not st.get("running") and st.get("settled"):
            mine = (st.get("settled") or {}).get(username)
            if mine:
                st = dict(st)
                st["user_settled"] = mine
        return st

    @app.get("/api/day_range")
    def day_range(code: str, date: str | None = None,
                  x_auth_token: Optional[str] = Header(None)):
        acct = _get_account(_require_user(x_auth_token))
        d = date or acct.state.get("trade_date") or _today_str()
        bar = _bars.get_bar(code, d)
        if bar is None:
            raise HTTPException(404, detail=f"无当日行情: {code} @ {d}")
        return bar.to_dict()

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.get("/")
    def index():
        idx = _STATIC / "index.html"
        if idx.exists():
            return FileResponse(idx)
        return JSONResponse({"error": "index.html not found"}, status_code=404)

    if _STATIC.exists():
        app.mount("/static", StaticFiles(directory=str(_STATIC)), name="static")

    return app


app = create_app()
