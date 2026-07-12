---
name: qt-a-share-rules
description: Applies A-share trading rules for qt-quant: T+1, limit up/down by board, 100-share lots, paper vs live QMT, risk limits. Use when trading logic, risk control, QMT execute, limit-up filter, or validating strategy compliance.
---

# A 股交易规则（qt-quant）

编码位置：`limit_status.py`, `strategy_runner.py`, `risk_control.py`, `trading/`.

## T+1

- 选股信号：T 日收盘后
- 回测执行：T+1 开盘买卖（`get_next_trading_date`）
- 所有「天数」= **交易日**，非自然日
- 跨境 ETF（513*/159920）T+0；普通 A 股 T+1

## 涨跌停阈值

| 板块 | 阈值 |
|---|---|
| 主板 6/0/3/2/9 | 10% |
| 科创板 688 / 创业板 300 | 20% |
| ST | 5%（名称识别） |

**选股**：停牌/一字/跌停硬排除；涨停默认扣分（`exclude_limit_up: true` 才硬排除）

**回测买入**：开盘较昨收 ≥ `limit_up_threshold`（默认 9.8%）跳过

## 最小交易单位

- **100 股整数倍** everywhere
- 回测最小单笔预算 ¥1000

## Paper vs Live

```bash
python -m src.trading execute --picks reports/candidates_bull_launch_20260707.json --mode paper
python -m src.trading execute --picks reports/candidates_bull_launch_20260707.json --mode live
```

| | Paper | Live |
|---|---|---|
| 默认 | `TRADING_PAPER_MODE=true` | 需 `confirm_live_mode()` |
| 引擎 | `PaperTradingEngine` | `LiveTradingEngine` |
| 共用 | `QMTTrader`, `RiskController` | 同左 |

信号格式：`[{"code": "600519", "signal": "buy", "rank": 1}, ...]`

## 风控（config/app.json → risk）

| 参数 | 默认 | Env |
|---|---|---|
| stop_loss_pct | -8.0% | `RISK_STOP_LOSS_PCT` |
| take_profit_pct | 20.0% | `RISK_TAKE_PROFIT_PCT` |
| max_single_position_pct | 30% | `RISK_MAX_SINGLE_POSITION_PCT` |
| max_total_position_pct | 80% | `RISK_MAX_TOTAL_POSITION_PCT` |
| max_daily_loss_pct | -5.0% | `RISK_MAX_DAILY_LOSS_PCT` |

`RiskController`：止损/止盈/单票仓位/总仓位/日亏损熔断

## QMT-MCP

- Cursor 打开工作区后，`qmt-mcp` 通过 `.cursor/mcp.json` **自启动**（stdio；入口 `~/.local/mcp/QMT-MCP/run_stdio_mcp.py`，command 用绝对路径，Cursor 不展开 `${userHome}`）
- 先开 Mini QMT 客户端并登录，交易/行情工具才能连上 XTQuant
- 调试 SSE 模式（可选）：`.\.cursor\scripts\start-qmt-mcp.ps1`

## PIT 原则

历史回测/选股用 `UniverseManager.get_tradable(trade_date)`，不用今日全量列表。

## 端到端

```
16:30 K线同步 → screen → 审 JSON tier → backtest → paper → (可选) live
```
