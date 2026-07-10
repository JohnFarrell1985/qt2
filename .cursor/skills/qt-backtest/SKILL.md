---
name: qt-backtest
description: Runs qt-quant backtests from MA screening JSON via CachedPicker and strategy_runner. Use when backtest, run_backtest.py, CachedPicker, performance metrics, Sharpe, drawdown, or validating selection lists.
---

# qt 回测

入口：`scripts/run_backtest.py`。默认 **连续持仓** 模式（`run_continuous`）。

## 命令

```bash
python scripts/run_backtest.py --picks-file reports/candidates_bull_launch_20260707.json
python scripts/run_backtest.py --picks-dir reports --start 2025-01-01 --end 2025-06-30 --capital 1000000
python scripts/run_backtest.py --screen --start 2025-01-01 --end 2025-06-30   # 慢，每日重筛 top5
```

## 工作流

1. 先跑选股 → `reports/candidates_{strategy}_{date}.json`
2. 确认 `trading_date` + `stock_daily` 覆盖回测区间
3. `run_backtest.py --picks-file` 或 `--picks-dir`
4. 看 `StrategyResult` + `full_performance_report`

## CachedPicker

- 读 `candidates_*.json`，按 `trade_date` 映射 `candidates`
- `confidence` = `ma_snapshots[code].composite_score`
- 兼容旧格式 `final_picks`

## 策略参数（StrategyConfig）

| 参数 | 默认 |
|---|---|
| initial_capital | 1,000,000 |
| max_position_pct | 30% |
| max_total_position_pct | 80% |
| max_holdings | 5（run_backtest 硬编码） |
| limit_up_threshold | 9.8%（开盘跳过买入） |

仓位：`int(budget / price / 100) * 100`（100 股整数倍）

## 手续费（fees.py / FEE_*）

- 佣金：万 1.15，最低 ¥5
- 印花税（卖）：千 0.5
- 过户费（沪）：万 0.02

## 绩效指标

`StrategyResult`：total_return_pct, annualized_return_pct, win_rate, max_drawdown, total_fees

`full_performance_report`：sharpe, sortino, calmar, profit_loss_ratio, monthly_heatmap

## 跳过原因

- 开盘涨停（≥9.8%）
- 无 OHLC
- 资金不足 / 不足 1 手

## 关键文件

- `src/backtest/strategy_runner.py`, `stock_picker.py`, `fees.py`, `performance.py`

## MCP 辅助

- `postgres`：验证回测区间 K 线完整性
