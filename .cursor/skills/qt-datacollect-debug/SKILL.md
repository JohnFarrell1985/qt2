---
name: qt-datacollect-debug
description: Debugs qt-quant data collection fallback chains, akshare/baostock/QMT sync failures, and DB completeness. Use when datacollect errors, akshare API breaks, missing K-line, fallback dispatcher, data_completeness, or source health checks.
---

# qt 数据采集排障

多源 fallback：`src/datacollect/data_sources.json` + `FallbackDispatcher`。

## 诊断顺序

```bash
python -m src.datacollect.dispatcher check
python -m src.data.data_completeness check
python -m src.data.data_completeness backfill
uv run python scripts/run_screen_audit.py --date YYYY-MM-DD
```

## Fallback 链

| data_type | 顺序 |
|---|---|
| stock_list | baostock → eastmoney → akshare → adata → tushare |
| daily_kline | xtquant → baostock → akshare → adata → tushare → pytdx |
| minute_kline | xtquant → pytdx → baostock |
| financial | xtquant → baostock → akshare → tushare → eastmoney |
| realtime | xtquant → akshare → adata → pytdx → eastmoney |

K 线 bulk（独立链路）：`kline_bulk_sync` = QMT → 东财 → 腾讯（东财熔断自动切腾讯）

## 同步命令

```bash
python -m src.data.akshare_sync stocks_full
python -m src.data.akshare_sync daily --days-back 30
python -m src.data.kline_bulk_sync stock --days-back 365 --source auto
python -m src.data.unified_collect --no-kline --categories universe,trading_calendar
uv run python scripts/run_scheduler.py   # 每日 16:30 增量
```

## 配置（env/.env.datacollect）

- `DATACOLLECT_AKSHARE_RATE=0.15`
- `DATACOLLECT_MAX_RETRIES`, `DATACOLLECT_REQUEST_TIMEOUT`
- `TUSHARE_TOKEN`, `QMT_PATH`

## 常见错误

| 错误 | 修复 |
|---|---|
| 所有数据源均失败 | `dispatcher check`；装缺失包 |
| 东财 connection reset / 429 | 等待；circuit 自动切腾讯 |
| xtquant 不可用 | 开 QMT；或 `--source eastmoney` |
| ST 名单加载失败 | `akshare_sync stocks_full` |
| trading_date 空 | `data_completeness backfill` |

## API 变更排查

1. `duckduckgo` MCP 搜「akshare 接口变更」
2. `fetch` MCP 打开 akshare 文档/公告页
3. 对照 `src/datacollect/collectors/akshare_collector.py` 函数名

## 关键文件

- `src/datacollect/dispatcher.py`, `health.py`
- `src/data/data_completeness.py`, `kline_bulk_sync.py`, `akshare_sync.py`
