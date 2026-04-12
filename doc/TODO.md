# qt-quant 综合待办清单 (索引)

> 最后更新: 2026-04-12
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
| ~~**P0**~~ | ✅ 已完成 | ~~12 项~~ | ~~16.5 天~~ | Bug 修复 + 核心量化 + 基础设施 — **全部完成** |
| ~~**P0.1**~~ | ✅ 已完成 → [12-数据采集模块](12-数据采集模块.md) + [13-数据清洗与LLM](13-数据清洗与LLM.md) | ~~57 项~~ | ~~~24 天~~ | 数据采集 (A01-A48) + 数据清洗 (P0-12~20) — **全部完成** |
| **P1** | [TODO-P1.md](TODO-P1.md) | 30 项 | ~61 天 | 量化核心 + 监控 + ETF 轮动 + 多源因子 + DSR + 事件总线 + 容错 + **架构改进 (标的池分类/交易规则引擎/UniverseProvider)** |
| **P2** | [TODO-P2.md](TODO-P2.md) | 22 项 | ~35 天 | 高级功能 + 扩展引擎 + RD-Agent + 知识蒸馏 + TOML 配置 |
| **P3** | [TODO-P3.md](TODO-P3.md) | 9 项 | ~14 天 | 长期可选 (SHAP/行业轮动/宏观经济) |
| **P4** | [TODO-P4.md](TODO-P4.md) | 7 项 | ~12 天 | **全栈可观测性** (Jaeger/Loki/Prometheus/Grafana/Alert, 参考 fliac ops03) |
| **合计** | — | **68 项** (剩余) | **~122 天** | P0 + P0.1 已完成, 其余待实施 |

---

## 当前代码现状

**已实现** (`src/` 中已存在代码):

| 模块 | 路径 | 状态 |
|------|------|------|
| 策略引擎 | `src/strategy/` | 10 策略 + orchestrator + monitor + arbiter + sizer (ATR 已接入) |
| 数据下载 | `src/data/` | QMT 数据下载引擎 + models + universe_manager (PIT) + limit_status |
| 因子工程 | `src/factor/` | 11 个手工因子 / 预处理 / IC 分析 / 行业中性化已启用 (待扩充至 Alpha158+迅投, 见 P1-21) |
| 机器学习 | `src/ml/` | LGB + 自动迭代 + 评估 + 预处理已接通 |
| 回测引擎 | `src/backtest/` | OrchestratorBacktester (统一管道) + 涨跌停/停牌模拟 + 绩效 |
| 情绪引擎 | `src/sentiment/` | ORM (JSONB) + Layer 1 量价情绪 + 策略 Profile + API |
| 交易模块 | `src/trading/` | QMT 交易 + 风控 + 模拟盘 |
| API 服务 | `src/api/` | FastAPI 路由 (依赖注入) |
| 公共基础 | `src/common/` | 配置 / 数据库 (DeclarativeBase) / 日志 |
| 基础设施 | `.github/`, `alembic/` | CI/CD (GitHub Actions) + Alembic 数据库迁移 |
| 数据采集 | `src/datacollect/` | 六层反爬 + 异步并发引擎 + 多源 fallback (A01-A48, 48 项) |
| 数据清洗 | `src/dataclean/` | instructor + LLM 清洗 + 三级降级 + E2E 测试 (P0-12~20, 9 项) |

**仅有文档设计、代码未创建** (待办):

| 模块 | 路径 | 设计文档 |
|------|------|---------|
| 个股雷达 | `src/stockradar/` | doc/13 引擎扩展章节 |
| 资金流向 | `src/fundflow/` | doc/13 引擎扩展章节 |
| 风险预警 | `src/riskmonitor/` | doc/13 引擎扩展章节 |
| 行业轮动 | `src/sectorwatch/` | doc/13 引擎扩展章节 |
| 宏观经济 | `src/macrotrack/` | doc/13 引擎扩展章节 |
| **ETF 轮动** | `src/strategy/etf_rotation/` | [TODO-P1.md P1-20](TODO-P1.md#p1-20-etf-全球资产轮动策略-tactical-asset-allocation) |
| **标的池分类/交易规则** | `src/strategy/trading_rules.py` (新增) | [TODO-P1.md P1-27](TODO-P1.md#p1-27-标的池分类与交易规则引擎-a股港股etf两融) |
| **UniverseProvider** | `src/data/universe_provider.py` (新增) | [TODO-P1.md P1-28](TODO-P1.md#p1-28-universeprovider-统一抽象接口) |
| **知识蒸馏** | `src/distill/` | [TODO-P2.md P2-19~P2-21](TODO-P2.md#p2-19--p2-21-知识蒸馏模块-llm-教师--轻量学生模型) |

---

## 任务速查表

### ~~P0: 紧急 Bug 修复 + 核心量化 + 基础设施~~ — ✅ 全部完成

> P0 全部 12 项已实现并通过 642 个单元测试验证 (2026-04-10)。
> 包括: ATR 仓位接入、行业中性化、预处理接通、OrchestratorBacktester 统一回测管道、
> 情绪引擎 (ORM/量价/Profile/API)、PIT 数据管理、CI/CD、Alembic、涨跌停模拟。

### ~~P0.1: 数据采集 + 数据清洗~~ ✅ 全部完成

> - **数据采集** (A01-A48, 48 项): 全部完成 → [12-数据采集模块.md](12-数据采集模块.md#实现完成总览-48-项-全部-)
> - **数据清洗** (P0-12~P0-20, 9 项): 全部完成 → [13-数据清洗与LLM.md](13-数据清洗与LLM.md#实现完成总览-p0-12--p0-20-全部-)

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
| **P1-21** | **多源因子管线 (Alpha158+迅投+自动筛选)** | **factor** | **4-5 天** |
| **P1-22** | **Deflated Sharpe Ratio / 多重检验修正** | **backtest** | **1.5 天** |
| **P1-23** | **轻量级事件总线 (从 P3-03 提升)** | **common** | **3 天** |
| **P1-24** | **数据质量监控 + Schema 校验 (Pandera)** | **data** | **2 天** |
| **P1-25** | **系统级容错 & 降级 (Tenacity/熔断)** | **common** | **2 天** |
| ~~**P1-26**~~ | ~~可观测性 (structlog + 飞书机器人告警)~~ → **已合并至 P4** | — | — |
| **P1-27** | **标的池分类与交易规则引擎 (A股/港股/ETF/两融)** | **strategy/data** | **3 天** |
| **P1-28** | **UniverseProvider 统一抽象接口** | **data/strategy** | **1 天** |
| **P1-29** | **策略自动发现与注册** | **strategy** | **0.5 天** |
| **P1-30** | **BaseFactor ABC + FactorRegistry** | **factor** | **1 天** |
| **P1-31** | **FactorPool 版本追溯** | **factor** | **0.5 天** |

### P2: 增强 → [详见 TODO-P2.md](TODO-P2.md)

| # | 任务 | 模块 | 工作量 |
|---|------|------|--------|
| P2-01 | 滑点模型 | backtest | 1 天 |
| P2-02 | XGBoost/CatBoost + Ensemble | ml | 2 天 |
| P2-03 | 绩效分析增强 | backtest | 2 天 |
| ~~P2-04~~ | ~~Survivorship Bias / PIT~~ → ✅ 已完成 (原 P0-24) | — | — |
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
| P2-19 | 多教师共识标注管线 (知识蒸馏) | distill | 2.5 天 |
| P2-20 | 学生模型分层训练 (SetFit+LoRA+DPO) | distill | 3 天 |
| P2-21 | 数据飞轮 + 生产部署 (ONNX) | distill | 2.5 天 |
| **P2-22** | **配置管理迁移 (.env → TOML 分层)** | **common** | **2 天** |

### P3: 长期 → [详见 TODO-P3.md](TODO-P3.md)

| # | 任务 | 模块 | 工作量 |
|---|------|------|--------|
| P3-01 | SHAP 可解释性 | ml | 1 天 |
| P3-02 | 实验管理 (MLflow + Trace) | ml | 2 天 |
| ~~P3-03~~ | ~~轻量级事件总线~~ → **已提升至 P1-23** | — | — |
| P3-04 | 数据版本化 | data | 2 天 |
| ~~P3-05~~ | ~~ProxyPool 代理池~~ → **已提升至 P0.1-A38 (ProxyPoolManager)** | — | — |
| ~~P3-06~~ | ~~本地 FinBERT NLP~~ → 已合并至 P2-19~P2-21 | distill | — |
| P3-07 | GenericExtraction Schema | dataclean | 0.5 天 |
| P3-08 | 热门股/一日游识别 | ml | 2 天 |
| P3-09 | 行业轮动引擎 | sectorwatch | 3 天 |
| P3-10 | 宏观经济引擎 | macrotrack | 3 天 |

### P4: 全栈可观测性 → [详见 TODO-P4.md](TODO-P4.md)

| # | 任务 | 模块 | 工作量 |
|---|------|------|--------|
| **P4-01** | **OpenTelemetry SDK 链路追踪埋点** | **common** | **2 天** |
| **P4-02** | **Prometheus 业务指标埋点** | **common / api** | **2 天** |
| **P4-03** | **结构化日志 → Loki 管线 (structlog)** | **common** | **1.5 天** |
| **P4-04** | **Grafana 看板 (4 张)** | **ops** | **3 天** |
| **P4-05** | **告警管线 (Alertmanager → 飞书)** | **ops** | **1.5 天** |
| **P4-06** | **基础设施部署 (Docker Compose)** | **ops** | **1.5 天** |
| **P4-07** | **collect_metrics 持久化 ORM** | **datacollect** | **0.5 天** |

---

## 核心技术栈一览

| 类别 | 技术 | 版本 | 最新状态 (2026.04审计) | 用途 |
|------|------|------|---------|------|
| **ML 框架** | LightGBM | >=4.6 | ✅ 最新4.6.0 (2025.02) | 主模型 |
| | XGBoost | **>=3.0** | ✅ 最新3.2.0 (2026.02) ⚠️ 2.x→3.x | Ensemble |
| | CatBoost | >=1.2.10 | ✅ 最新1.2.10 (2026.02) | Ensemble |
| **ML 工具** | shap | >=0.51 | ✅ 最新0.51.0 (2026.03) | 可解释性 |
| | mlflow | **>=3.0** | ✅ 最新3.10.1 (2026.03) ⚠️ 2.x→3.x | 实验管理 |
| | scikit-learn | >=1.7 | ✅ 最新1.8.0 (2025.12) | CV/Pipeline |
| **自动迭代** | Thompson Sampling (自研) | - | - | Bandit 因子/模型方向选择 (借鉴 RD-Agent) |
| | Trace (自研) | - | - | 实验历史记忆链 + 智能过滤 (借鉴 RD-Agent) |
| **组合优化** | CLA (自研) | - | - | CAA 核心: Critical Line Algorithm (Keller 2015) |
| | skfolio | **>=0.15** | ✅ 最新0.15.7 (2026.03) | 组合优化 (sklearn 兼容, 100+模型) |
| | cvxpy | >=1.5 | ✅ | 凸优化求解 |
| **数据采集** | curl_cffi | **>=0.14** | ✅ 最新0.15.0 (+HTTP/3指纹) | TLS 指纹伪装 |
| | Playwright | **>=1.59** | ✅ 最新1.59.1 (2026.04) | 浏览器采集 |
| | akshare | >=1.18 | ✅ 最新1.18.49 | A股免费数据 |
| | tavily-python | >=0.5 | ✅ 2026.03 | 搜索 API |
| **因子** | jqdatasdk | >=1.9 | ✅ | 聚宽因子库 (可选) |
| | jqfactor_analyzer | >=2.4 | ✅ 2025 | 聚宽因子分析 (可选) |
| **LLM** | openai SDK | **>=2.0** | ✅ 最新2.30.0 (2026.03) ⚠️ 1.x→2.x | DeepSeek/Qwen 统一客户端 |
| | pydantic | >=2.6 | ✅ | Schema 定义 |
| **NLP** | FinBERT2 | 2025 | ✅ 最新 | 中文金融情感 |
| | transformers | **>=5.0** | ✅ 最新5.5.0 (2026.04) ⚠️ 4.x→5.x | HuggingFace 推理 |
| **蒸馏** | setfit | >=1.1 | ✅ 2026 | 冷启动 (8样本/类) |
| | peft (LoRA) | **>=0.18** | ✅ 最新0.18.1 (2026.01) | 参数高效微调 (+EVA/hot-swap) |
| | trl (DPO) | **>=1.0** | ✅ 最新1.0.0 (2026.03) ⚠️ 0.x→1.0 | 偏好对齐训练 (+GRPO/DPPO) |
| | onnxruntime | >=1.21 | ✅ 最新1.21.1 (2025.04) | 跨平台推理部署 |
| **调度** | APScheduler | >=3.11 (stable) | ✅ 稳定3.11.2 (4.0仍alpha) | 定时采集 |
| **事件** | blinker | >=1.9 | ✅ | 模块解耦 (P1-23) |
| **容错** | tenacity | >=9.0 | ✅ | 重试+熔断 (P1-25) |
| **日志** | structlog | >=25.1 | ✅ | 结构化日志 (P4-03) |
| **链路追踪** | opentelemetry-sdk | >=1.30 | ✅ | 分布式追踪 (P4-01) |
| | opentelemetry-exporter-otlp | >=1.30 | ✅ | OTLP → Jaeger (P4-01) |
| **指标** | prometheus_client | >=0.21 | ✅ | Prometheus 埋点 (P4-02) |
| **可观测基础设施** | Jaeger | v2.14+ | ✅ | 链路追踪 (P4-06) |
| | Loki | 3.6+ | ✅ | 日志聚合 (P4-06) |
| | Prometheus | latest | ✅ | 指标存储 (P4-06) |
| | Grafana | 12.4+ | ✅ | 统一看板 (P4-06) |
| | Alertmanager | latest | ✅ | 告警路由 (P4-05) |
| **数据质量** | pandera | >=0.23 | ✅ | DataFrame schema 校验 (P1-24) |
| **数据新鲜度** | exchange_calendars | >=4.5 | ✅ | A 股交易日历 (A27) |
| **异步 DB** | asyncpg | >=0.30 | ✅ | PostgreSQL 异步驱动 + COPY 协议 (A34) |
| **异步限流** | aiolimiter | >=1.2 | ✅ | Leaky Bucket 异步限流器 (A32 可选) |
| **数据库** | PostgreSQL | >=16 | ✅ | JSONB 存储 |
| | SQLAlchemy | >=2.0 | ✅ 稳定2.0.48 (2.1.0b1已发布) | ORM |
| | Alembic | >=1.15 | ✅ | DB schema 迁移 (已部署) |
| **统计** | statsmodels | >=0.14 | ✅ 最新0.14.6 | 回归/中性化 |
| | scipy | >=1.15 | ✅ 最新1.17.1 (2026.02) | 统计检验 |
| **基础** | pandas | **>=2.2 (兼容3.0)** | ✅ 最新3.0.2 (2026.03) ⚠️ 3.0需Python≥3.11 | 数据处理核心 |
| | numpy | **>=2.0** | ✅ 最新2.4.4 (2026.03) ⚠️ 1.x→2.x | 向量化运算 |
| | torch | >=2.8 | ✅ 最新2.9.1 (2026.02) | 深度学习训练 |

---

## 对标参考项目

| 项目 | Star | 说明 | 链接 |
|------|------|------|------|
| **Microsoft Qlib** | ~40k | AI 量化投资平台，统一管道设计标杆 (v0.9.7, 2025.08) | [github.com/microsoft/qlib](https://github.com/microsoft/qlib) |
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
| **Qlib Alpha158** | (Qlib 内置) | 158 个 A 股量价因子, IC 0.02-0.04, 10+模型验证 | [github.com/microsoft/qlib (handler.py)](https://github.com/microsoft/qlib/blob/main/qlib/contrib/data/handler.py) |
| **JoinQuant jqfactor_analyzer** | 130+ | 聚宽因子分析工具 (IC/分组回测/因子合成) | [github.com/JoinQuant/jqfactor_analyzer](https://github.com/JoinQuant/jqfactor_analyzer) |
| **FactorEngine (2026.03)** | - | LLM 引导程序级因子挖掘, SOTA IC/ICIR | [arXiv:2603.16365](https://arxiv.org/abs/2603.16365) |
| **NVIDIA Financial Distillation** | 41 | 生产级金融蒸馏蓝图 (Data Flywheel, 49-70B→1-8B, 98%降本) | [github.com/NVIDIA-AI-Blueprints/ai-model-distillation-for-financial-data](https://github.com/NVIDIA-AI-Blueprints/ai-model-distillation-for-financial-data) |
| **ODA-Fin** | - | 难度感知金融蒸馏, 8B 超越同规模 SOTA (arXiv:2603.07223) | [arxiv.org/abs/2603.07223](https://arxiv.org/abs/2603.07223) |
| **TensorZero** | 7.3k+ | LLMOps 平台, 程序化策展+微调 5-30x 降本 | [github.com/tensorzero/tensorzero](https://github.com/tensorzero/tensorzero) |
| **SetFit** | 2.2k+ | 少样本学习框架, 8样本/类达 RoBERTa-Large 水平 | [github.com/SetFit/setfit](https://github.com/SetFit/setfit) |
| **Bailey & López de Prado (2014)** | - | Deflated Sharpe Ratio, 多重检验修正标杆 | *Journal of Portfolio Management* 2014 |
| **Pandera** | 3.5k+ | DataFrame schema 校验 (Pydantic 风格) | [pandera.readthedocs.io](https://pandera.readthedocs.io/) |

---

## 建议执行顺序

```
Phase 0 — ✅ 已完成 (Bug 修复 + 基础设施)

Phase 0.1 — ✅ 已完成 (数据采集 + 清洗):
  A01~A38   datacollect 48 项全部完成 (HTTP客户端/限流/反爬/架构/高性能)
  P0-12~20  dataclean 9 项全部完成 (LLM客户端/Schema/清洗器/Prompt/Config)

Phase 1 (第 5-9 周):
  ★ P1-27~28  标的池分类 + 交易规则引擎 + UniverseProvider (A股/港股/ETF/两融, 最优先)
  P1-29     策略自动发现与注册 (OCP, 0.5天)
  P1-30     BaseFactor ABC + FactorRegistry (因子一等公民, P1-21 前置)
  P1-01~02  Purged CV + Walk-Forward 重训练 (含 Regime-Aware)
  P1-05~06  组合优化 + 风险归因
  P1-08~11  datacollect 完善 (路由/OpenClaw/调度)
  P1-12~15  dataclean 完善 (扩展Schema/注册表)
  P1-16~19  sentiment 完善 (合成指数/分类器/Profile集成)
  P1-20     ETF 全球资产轮动策略 (含幸存者偏差处理)
  P1-21     多源因子管线 (Alpha158+迅投+自动筛选)
  P1-22     Deflated Sharpe Ratio / 多重检验修正
  P1-23     轻量级事件总线 (blinker, 模块解耦)
  P1-24     数据质量监控 + Pandera Schema 校验
  P1-25     系统级容错 & 降级 (Tenacity/熔断)
  P1-31     FactorPool 版本追溯 (0.5天)

Phase 2 (第 9-13 周):
  P1-03~04  因子/模型监控 (含因子拥挤度检测)
  P1-07     换手率约束
  P2-01~03  量化增强 (滑点/XGB/绩效)
  P2-05~06  交易成本归因 + 多周期标签
  P2-07~14  采集+清洗+情绪高级功能
  P2-15~17  扩展引擎 (个股雷达/资金/风险)
  P2-18     RD-Agent 式自动因子-模型联合迭代 (Bandit+Trace+IC去重)
  P2-19~21  知识蒸馏 (多教师共识标注/LoRA分层训练/数据飞轮部署)
  P2-22     配置管理迁移 (.env → TOML 分层)

Phase 3 (第 14 周+):
  P3-01~10  按需选择实现 (SHAP/MLflow/数据版本化/行业轮动/宏观)

Phase 4 — 全栈可观测性 (与其他 Phase 并行推进):
  P4-03     structlog 结构化日志 (可提前, 无外部依赖)
  P4-07     collect_metrics ORM (可提前)
  P4-01~02  OpenTelemetry + Prometheus 埋点
  P4-06     Docker Compose 基础设施部署 (Jaeger/Loki/Prometheus/Grafana)
  P4-04~05  Grafana 看板 + 告警规则
```
