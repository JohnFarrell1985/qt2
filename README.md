# A股量化因子迭代平台 v3.0

基于 **LightGBM** 因子挖掘 + **迅投 QMT** 数据/交易 + **策略池化** + **宏观环境映射** 的量化投资系统。

## 架构

```
用户 / 飞书机器人 / OpenClaw
         │
    FastAPI (Swagger /docs)
         │
┌────────┼────────┬──────────┬───────────┐
│ 数据层 │ 因子工程 │ 机器学习  │ 策略管理   │
│ QMT   │ IC/IR  │ LightGBM │ 池化+宏观  │
├────────┴────────┼──────────┴───────────┤
│   回测引擎       │    交易执行 (模拟/实盘) │
├─────────────────┴──────────────────────┤
│   PostgreSQL  │  迅投 QMT/MiniQMT       │
└───────────────┴────────────────────────┘
```

## 模块

| 模块 | 路径 | 说明 |
|------|------|------|
| 公共 | `src/common/` | 配置、日志、数据库 |
| 数据 | `src/data/` | QMT 数据对接、400+ 因子同步 |
| 因子 | `src/factor/` | 因子计算、预处理、IC/IR 分析 |
| ML | `src/ml/` | LightGBM 训练、自动迭代优化 |
| 策略 | `src/strategy/` | 策略池、标的池、宏观环境 |
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
- [总体设计](doc/00-总体设计.md)
- [数据模块](doc/01-数据模块.md) — 下载引擎架构、QMT API 接口一览
- [因子工程](doc/02-因子工程.md)
- [机器学习](doc/03-机器学习模块.md)
- [策略管理](doc/04-策略管理.md)
- [回测引擎](doc/05-回测引擎.md)
- [交易模块](doc/06-交易模块.md)
- [API 文档](doc/07-API接口文档.md)
- [用户手册](doc/08-用户手册.md) — **含数据下载攻略** (第 6 章)
- [运维部署](doc/09-运维部署.md)
- [OpenClaw 飞书对接](doc/10-OpenClaw飞书对接.md)

## 配置

- 环境变量: `.env` (项目根目录, 已加入 .gitignore)
- 宏观环境: `macro_env.json` (项目根目录)
