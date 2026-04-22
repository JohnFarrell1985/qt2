# OpenClaw / qt 技能使用说明

本工作区为 **OpenClaw 工作区根** 的仓库镜像。技能主目录为 **`workspace/skills/`**（Vibe-Trading 同步，见上级 `../README.md`），用于向 Agent 提供**方法论与流程**；**可执行回测、下单、数据主路径**在 **qt 根目录的 `src/`** 中实现。

## 工具映射（读 skills 时必看）

| Vibe-Trading 技能中可能出现的调用 | 在 qt 中应使用 |
|----------------------------------|----------------|
| `factor_analysis`（Vibe 工具 / MCP） | `src/factor/`、`src/backtest/` 中的因子与回测管道；或内部 API、脚本 |
| `run_backtest` / `backtest`（Vibe 运行目录） | `src/backtest/`，与 Orchestrator/策略层约定一致 |
| `get_market_data` / Tushare 仅作示例 | `src/datacollect/`、`src/data/`，QMT/迅投 以 **xtdata / 项目内封装** 为准 |
| 交易流水、Shadow 分析 | 若实现：用 qt 的持仓/成交数据或导出文件 + 自研/外部脚本，勿假定存在 Vibe 全局目录 |

- **A 股规则**（T+1、涨跌停、PIT 等）以 `doc/` 与 `src/` 实现及监管为准；skills 中境外市场描述仅作阅读参考。

## 语言

- 与 qt 主项目一致：对用户的解释与操作说明优先使用 **中文**；skills 原文多为英文/中英混合，**不得**在未核对的情况下当作合规或交易建议。

## 与 OpenClaw 的对应关系

- **`workspace/skills/`**：与官方文档中 **workspace 根下的 `skills/`** 一致，优先级最高；本仓库中为由脚本同步的 Vibe-Trading 技能包。
- **`workspace/.agents/skills/`**：与官方 **「Project agent skills」** 位置一致，用于你自行放置**覆盖/补丁**型技能（同名将按 OpenClaw 的 precedence 与 `workspace/skills` 协同，具体以你 Gateway 版本为准）。默认可为空。
