# A股量化因子迭代平台 v5.0

基于 **三档策略引擎** + **完整买卖体系** + **持仓监控 / 信号仲裁 / 仓位分配** + **迅投 QMT** 数据交易的散户量化投资系统。

## 架构

```
用户 / 飞书机器人 / OpenClaw
         │
    FastAPI (Swagger /docs)
         │
┌────────┼────────┬──────────┬───────────────────┐
│ 数据层 │ 因子工程 │ 机器学习  │ 三档策略引擎        │
│ QMT   │ IC/IR  │ LightGBM │ Rule/Scoring/ML   │
│ 可转债 │        │ XGBoost* │ 10 个策略类         │
│ ETF   │        │ CatBoost*│ 买入 + 卖出信号     │
├────────┴────────┼──────────┴───────────────────┤
│   PositionMonitor  │  SignalArbiter             │
│   持仓监控 (止损/止盈)│  信号仲裁 (去重/T+1)       │
├─────────────────┼──────────────────────────────┤
│   PositionSizer    │  StrategyOrchestrator      │
│   仓位分配 (等权/ATR) │  编排器 (操作清单输出)       │
├─────────────────┴──────────────────────────────┤
│   回测引擎       │    交易执行 (模拟/实盘)         │
├─────────────────┴──────────────────────────────┤
│   PostgreSQL  │  迅投 QMT/MiniQMT               │
└───────────────┴────────────────────────────────┘
                                     * = 预留接口
```

## v5.0 新增: 散户实战体系

| 组件 | 职责 |
|------|------|
| PositionMonitor | 扫描持仓 → 触发止损/止盈/移动止损/超期清仓 |
| SignalArbiter | 多策略信号去重、冲突解决、T+1 校验、投票加分 |
| PositionSizer | 等权/ATR反比/凯利公式 仓位分配, 100股整手 |
| 全策略卖出信号 | 每个策略同时生成买入和卖出信号 (条件失效卖出) |
| T+1 宽网格 | 网格策略适配 A 股 T+1 (隔日卖出) |
| 散户配置 | 止损 -8%、止盈 15%、最大持仓 5 只、单票 20% |

### 完整执行流程

```
策略信号生成 → 持仓监控扫描 → 信号仲裁 → 仓位分配 → 操作清单
                                ↑ T+1 校验
                                ↑ 流动性过滤
                                ↑ 持仓感知 (不重复买/不空卖)
```

## 三档策略

| 档位 | 类型 | 策略 | 卖出逻辑 |
|------|------|------|----------|
| Tier 1 | 规则 | 双低可转债 | 双低值升高不再满足 |
| Tier 1 | 规则 | 动量 | 动量反转 (收益率翻负) |
| Tier 1 | 规则 | 反转 | 反弹目标达成 (>5%) |
| Tier 1 | 规则 | 行业轮动 | 行业排名跌出 Top N |
| Tier 1 | 规则 | 均线突破 | 死叉 (短均下穿长均) |
| Tier 1 | 规则 | T+1 宽网格 | 价格触及网格上沿 |
| Tier 1 | 规则 | 低波红利 | 波动率飙升 |
| Tier 2 | 打分 | 多因子等权/IC加权 | 因子排名下滑至后 30% |
| Tier 3 | ML | LightGBM/XGBoost*/CatBoost* | 模型预测收益低于阈值 |

## 模块

| 模块 | 路径 | 说明 |
|------|------|------|
| 公共 | `src/common/` | 配置、日志、数据库 |
| 数据 | `src/data/` | QMT 数据对接、可转债/ETF、400+ 因子同步 |
| 因子 | `src/factor/` | 因子计算、预处理、IC/IR 分析 |
| ML | `src/ml/` | LightGBM 训练、自动迭代优化 |
| 策略 | `src/strategy/` | 三档策略引擎、标的池、宏观环境编排 |
| 买卖体系 | `src/strategy/` | PositionMonitor、SignalArbiter、PositionSizer |
| 回测 | `src/backtest/` | 日线/分钟线回测、绩效统计 |
| 交易 | `src/trading/` | 模拟盘/实盘、风控 |
| API | `src/api/` | FastAPI 服务、Swagger 文档 |

## 快速开始

```bash
# 安装 (使用 uv)
uv sync

# 初始化数据库
uv run python scripts/init_db.py

# 启动 API 服务
uv run uvicorn src.api.main:app --host 0.0.0.0 --port 8012

# 访问 Swagger 文档
open http://localhost:8012/docs
```

## 核心 API

```bash
# 完整执行: 输入持仓和资金 → 输出今日操作清单
POST /api/strategy/execute
{
  "total_capital": 1000000,
  "available_cash": 500000,
  "holdings": [
    {"code": "000001.SZ", "buy_price": 10.0, "quantity": 1000, ...}
  ]
}
# → 返回: {actions: [{code, direction, target_quantity, reasons}], summary}
```

## 测试

```bash
uv sync --extra dev
uv run pytest --cov=src --cov-report=html
```

## Docker 部署

```bash
docker compose up -d
```

## 文档

详细文档见 `doc/` 目录:

| 文档 | 重点内容 |
|------|---------|
| [总体设计](doc/00-总体设计.md) | v5.0 架构总览、三档策略引擎、每日操作流 |
| [数据模块](doc/01-数据模块.md) | 下载引擎架构、QMT API 30+ 接口、断点续传 |
| [因子工程](doc/02-因子工程.md) | 因子分类、预处理流水线、IC 检验、策略对接方式 |
| [机器学习](doc/03-机器学习模块.md) | LGB 训练方式、自动迭代、适用场景、新手教程 |
| [**策略管理**](doc/04-策略管理.md) | **10 个策略的详细使用场景、参数调优、标的池搭配** |
| [回测引擎](doc/05-回测引擎.md) | 各策略回测方法、绩效解读、常见陷阱 |
| [交易模块](doc/06-交易模块.md) | 完整交易流程、多层风控、模拟盘→实盘 |
| [API 文档](doc/07-API接口文档.md) | 全部 API + execute 核心接口详细示例 |
| [用户手册](doc/08-用户手册.md) | 快速上手、策略选择指南、实战教程、下载攻略 |
| [运维部署](doc/09-运维部署.md) | Docker、环境变量、定时任务、磁盘监控 |
| [**市场情绪引擎**](doc/11-市场情绪引擎.md) | **五层数据采集、合成情绪指数、自动宏观判断、策略参数Profile** |

## 配置

- 环境变量: `.env` (项目根目录, 已加入 .gitignore)
- 宏观环境: `macro_env.json` (项目根目录)
