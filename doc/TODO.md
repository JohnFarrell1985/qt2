# qt-quant 综合待办清单 (索引)

> 最后更新: 2026-04-04
>
> 本清单合并了两部分内容:
> 1. **量化体系优化** — 以专业量化研究视角审查现有代码后发现的缺陷和改进点
> 2. **新模块开发** — doc/11 (情绪引擎)、doc/12 (数据采集)、doc/13 (数据清洗) 中设计完成但代码尚未实现的部分
>
> 每项任务均包含: **为什么要做** → **业界最佳实践** → **技术选型与版本** → **参考文档** → **落地方案**

---

## 分文档索引

| 优先级 | 文档 | 项目数 | 预估工作量 | 核心价值 |
|--------|------|--------|-----------|---------|
| **P0** | [TODO-P0.md](TODO-P0.md) | 23 项 | ~20 天 | Bug 修复 + 三大新模块骨架 (datacollect/dataclean/sentiment) |
| **P1** | [TODO-P1.md](TODO-P1.md) | 20 项 | ~40 天 | 量化核心提升 (CV/监控/CAA组合优化) + 模块完善 + ETF 全球资产轮动 |
| **P2** | [TODO-P2.md](TODO-P2.md) | 18 项 | ~27 天 | 高级功能 + 扩展引擎 + RD-Agent 式自动迭代 |
| **P3** | [TODO-P3.md](TODO-P3.md) | 10 项 | ~19 天 | 长期可选 (SHAP/事件总线/FinBERT/行业轮动/宏观经济) |
| **合计** | — | **71 项** | **~106 天** | — |

---

## 当前代码现状

**已实现** (`src/` 中已存在代码):

| 模块 | 路径 | 状态 |
|------|------|------|
| 策略引擎 | `src/strategy/` | 10 策略 + orchestrator + monitor + arbiter + sizer |
| 数据下载 | `src/data/` | QMT 数据下载引擎 + models |
| 因子工程 | `src/factor/` | 因子计算 / 预处理 / IC 分析 |
| 机器学习 | `src/ml/` | LGB + 自动迭代 + 评估 |
| 回测引擎 | `src/backtest/` | 日线 / 分钟线回测 + 绩效 |
| 交易模块 | `src/trading/` | QMT 交易 + 风控 + 模拟盘 |
| API 服务 | `src/api/` | FastAPI 路由 |
| 公共基础 | `src/common/` | 配置 / 数据库 / 日志 |

**仅有文档设计、代码未创建** (待办):

| 模块 | 路径 | 设计文档 |
|------|------|---------|
| 数据采集 | `src/datacollect/` | [doc/12-数据采集模块.md](12-数据采集模块.md) |
| 数据清洗 | `src/dataclean/` | [doc/13-数据清洗与LLM.md](13-数据清洗与LLM.md) |
| 情绪引擎 | `src/sentiment/` | [doc/11-市场情绪引擎.md](11-市场情绪引擎.md) |
| 个股雷达 | `src/stockradar/` | doc/13 引擎扩展章节 |
| 资金流向 | `src/fundflow/` | doc/13 引擎扩展章节 |
| 风险预警 | `src/riskmonitor/` | doc/13 引擎扩展章节 |
| 行业轮动 | `src/sectorwatch/` | doc/13 引擎扩展章节 |
| 宏观经济 | `src/macrotrack/` | doc/13 引擎扩展章节 |
| **ETF 轮动** | `src/strategy/etf_rotation/` | [TODO-P1.md P1-20](TODO-P1.md#p1-20-etf-全球资产轮动策略-tactical-asset-allocation) |

---

## 任务速查表

### P0: 紧急 / 基础 → [详见 TODO-P0.md](TODO-P0.md)

| # | 任务 | 模块 | 工作量 |
|---|------|------|--------|
| P0-01 | ATR PositionSizer 未接入 | strategy | 0.5 天 |
| P0-02 | 行业中性化未启用 | factor | 1 天 |
| P0-03 | FactorDataset 预处理断路 + IC 去重 | ml | 0.5 天 |
| P0-04 | 回测与实盘管道不一致 | backtest | 3-5 天 |
| P0-05 | SmartHttpClient 反爬 HTTP 客户端 | datacollect | 1 天 |
| P0-06 | TokenBucketLimiter 令牌桶限流器 | datacollect | 0.5 天 |
| P0-07 | BaseCollector 采集器抽象基类 | datacollect | 0.5 天 |
| P0-08 | AkshareCollector | datacollect | 1 天 |
| P0-09 | 数据源注册表 | datacollect | 1 天 |
| P0-10 | 采集日志 ORM | datacollect | 0.5 天 |
| P0-11 | datacollect 模块初始化 | datacollect | 0.5 天 |
| P0-12 | LLMClient 统一客户端 | dataclean | 1 天 |
| P0-13 | BaseCleaner + CleanResult | dataclean | 0.5 天 |
| P0-14 | SentimentExtraction Schema | dataclean | 0.5 天 |
| P0-15 | SentimentCleaner LLM 清洗器 | dataclean | 1 天 |
| P0-16 | PassthroughCleaner | dataclean | 0.5 天 |
| P0-17 | RuleCleaner | dataclean | 0.5 天 |
| P0-18 | 情绪清洗 Prompt 模板 | dataclean | 0.5 天 |
| P0-19 | dataclean 模块初始化 | dataclean | 0.5 天 |
| P0-20 | SentimentDaily ORM (JSONB) | sentiment | 1 天 |
| P0-21 | 量价情绪 Layer 1 | sentiment | 1.5 天 |
| P0-22 | 策略参数 Profile | sentiment | 1 天 |
| P0-23 | 情绪 API 端点 | sentiment | 1 天 |

### P1: 重要 → [详见 TODO-P1.md](TODO-P1.md)

| # | 任务 | 模块 | 工作量 |
|---|------|------|--------|
| P1-01 | Purged Walk-Forward CV | ml | 2-3 天 |
| P1-02 | Rolling 重训练 + Bandit | ml | 3 天 |
| P1-03 | 因子衰减监控 | monitoring | 2 天 |
| P1-04 | 模型漂移检测 | monitoring | 2 天 |
| P1-05 | 组合优化器 (CAA/skfolio) | portfolio | 5-7 天 |
| P1-06 | 风险归因 (Barra 简化) | portfolio | 3 天 |
| P1-07 | 换手率约束 | strategy | 1 天 |
| P1-08 | CollectRouter 自适应路由 | datacollect | 1.5 天 |
| P1-09 | OpenClawReceiver | datacollect | 1 天 |
| P1-10 | XtdataCollector | datacollect | 1 天 |
| P1-11 | APScheduler 定时调度 | datacollect | 1.5 天 |
| P1-12 | StockEvent Schema + Cleaner | dataclean | 1 天 |
| P1-13 | RiskAlert Schema | dataclean | 0.5 天 |
| P1-14 | Schema + Prompt 注册表 | dataclean | 1 天 |
| P1-15 | 清洗日志 ORM | dataclean | 0.5 天 |
| P1-16 | 6维情绪合成指数 | sentiment | 1.5 天 |
| P1-17 | 宏观状态分类器 | sentiment | 2 天 |
| P1-18 | Orchestrator 集成 Profile | strategy | 1.5 天 |
| P1-19 | 情绪 API 完整化 | sentiment | 1.5 天 |
| **P1-20** | **ETF 全球资产轮动策略** | **strategy** | **7-10 天** |

### P2: 增强 → [详见 TODO-P2.md](TODO-P2.md)

| # | 任务 | 模块 | 工作量 |
|---|------|------|--------|
| P2-01 | 滑点模型 | backtest | 1 天 |
| P2-02 | XGBoost/CatBoost + Ensemble | ml | 2 天 |
| P2-03 | 绩效分析增强 | backtest | 2 天 |
| P2-04 | Survivorship Bias / PIT | data | 2 天 |
| P2-05 | 交易成本归因 | backtest | 1 天 |
| P2-06 | 多周期标签 | ml | 1 天 |
| P2-07 | TavilyCollector | datacollect | 1 天 |
| P2-08 | BrowserCollector (Playwright) | datacollect | 1.5 天 |
| P2-09 | HttpCollector | datacollect | 1 天 |
| P2-10 | SectorSignal Schema | dataclean | 1 天 |
| P2-11 | FundFlow Schema | dataclean | 0.5 天 |
| P2-12 | MacroIndicator Schema | dataclean | 0.5 天 |
| P2-13 | 情绪特征工程 → LGB | sentiment | 2 天 |
| P2-14 | 合成指数权重自动学习 | sentiment | 1 天 |
| P2-15 | 个股雷达引擎 | stockradar | 3 天 |
| P2-16 | 资金流向引擎 | fundflow | 3 天 |
| P2-17 | 风险预警引擎 | riskmonitor | 2 天 |
| P2-18 | LLM 驱动因子-模型联合迭代 (RD-Agent) | ml | 5 天 |

### P3: 长期 → [详见 TODO-P3.md](TODO-P3.md)

| # | 任务 | 模块 | 工作量 |
|---|------|------|--------|
| P3-01 | SHAP 可解释性 | ml | 1 天 |
| P3-02 | 实验管理 (MLflow + Trace) | ml | 2 天 |
| P3-03 | 轻量级事件总线 | common | 3 天 |
| P3-04 | 数据版本化 | data | 2 天 |
| P3-05 | ProxyPool 代理池 | datacollect | 1 天 |
| P3-06 | 本地 FinBERT NLP | dataclean | 2 天 |
| P3-07 | GenericExtraction Schema | dataclean | 0.5 天 |
| P3-08 | 热门股/一日游识别 | ml | 2 天 |
| P3-09 | 行业轮动引擎 | sectorwatch | 3 天 |
| P3-10 | 宏观经济引擎 | macrotrack | 3 天 |

---

## 核心技术栈一览

| 类别 | 技术 | 版本 | 最新状态 | 用途 |
|------|------|------|---------|------|
| **ML 框架** | LightGBM | >=4.5 | ✅ 2026活跃 | 主模型 |
| | XGBoost | >=2.1 | ✅ 2026活跃 | Ensemble |
| | CatBoost | >=1.2 | ✅ 2025 | Ensemble |
| **ML 工具** | shap | >=0.50 | ✅ 2026 | 可解释性 |
| | mlflow | >=2.20 | ✅ 2026活跃 | 实验管理 |
| | scikit-learn | >=1.5 | ✅ | CV/Pipeline |
| **自动迭代** | Thompson Sampling (自研) | - | - | Bandit 因子/模型方向选择 (借鉴 RD-Agent) |
| | Trace (自研) | - | - | 实验历史记忆链 + 智能过滤 (借鉴 RD-Agent) |
| **组合优化** | CLA (自研) | - | - | CAA 核心: Critical Line Algorithm (Keller 2015) |
| | skfolio | >=0.5 | ✅ 2026 | 组合优化 (sklearn 兼容，高级约束) |
| | cvxpy | >=1.5 | ✅ | 凸优化求解 |
| **数据采集** | curl_cffi | >=0.7.4 | ✅ 2026活跃 | TLS 指纹伪装 |
| | Playwright | >=1.48 | ✅ 2026活跃 | 浏览器采集 |
| | akshare | >=1.14 | ✅ 持续更新 | A股免费数据 |
| | tavily-python | >=0.5 | ✅ 2026.03 | 搜索 API |
| **LLM** | openai SDK | >=1.60 | ✅ | DeepSeek/Qwen 统一客户端 |
| | pydantic | >=2.6 | ✅ | Schema 定义 |
| **NLP** | FinBERT2 | 2025 | ✅ 最新 | 中文金融情感 |
| | transformers | >=4.46 | ✅ | HuggingFace 推理 |
| **调度** | APScheduler | 3.10/4.0α | ✅ | 定时采集 |
| **事件** | blinker | >=1.9 | ✅ | 模块解耦 |
| **数据库** | PostgreSQL | >=16 | ✅ | JSONB 存储 |
| | SQLAlchemy | >=2.0 | ✅ | ORM |
| **统计** | statsmodels | >=0.14 | ✅ | 回归/中性化 |
| | scipy | >=1.12 | ✅ | 统计检验 |

---

## 对标参考项目

| 项目 | Star | 说明 | 链接 |
|------|------|------|------|
| **Microsoft Qlib** | 39.8k | AI 量化投资平台，统一管道设计标杆 | [github.com/microsoft/qlib](https://github.com/microsoft/qlib) |
| **Barra-CNE5** | - | A 股风险模型 Python 实现 | [github.com/xinyue6688/Barra-CNE5](https://github.com/xinyue6688/Barra-CNE5) |
| **Barra-CNE6-LightGBM** | - | Barra CNE6 + LGB 选股 | [github.com/finexsf/Barra-CNE6-LightGBM](https://github.com/finexsf/Barra-CNE6-LightGBM) |
| **skfolio** | - | scikit-learn 原生组合优化 | [skfolio.org](https://skfolio.org/) |
| **FinBERT2** | - | 最强中文金融 NLP 模型 | [github.com/valuesimplex/FinBERT](https://github.com/valuesimplex/FinBERT) |
| **Tavily Market Researcher** | - | AI 搜索驱动金融研究 | [github.com/tavily-ai/market-researcher](https://github.com/tavily-ai/market-researcher) |
| **Market Intelligence MVP** | - | MLflow+Airflow+FastAPI 金融 ML | [github.com/cdobratz/market-intelligence-mvp](https://github.com/cdobratz/market-intelligence-mvp) |
| **CAA (Keller 2015)** | - | 动量+MVO 百年回测 Sharpe=1.0 | SSRN: Keller, Butler & Kipnis (2015) *Momentum and Markowitz* |
| **CLA Python (Bailey 2013)** | - | Critical Line Algorithm 开源实现 | SSRN 2197616, Bailey & López de Prado (2013) |
| **Microsoft RD-Agent** | 3.8k+ | LLM 驱动自主因子-模型联合进化 (Bandit+Trace+IC去重) | [github.com/microsoft/RD-Agent](https://github.com/microsoft/RD-Agent) |
| **zhangsensen/etf-rotation** | - | A 股 ETF 轮动实盘 (WFO+VEC+BT 三层验证, OOS Sharpe=1.38) | [github.com/zhangsensen/etf-rotation-strategy](https://github.com/zhangsensen/etf-rotation-strategy) |
| **Keller VAA/DAA/RAA** | - | 广度动量+哨兵资产 TAA 策略族 (SSRN 3002624/3212862/3752294) | [allocatesmartly.com](https://allocatesmartly.com/) |
| **oronimbus/tactical-aa** | - | TAA 回测框架 (Dual Momentum + 多策略) | [github.com/oronimbus/tactical-asset-allocation](https://github.com/oronimbus/tactical-asset-allocation) |

---

## 建议执行顺序

```
Phase 0 (第 1-3 周):
  P0-01~03  修复已有代码 bug (ATR/中性化/预处理)
  P0-05~11  datacollect 核心 (HTTP客户端/限流/采集器/注册表)
  P0-12~19  dataclean 核心 (LLM客户端/Schema/清洗器)
  P0-20~23  sentiment 核心 (ORM/量价情绪/Profile/API)

Phase 1 (第 4-8 周):
  P0-04     OrchestratorBacktester (回测统一)
  P1-01~02  Purged CV + Walk-Forward 重训练
  P1-05~06  组合优化 + 风险归因
  P1-08~11  datacollect 完善 (路由/OpenClaw/调度)
  P1-12~15  dataclean 完善 (扩展Schema/注册表)
  P1-16~19  sentiment 完善 (合成指数/分类器/Profile集成)
  P1-20     ETF 全球资产轮动策略 (池/动量/崩盘保护/回测)

Phase 2 (第 8-11 周):
  P1-03~04  因子/模型监控
  P1-07     换手率约束
  P2-01~06  量化增强 (滑点/XGB/绩效/PIT/多周期)
  P2-07~14  采集+清洗+情绪高级功能
  P2-15~17  扩展引擎 (个股雷达/资金/风险)
  P2-18     RD-Agent 式自动因子-模型联合迭代 (Bandit+Trace+IC去重)

Phase 3 (第 12 周+):
  P3-01~10  按需选择实现
```
