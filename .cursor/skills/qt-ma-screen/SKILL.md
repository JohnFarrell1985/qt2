---
name: qt-ma-screen
description: Runs and debugs qt-quant MA stock screening (bull_launch/bear_rebound). Use when screening stocks, ma_screener, universe, ST filter, limit-up, funnel audit, candidates JSON/CSV, or SELECTION_STRATEGY.
---

# qt MA 选股

v4 流程：PostgreSQL `stock_daily` → `ma_screener` → `reports/candidates_*.json`。无 LLM/RAG。

## 命令

```bash
python -m src.selection screen --date 2026-07-07
python -m src.selection screen --date 2026-07-07 --strategy bear_rebound --csv
uv run python scripts/run_screen_audit.py --date 2026-07-07 --rank-dist
python scripts/diag_strategy_funnel.py
```

## 策略切换优先级

CLI `--strategy` > `SELECTION_STRATEGY` > `config/app.json` → `selection.active_strategy` > `bull_launch`

| 项 | bull_launch | bear_rebound |
|---|---|---|
| anchor MA | MA5 | MA20 |
| require_spreading | true | false |
| filter_periods | 5,10,20,50 | 20,30,40,50,60 |
| rank.export_top_n | 40 | 50 |

Preset：`config/strategies/{bull_launch,bear_rebound}.json`

## 筛选漏斗

1. Universe（`all_a` PIT / `universe_file`）
2. ST 排除（`exclude_st`）
3. K 线（仅 PostgreSQL `stock_daily`，无 QMT 回退）
4. 可交易性（停牌/一字/跌停硬排除；涨停默认扣分不排除）
5. MA 发散 → 前期放量 → 最大涨幅 → 缩量回踩锚线 → 流动性
6. 综合评分 tier A/B/C，上限 `max_candidates`（200）

## 输出

- JSON：`reports/candidates_{strategy}_{YYYYMMDD}.json`
- 字段：`candidates`, `export_shortlist`, `ma_snapshots`（含 `composite_score`, `tier`, `ma5_dist_pct`）
- CSV（`--csv`）：`code, composite_score, tier, close, ma5_dist_pct, avg_turnover_20d`

## 前置检查

```bash
python -m src.data.akshare_sync stocks_full    # ST 名单
python -m src.data.kline_bulk_sync stock --days-back 365 --source auto
```

## 常见问题

| 现象 | 处理 |
|---|---|
| 候选为空 | `run_screen_audit.py --audit` 看漏斗 |
| ST 未过滤 | 跑 `stocks_full` |
| 无 K 线 | `kline_bulk_sync stock` |
| Universe 空 | `stock_list_sync` / `akshare_sync stocks_full` |

## 关键文件

- `src/selection/ma_screener.py`, `workflow.py`
- `src/data/st_filter.py`, `limit_status.py`, `universe_manager.py`
- `src/common/config.py`（`MaFilterConfig`, `RankConfig`）

## MCP 辅助

- `postgres`：查 `stock_daily` 覆盖、`stocks` 表
- `ashare` / `china-stock`：对比实时行情
