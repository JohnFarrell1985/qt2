# qt-quant — MA 程序选股 + QMT 交易

精简版 A 股量化系统：程序计算多周期均线并初筛，输出选股清单；支持回测与 QMT 模拟/实盘执行。

## 架构

```
数据采集 (datacollect + data) → PostgreSQL (stock_daily)
        ↓
MA 程序选股 (src/selection/ma_screener)
        ↓
选股清单 JSON/CSV (reports/candidates_*.json)
        ↓
回测 (strategy_runner + CachedPicker) / QMT 交易 (paper/live)
```

## 快速开始

```bash
# 安装依赖
uv sync

# 配置环境变量 (DB、QMT)
cp env/.env.example env/.env.db
# ... 编辑 env/.env.* ...

# 每日选股
python -m src.selection screen --date 2026-07-07 --csv

# 回测 (使用缓存清单)
python scripts/run_backtest.py --picks-file reports/candidates_bull_launch_20260707.json

# QMT 模拟盘执行
python -m src.trading execute --picks reports/candidates_bull_launch_20260707.json --mode paper
```

## 配置

全局参数见 [`config/app.json`](config/app.json)，选股策略 preset 见 [`config/strategies/`](config/strategies/)：

| 策略 ID | 文件 | 说明 |
|---------|------|------|
| `bull_launch` | `bull_launch.json` | 牛市启动突破 — 短均线发散 + 贴 MA5 |
| `bear_rebound` | `bear_rebound.json` | 熊市反弹 — 长均线上行 + 贴 MA20 |

切换方式：改 `app.json` 的 `selection.active_strategy`，或 CLI `--strategy bear_rebound`，或环境变量 `SELECTION_STRATEGY`。

密钥从 `env/.env.*` 读取：`DATABASE_URL`、`QMT_PATH` 等。

## 核心模块

| 模块 | 路径 | 说明 |
|------|------|------|
| 公共基础 | `src/common/` | 配置 / DB / 日志 |
| 数据落盘 | `src/data/` | QMT 同步、K 线 bulk 写入 |
| 外部采集 | `src/datacollect/` | 多源 K 线 fallback |
| 选股 | `src/selection/` | MA 初筛 CLI |
| 回测 | `src/backtest/` | strategy_runner + CachedPicker |
| 交易 | `src/trading/` | QMT 模拟/实盘 |

## 文档

详见 [`doc/README.md`](doc/README.md)（**[用户手册](doc/07-用户手册.md)** · 00 总体设计 → 06 模拟盘 UI）。

## 定时同步

```bash
uv run python scripts/run_scheduler.py   # 本地常驻，每日 16:30 增量同步 K 线
```
