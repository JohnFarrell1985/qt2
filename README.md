# A 股量化因子迭代平台

基于 **三档策略引擎** + **多源因子管线** + **市场情绪引擎** + **ETF 全球轮动** + **LLM 数据清洗** + **知识蒸馏** + **迅投 QMT** 的散户量化投资系统。

> 63 项待办 | [TODO 总览](doc/TODO.md) | 对标 Microsoft Qlib / RD-Agent | Python 3.13

---

## 系统架构

```
                        ┌─────────────────────────────┐
                        │   用户 / 飞书机器人 / OpenClaw  │
                        └──────────────┬──────────────┘
                                       │
                        ┌──────────────▼──────────────┐
                        │   FastAPI (Swagger /docs)    │
                        │   structlog + 飞书告警        │
                        └──────────────┬──────────────┘
                                       │
        ┌──────────────────────────────┼──────────────────────────────┐
        │                              │                              │
┌───────▼───────┐            ┌─────────▼─────────┐          ┌────────▼────────┐
│  数据采集层    │            │    智能处理层       │          │   策略执行层     │
│  datacollect  │            │                    │          │                 │
│               │            │  ┌──────────────┐  │          │  三档策略引擎    │
│ SmartHttp     │───────────▶│  │ LLM 数据清洗  │  │          │  Rule / Score   │
│ (curl_cffi)   │            │  │ DeepSeek/Qwen │  │          │  / ML (LGB)     │
│               │            │  └──────┬───────┘  │          │                 │
│ akshare/QMT   │            │         │          │          │  ETF 全球轮动    │
│ yfinance/sina │            │  ┌──────▼───────┐  │   ┌─────▶│  VAA/DAA/CAA    │
│ efinance/RSS  │            │  │  情绪引擎     │  │   │      │                 │
│ OpenClaw      │            │  │  6 维合成指数  │──┼───┘      │  可转债双低     │
│               │            │  │  宏观状态分类  │  │          └────────┬────────┘
│ 异步并发引擎  │            │  └──────────────┘  │                   │
│ 六层反爬体系  │            │                    │          ┌────────▼────────┐
└───────────────┘            │  ┌──────────────┐  │          │   买卖执行体系   │
                             │  │  知识蒸馏     │  │          │                 │
        ┌───────────────┐    │  │  LLM Teacher  │  │          │ PositionMonitor │
        │   因子工程层    │    │  │  → 小模型     │  │          │ 止损/止盈/追踪   │
        │               │    │  │  (LoRA/DPO)  │  │          │                 │
        │ Alpha158 自算  │    │  └──────────────┘  │          │ SignalArbiter   │
        │ (158 量价因子) │    └────────────────────┘          │ 去重/T+1/投票   │
        │               │                                    │                 │
        │ 迅投基本面因子  │    ┌────────────────────┐          │ PositionSizer   │
        │ (财务/成长/质量)│    │    ML 训练层        │          │ 等权/ATR/Kelly  │
        │               │───▶│                    │─────────▶│                 │
        │ 因子预处理     │    │ LightGBM (主模型)  │          │ 涨跌停/停牌模拟  │
        │ MAD/中性化/Z   │    │ XGBoost / CatBoost│          └────────┬────────┘
        │               │    │                    │                   │
        │ IC/ICIR 筛选   │    │ Purged WF-CV      │          ┌────────▼────────┐
        │ 因子拥挤度检测  │    │ Rolling 重训练     │          │    回测引擎      │
        │ 衰减监控       │    │ Regime-Aware HMM  │          │                 │
        └───────────────┘    │ Bandit (Thompson)  │          │ Orchestrator    │
                             └────────────────────┘          │ Backtester      │
                                                             │ (统一回测/实盘)  │
        ┌────────────────────────────────────────┐           │                 │
        │           基础设施层                     │           │ DSR 多重检验    │
        │                                        │           │ PIT 幸存者偏差   │
        │ PostgreSQL 16 (JSONB) + Alembic 迁移   │           └────────┬────────┘
        │ 迅投 QMT (行情 + 交易)       │                    │
        │ CI/CD (GitHub Actions + pytest + mypy) │           ┌────────▼────────┐
        │ blinker 事件总线 (模块解耦)             │           │  交易执行        │
        │ Tenacity 熔断 + 分级降级               │           │  模拟盘 / 实盘   │
        │ Pandera 数据质量校验                    │           │  迅投 QMT 下单   │
        │ APScheduler 定时调度                    │           │  多层风控        │
        └────────────────────────────────────────┘           └─────────────────┘
```

---

## 核心模块

| 模块 | 路径 | 状态 | 说明 |
|------|------|------|------|
| 公共基础 | `src/common/` | ✅ 已实现 | 配置 / 数据库 / 日志 / 事件总线 |
| 数据下载 | `src/data/` | ✅ 已实现 | QMT 引擎 + PIT 宇宙管理 + 涨跌停 |
| 因子工程 | `src/factor/` | ✅ 已实现 | Alpha158 + 迅投基本面 + 预处理 + IC 分析 |
| 机器学习 | `src/ml/` | ✅ 已实现 | LGB + 自动迭代 + Bandit + Regime-Aware |
| 策略引擎 | `src/strategy/` | ✅ 已实现 | 10 策略 + Orchestrator + Monitor + Arbiter + Sizer |
| 回测引擎 | `src/backtest/` | ✅ 已实现 | 统一回测管道 + DSR + 涨跌停模拟 |
| 交易模块 | `src/trading/` | ✅ 已实现 | QMT 交易 + 风控 + 模拟盘 |
| API 服务 | `src/api/` | ✅ 已实现 | FastAPI 路由 + Swagger |
| 数据采集 | `src/datacollect/` | ✅ 已实现 | 六层反爬 + 异步并发引擎 + 多源 fallback (48 项) |
| 数据清洗 | `src/dataclean/` | 📋 设计完成 | LLM 清洗 + Schema 注册表 + 三级降级 |
| 情绪引擎 | `src/sentiment/` | 📋 设计完成 | 6 维合成指数 + 宏观状态 + 策略 Profile |
| ETF 轮动 | `src/strategy/etf_rotation/` | 📋 设计完成 | VAA/DAA/CAA + 崩盘保护 + 全球配置 |
| 知识蒸馏 | `src/distill/` | 📋 设计完成 | 多教师共识 + LoRA/DPO + 数据飞轮 |
| 组合优化 | `src/portfolio/` | 📋 设计完成 | CAA/MVO + skfolio + Barra 风险归因 |
| 系统监控 | `src/monitoring/` | 📋 设计完成 | 因子衰减 + 模型漂移 + 拥挤度 + 飞书告警 |

---

## 三档策略 + ETF 轮动

| 档位 | 类型 | 策略 | 卖出逻辑 |
|------|------|------|----------|
| Tier 1 | 规则 | 双低可转债 | 双低值升高不再满足 |
| Tier 1 | 规则 | 动量突破 | 动量反转 (收益率翻负) |
| Tier 1 | 规则 | 均值反转 | 反弹目标达成 (>5%) |
| Tier 1 | 规则 | 行业轮动 | 行业排名跌出 Top N |
| Tier 1 | 规则 | 均线突破 | 死叉 (短均下穿长均) |
| Tier 1 | 规则 | T+1 宽网格 | 价格触及网格上沿 |
| Tier 1 | 规则 | 低波红利 | 波动率飙升 |
| Tier 2 | 打分 | 多因子等权/IC 加权 | 因子排名下滑至后 30% |
| Tier 3 | ML | LightGBM / XGBoost / CatBoost | 模型预测收益低于阈值 |
| **ETF** | **TAA** | **VAA / DAA / R²×Return / CAA** | **动量翻负 → 切换至债券/货币** |

---

## 技术栈

### 核心框架

| 类别 | 技术 | 版本 | 用途 |
|------|------|------|------|
| **ML** | LightGBM | >=4.6 | 主模型 (GBDT) |
| | XGBoost | >=3.0 | Ensemble |
| | CatBoost | >=1.2.10 | Ensemble |
| | scikit-learn | >=1.7 | CV / Pipeline |
| **因子** | Qlib Alpha158 | (自算) | 158 个量价因子 |
| | xtquant | (迅投) | 基本面/财务因子 |
| | jqdatasdk | >=1.9 | 聚宽因子 (可选) |
| **组合优化** | skfolio | >=0.15 | 100+ 组合模型 (sklearn 兼容) |
| | cvxpy | >=1.5 | 凸优化求解 |
| **数据采集** | curl_cffi | >=0.15 | TLS 指纹伪装 (反爬核心) |
| | akshare | >=1.18 | A 股免费数据 (主力源) |
| | yfinance | >=0.2 | 全球市场 (美股/VIX/黄金/外汇) |
| | efinance | >=0.4 | A 股资金面 (北向/融资/龙虎榜) |
| | baostock | >=0.8 | A 股历史 K 线 + 财务 |
| | tushare | >=1.4 | A 股/可转债/ETF |
| | adata | >=2.9 | 多源融合 A 股数据 |
| | feedparser | >=6.0 | RSS 财经新闻聚合 |
| | Playwright | >=1.40 | 浏览器级采集 (可选) |
| | tavily-python | >=0.5 | AI 搜索兜底 (可选) |
| **LLM / NLP** | openai SDK | >=2.0 | DeepSeek / Qwen 统一客户端 |
| | FinBERT2 | 2025 | 中文金融情感模型 |
| | transformers | >=5.0 | HuggingFace 推理 |
| **蒸馏** | setfit | >=1.1 | 少样本冷启动 (8 例/类) |
| | peft (LoRA) | >=0.18 | 参数高效微调 |
| | trl (DPO) | >=1.0 | 偏好对齐训练 |
| | onnxruntime | >=1.21 | 生产推理 (INT8) |
| **数据库** | PostgreSQL | >=16 | JSONB + GIN 索引 |
| | SQLAlchemy | >=2.0 | ORM |
| | Alembic | >=1.15 | Schema 迁移 |
| **基础设施** | FastAPI | >=0.115 | Web API |
| | APScheduler | >=3.11 | 定时调度 |
| | blinker | >=1.9 | 事件总线 |
| | tenacity | >=9.0 | 重试 + 熔断 |
| | structlog | >=25.1 | 结构化日志 |
| | pandera | >=0.23 | 数据质量校验 |
| **统计** | statsmodels | >=0.14 | OLS 中性化 |
| | scipy | >=1.15 | 统计检验 |
| **基础** | pandas | >=2.2 | 数据处理 |
| | numpy | >=2.0 | 向量化运算 |
| | torch | >=2.8 | 深度学习训练 |
| **实验管理** | MLflow | >=3.0 | 模型注册 / 追踪 |
| | SHAP | >=0.51 | 可解释性 |

### 交易接口

| 接口 | 说明 |
|------|------|
| 迅投 QMT | 行情数据 + 实盘/模拟交易 |
| OpenClaw + 飞书机器人 | 新闻采集 + 告警推送 |

---

## 快速开始

```bash
# 安装
uv sync

# 初始化数据库
uv run python scripts/init_db.py

# 启动 API 服务
uv run uvicorn src.api.main:app --host 0.0.0.0 --port 8012

# Swagger 文档
open http://localhost:8012/docs
```

### 核心 API

```bash
# 完整执行: 输入持仓和资金 → 输出今日操作清单
POST /api/strategy/execute
{
  "total_capital": 1000000,
  "available_cash": 500000,
  "holdings": [
    {"code": "000001.SZ", "buy_price": 10.0, "quantity": 1000}
  ]
}
# → {actions: [{code, direction, target_quantity, reasons}], summary}
```

### 测试

```bash
uv sync --extra dev

# 单元测试
uv run pytest tests/ -m "not qmt" --cov=src --cov-report=html

# E2E 端到端测试 (按模块)
uv run pytest tests/e2e/api/ -v                # API E2E (合成数据)
uv run pytest tests/e2e/datacollect/ -v        # 数据采集 E2E (真实数据源, 120s超时)
uv run pytest tests/e2e/qmt/ -v -m qmt        # QMT 终端 E2E (需 QMT 已登录)

# 全量 E2E (排除 QMT)
uv run pytest tests/e2e/ -v -m "not qmt"
```

### Docker 部署

```bash
docker compose up -d
```

---

## 文档

| 文档 | 重点内容 |
|------|---------|
| [总体设计](doc/00-总体设计.md) | 架构总览、三档策略引擎、每日操作流 |
| [数据模块](doc/01-数据模块.md) | QMT 下载引擎、30+ API 接口、断点续传 |
| [因子工程](doc/02-因子工程.md) | 因子分类、预处理流水线、IC 检验 |
| [机器学习](doc/03-机器学习模块.md) | LGB 训练、自动迭代、新手教程 |
| [策略管理](doc/04-策略管理.md) | 10 策略使用场景、参数调优、标的池 |
| [回测引擎](doc/05-回测引擎.md) | 回测方法、绩效解读、常见陷阱 |
| [交易模块](doc/06-交易模块.md) | 完整交易流程、多层风控、模拟→实盘 |
| [API 接口](doc/07-API接口文档.md) | 全部 API + execute 核心接口 |
| [用户手册](doc/08-用户手册.md) | 快速上手、策略选择、实战教程 |
| [运维部署](doc/09-运维部署.md) | Docker、环境变量、定时任务 |
| [市场情绪引擎](doc/11-市场情绪引擎.md) | 情绪特征、合成指数、宏观分类、策略 Profile |
| [数据采集模块](doc/12-数据采集模块.md) | 六层反爬、异步并发引擎、多源 fallback、48 项全部完成 |
| [数据清洗与 LLM](doc/13-数据清洗与LLM.md) | LLM 清洗管道、Schema 注册表、降级策略 |
| [ETF 资产配置轮动](doc/14-ETF资产配置轮动.md) | VAA/DAA/CAA 策略族、候选池、崩盘保护 |
| **[TODO 待办清单](doc/TODO.md)** | **63 项剩余: P0+P0.1 已完成, P1~P4 待实施** |

---

## 参考文献与论文

### 量化投资

| 文献 | 作者 / 来源 | 核心贡献 |
|------|------------|---------|
| *Advances in Financial Machine Learning* | Marcos López de Prado (2018) | Purged CV、因子预处理、回测陷阱 |
| *Momentum and Markowitz: A Golden Combination* | Keller, Butler & Kipnis (2015) | CAA: 动量 + MVO, 百年回测 Sharpe=1.0 |
| Deflated Sharpe Ratio | Bailey & López de Prado (2014) | 多重检验修正, 防止回测过拟合 |
| Critical Line Algorithm (CLA) | Bailey & López de Prado (2013) | MVO 精确解, 无需梯度下降 |
| Vigorous Aggressive Asset Allocation (VAA) | Keller & Keuning (2017), SSRN 3002624 | 广度动量 + 哨兵资产轮动 |
| Defensive Asset Allocation (DAA) | Keller & Keuning (2018), SSRN 3212862 | 改进型 VAA, 哨兵资产分级 |
| Resilient Asset Allocation (RAA) | Keller (2021), SSRN 3752294 | 抗通胀型全天候配置 |
| Dual Momentum | Gary Antonacci (2014) | 绝对 + 相对动量双重过滤 |
| Barra CNE5/CNE6 | MSCI / 中信建投 | A 股多因子风险模型 |
| *Trade Your Way to Financial Freedom* | Van Tharp | ATR 仓位管理 |
| *Way of the Turtle* | Curtis Faith | 海龟交易系统 ATR 规则 |
| Signal Decay Analysis | Jegadeesh & Titman (1993), Asness (2014) | 动量因子生命周期 ~10 个月 |
| 《因子投资：方法与实践》 | 石川 | A 股因子预处理实操 |

### 机器学习与 AI

| 文献 | 作者 / 来源 | 核心贡献 |
|------|------------|---------|
| RD-Agent: Data-Centric Multi-Agent | Microsoft (2025), arXiv:2505.15155 | LLM 驱动因子-模型联合进化, Thompson Sampling Bandit |
| FactorEngine | arXiv:2603.16365 (2026) | LLM 引导程序级因子挖掘, SOTA IC/ICIR |
| ODA-Fin | arXiv:2603.07223 (2026) | 难度感知金融蒸馏, 8B 超越同规模 SOTA |
| NVIDIA Data Flywheel Blueprint | NVIDIA (2025) | 生产级金融蒸馏, 49-70B→1-8B, 成本降 98% |
| TensorZero | TensorZero (2025) | 程序化策展 + 微调, 5-30x 降本 |
| SetFit | HuggingFace (2022) | 8 样本/类达 RoBERTa-Large 水平 |
| TinyFinBERT | arXiv:2409.18999 (2024) | 14.5M 参数, GPT 蒸馏, 99% 保留率 |
| FinBERT2 | valuesimplex (2025) | 最强中文金融 NLP (32B token 预训练) |
| TinyLoRA | arXiv (2026.03) | 仅 13 参数微调达 91.8% GSM8K |
| EvasionBench | arXiv:2601.09142 (2026) | 多模型共识 + 分歧挖掘 |

### 对标开源项目

| 项目 | Star | 说明 |
|------|------|------|
| [Microsoft Qlib](https://github.com/microsoft/qlib) | ~40k | AI 量化平台, 统一管道标杆 |
| [Microsoft RD-Agent](https://github.com/microsoft/RD-Agent) | 3.8k+ | LLM 自主因子-模型进化 |
| [skfolio](https://skfolio.org/) | - | scikit-learn 原生组合优化 |
| [Barra-CNE5](https://github.com/xinyue6688/Barra-CNE5) | - | A 股风险模型 Python 实现 |
| [Barra-CNE6-LightGBM](https://github.com/finexsf/Barra-CNE6-LightGBM) | - | CNE6 + LGB 选股 |
| [FinBERT2](https://github.com/valuesimplex/FinBERT) | - | 中文金融 NLP |
| [NVIDIA Financial Distillation](https://github.com/NVIDIA-AI-Blueprints/ai-model-distillation-for-financial-data) | 41 | 生产级蒸馏蓝图 |
| [TensorZero](https://github.com/tensorzero/tensorzero) | 7.3k+ | LLMOps 程序化策展 |
| [SetFit](https://github.com/SetFit/setfit) | 2.2k+ | 少样本学习 |
| [Pandera](https://pandera.readthedocs.io/) | 3.5k+ | DataFrame schema 校验 |
| [zhangsensen/etf-rotation](https://github.com/zhangsensen/etf-rotation-strategy) | - | A 股 ETF 轮动实盘 |
| [oronimbus/tactical-aa](https://github.com/oronimbus/tactical-asset-allocation) | - | TAA 回测框架 |
| [JoinQuant jqfactor_analyzer](https://github.com/JoinQuant/jqfactor_analyzer) | 130+ | 因子分析工具 |
| [Qlib Alpha158](https://github.com/microsoft/qlib/blob/main/qlib/contrib/data/handler.py) | (Qlib 内置) | 158 个量价因子 |

---

## 配置

- 环境变量: `.env` (项目根目录, 已加入 .gitignore; 新用户可复制 `.env.example` 模板)
- 宏观环境: `macro_env.json` (项目根目录)

## License

Private repository.
