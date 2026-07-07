# 配置文件 (JSON)

| 文件 | 说明 |
|------|------|
| `app.json` | 全局：回测、调度、风控、`selection.active_strategy` |
| `strategies/bull_launch.json` | **牛市启动突破** — 短均线发散 + 贴 MA5 |
| `strategies/bear_rebound.json` | **熊市反弹** — 20~60 发散 + 贴 MA20 |

手动切换：修改 `app.json` 中 `selection.active_strategy` 为 `bull_launch` 或 `bear_rebound`，或在 CLI 加 `--strategy bear_rebound`。

优先级：环境变量 `SELECTION_STRATEGY` > CLI `--strategy` > `app.json` > 代码默认。
