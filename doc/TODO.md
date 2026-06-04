# qt-quant 综合待办清单 (索引)

> 最后更新: 2026-04-21
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
| ~~**P1.1**~~ | ✅ 已完成 | ~~11 项~~ | ~~22 天~~ | 系统风险 — 交易规则/标签泄露/过拟合/因子失效/容错降级 — **全部完成** |
| ~~**P1.2**~~ | ✅ 已完成 | ~~14 项~~ | ~~41 天~~ | 赚钱效应 ROI — ETF 轮动/多源因子/组合优化/情绪引擎/择时信号 — **全部完成** |
| ~~**P1.3**~~ | ✅ 代码审查 17 项已完成; 5 项特性迁入 P2 (P2-32~36) | ~~17+5 项~~ | ~~9 天~~ | 工程化 — 手续费/认证/前视偏差/CORS/并发/CI-CD/锁文件/分层/readonly/类型安全/索引/asyncio/SQL安全/模块边界/覆盖率/依赖去重 — **全部完成** |
| **P2** | [TODO-P2.md](TODO-P2.md) | 36 项 | ~81 天 | 高级功能 + 扩展引擎 + RD-Agent(⭐提升) + 知识蒸馏 + TOML 配置 + **AI Agent 前沿** + P1.3 迁入 (事件总线/自动注册/版本追溯/datacollect+dataclean 完善) |
| **P3** | [TODO-P3.md](TODO-P3.md) | 9 项 | ~14 天 | 长期可选 (SHAP/行业轮动/宏观经济) |
| **P4** | [TODO-P4.md](TODO-P4.md) | 7 项 | ~12 天 | **全栈可观测性** (Jaeger/Loki/Prometheus/Grafana/Alert, 参考 fliac ops03) |
| **合计** | — | **52 项** (剩余) | **~107 天** | P0 + P0.1 + P1.1 + P1.2 + P1.3 代码审查已完成, 其余待实施 |

**专项待办 (独立成文，未计入上表项数):**

| 说明 | 文档 |
|------|------|
| 日K 多线程补全（多标的）、分线程反爬/请求隔离 | [TODO-daily-kline-threadpool.md](TODO-daily-kline-threadpool.md) |
| 8×A100 GPU 节点落地（训练/推理/资源配额） | [TODO-A100.md](TODO-A100.md) |

---

## 当前代码现状

**已实现** (`src/` 中已存在代码):

| 模块 | 路径 | 状态 |
|------|------|------|
| 策略引擎 | `src/strategy/` | 11 策略 + ETF 轮动 + orchestrator + monitor + arbiter + sizer (ATR/CAA/RiskParity) |
| 数据下载 | `src/data/` | QMT 数据下载引擎 + models + universe_manager (PIT) + limit_status |
| 因子工程 | `src/factor/` | BaseFactor ABC + FactorRegistry + Alpha158 (158 因子) + 自动筛选 + 质量门控 + 预处理 + IC 分析 |
| 机器学习 | `src/ml/` | LGB + 自动迭代 + Rolling Walk-Forward + Thompson Bandit + 评估 + 预处理 |
| 回测引擎 | `src/backtest/` | OrchestratorBacktester (统一管道) + 涨跌停/停牌模拟 + 绩效 |
| 情绪引擎 | `src/sentiment/` | ORM (JSONB) + 量价情绪 + 合成指数 (8 维) + 宏观分类器 + 北向资金 + 跨资产 Regime + Profile + API |
| 组合优化 | `src/portfolio/` | CAAOptimizer + RiskParityOptimizer + RiskAttributor (简化 Barra) |
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
| **标的池分类/交易规则** | `src/strategy/trading_rules.py` | ✅ P1-27 已完成 |
| **UniverseProvider** | `src/data/universe_provider.py` | ✅ P1-28 已完成 |
| **知识蒸馏** | `src/distill/` | [TODO-P2.md P2-19~P2-21](TODO-P2.md#p2-19--p2-21-知识蒸馏模块-llm-教师--轻量学生模型) |
| **LLM 因子挖掘** | `src/factor/llm_mining/` (新增) | [TODO-P2.md P2-23](TODO-P2.md#p2-23-llm-进化式因子挖掘-quantaalpha-风格) |
| **RAG 投研知识库** | `src/research/` (新增) | [TODO-P2.md P2-25~P2-27](TODO-P2.md#p2-25-rag-投研知识库) |
| **AI 新闻情报** | `src/sentiment/news_intelligence.py` (新增) | [TODO-P2.md P2-29](TODO-P2.md) |
| **论文→策略进化** | `src/research/paper_reader.py` (新增) | [TODO-P2.md P2-30](TODO-P2.md) |
| **LLM 择时** | `src/strategy/llm_param_tuner.py` (新增) | [TODO-P2.md P2-31](TODO-P2.md) |

---

## 任务速查表

### ~~P0: 紧急 Bug 修复 + 核心量化 + 基础设施~~ — ✅ 全部完成

> P0 全部 12 项已实现并通过 642 个单元测试验证 (2026-04-10)。
> 包括: ATR 仓位接入、行业中性化、预处理接通、OrchestratorBacktester 统一回测管道、
> 情绪引擎 (ORM/量价/Profile/API)、PIT 数据管理、CI/CD、Alembic、涨跌停模拟。

### ~~P0.1: 数据采集 + 数据清洗~~ ✅ 全部完成

> - **数据采集** (A01-A48, 48 项): 全部完成 → [12-数据采集模块.md](12-数据采集模块.md#实现完成总览-48-项-全部-)
> - **数据清洗** (P0-12~P0-20, 9 项): 全部完成 → [13-数据清洗与LLM.md](13-数据清洗与LLM.md#实现完成总览-p0-12--p0-20-全部-)

### ~~P1.1: 系统风险~~ ✅ 全部完成

> 11 项全部实施完毕, 含 E2E 测试 (`tests/e2e/system_risk/`, 82 tests)。
>
> 涵盖: 交易规则引擎 (P1-27) | UniverseProvider (P1-28) | Purged CV (P1-01) | 分数 Kelly + DrawdownGuard (P1-32) | Regime 门控 (P1-35) | 换手率约束 (P1-07) | 因子衰减监控 (P1-03) | 模型漂移检测 (P1-04) | Deflated Sharpe Ratio (P1-22) | 数据质量 + Pandera (P1-24) | 系统容错 & 降级 (P1-25)

### ~~P1.2: 赚钱效应 ROI~~ ✅ 全部完成

> 14 项全部实施完毕, 含 E2E 测试 (`tests/e2e/`):
>
> 涵盖: ETF 全球资产轮动 (P1-20) | 多源因子管线 Alpha158+自动筛选 (P1-21) | 组合优化器 CAA+RiskParity (P1-05) | 风险归因 Barra 简化 (P1-06) | Rolling Walk-Forward+Bandit (P1-02) | BaseFactor+FactorRegistry (P1-30) | 6 维情绪合成指数 (P1-16) | 宏观状态分类器 (P1-17) | Orchestrator 集成 Profile (P1-18) | 情绪 API 完整化 (P1-19) | 北向资金流 Regime 信号 (P1-33) | alphalens 因子质量门控 (P1-34) | 风险平价优化 (P1-36) | 跨资产 Regime 上下文 (P1-37)

### ~~P1.3: 工程化 (再次之)~~ ✅ 代码审查全部完成

> **代码审查发现 17 项** (3 CRITICAL + 4 HIGH + 8 MEDIUM + 2 LOW) 已全部实现并通过 E2E 测试:
>
> ✅ 回测手续费参数错位 | ✅ API Key 认证中间件 | ✅ 因子中性化前视偏差 |
> ✅ CORS 收紧 | ✅ 并发安全 | ✅ CI/CD GitHub Actions | ✅ uv.lock 锁文件 |
> ✅ data→strategy 分层违反 | ✅ get_session readonly | ✅ JSON→list 类型安全 |
> ✅ 密钥启动校验 | ✅ TradeOrder 复合索引 | ✅ asyncio 弃用 API |
> ✅ bulk_writer 表名白名单 | ✅ sentiment_bridge 模块边界 | ✅ fail_under=85 |
> ✅ dev 依赖去重
>
> **5 项未实现特性已迁入 P2**: P2-32 (datacollect 完善) | P2-33 (dataclean 完善) | P2-34 (事件总线) | P2-35 (策略自动注册) | P2-36 (FactorPool 版本追溯)
>
> ~~P1-26 可观测性~~ → 已合并至 P4

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
| **P2-18** | **⭐ LLM 驱动因子-模型联合迭代 (RD-Agent, 建议提升至 P1.2)** | **ml** | **5 天** |
| P2-19 | 多教师共识标注管线 (知识蒸馏) | distill | 2.5 天 |
| P2-20 | 学生模型分层训练 (SetFit+LoRA+DPO) | distill | 3 天 |
| P2-21 | 数据飞轮 + 生产部署 (ONNX) | distill | 2.5 天 |
| **P2-22** | **配置管理迁移 (.env → TOML 分层)** | **common** | **2 天** |
| **P2-23** | **⭐ LLM 进化式因子挖掘 (QuantaAlpha+FactorMiner, 建议与P2-18同批)** | **factor** | **5 天** |
| **P2-24** | **因子 Embedding 去重与经验记忆** | **factor** | **2 天** |
| **P2-25** | **RAG 投研知识库** | **research** | **4 天** |
| **P2-26** | **FinBERT2 + Qwen 双塔检索/生成** | **research** | **3 天** |
| **P2-27** | **多智能体投研架构 (TradingAgents+OpenClaw+Hermes)** | **research** | **5 天** |
| **P2-28** | **PPO 自适应 Alpha 动态加权** | **ml** | **3 天** |
| **P2-29** | **AI 新闻情报深度解读 Agent** | **sentiment** | **3 天** |
| **P2-30** | **论文阅读 → 策略/因子进化 Agent** | **research/factor** | **5 天** |
| **P2-31** | **LLM 择时参数自适应 (TiMi 范式)** | **strategy** | **3 天** |

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
| | Riskfolio-Lib | **>=7.2** | ✅ | 战术配置 + 风险预算 + 24+ 凸风险度量 (P1-36) |
| | PyPortfolioOpt | >=1.5 | ✅ | HRP / Black-Litterman (可选) |
| | cvxpy | >=1.5 | ✅ | 凸优化求解 |
| **数据采集** | curl_cffi | **>=0.14** | ✅ 最新0.15.0 (+HTTP/3指纹) | TLS 指纹伪装 |
| | Playwright | **>=1.59** | ✅ 最新1.59.1 (2026.04) | 浏览器采集 |
| | akshare | >=1.18 | ✅ 最新1.18.49 | A股免费数据 |
| | tavily-python | >=0.5 | ✅ 2026.03 | 搜索 API |
| **因子** | jqdatasdk | >=1.9 | ✅ | 聚宽因子库 (可选) |
| | jqfactor_analyzer | >=2.4 | ✅ 2025 | 聚宽因子分析 (可选) |
| | alphalens-reloaded | >=0.0.14 | ✅ | 因子 IC/分层/换手标准分析 (P1-34) |
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
| **TradingAgents** | 49k+ | 多角色 LLM 交易智能体 (基本面/情绪/技术/辩论/风控) | [github.com/TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) |
| **OpenBB** | 65k+ | 金融数据与 AI Agent 工作台 (多源统一接口) | [github.com/OpenBB-finance/OpenBB](https://github.com/OpenBB-finance/OpenBB) |
| **FinRL** | 14k+ | 金融强化学习框架 (Gym 环境 + DRL 训练) | [github.com/AI4Finance-Foundation/FinRL](https://github.com/AI4Finance-Foundation/FinRL) |
| **vectorbt** | 7k+ | 极速向量化回测与参数扫描 | [github.com/polakowo/vectorbt](https://github.com/polakowo/vectorbt) |
| **Riskfolio-Lib** | 4k+ | 战术资产配置 + 24+ 凸风险度量 + 风险预算 | [github.com/dcajasn/Riskfolio-Lib](https://github.com/dcajasn/Riskfolio-Lib) |
| **PyPortfolioOpt** | 5.6k+ | HRP / Black-Litterman / 协方差压缩 | [github.com/robertmartin8/PyPortfolioOpt](https://github.com/robertmartin8/PyPortfolioOpt) |
| **alphalens** | 4.2k+ | 因子 IC/分层/换手分析 (Quantopian 标准) | [github.com/quantopian/alphalens](https://github.com/quantopian/alphalens) |
| **AKShare** | 18k+ | A 股免费数据 (含北向/融资/宏观) | [github.com/akfamily/akshare](https://github.com/akfamily/akshare) |
| **QuantaAlpha (2026)** | 640+ | LLM 进化式 Alpha 因子挖掘 (CSI 300 IC=0.15) | [arXiv:2602.07085](https://arxiv.org/abs/2602.07085) |
| **ATLAS (2026)** | - | Adaptive-OPRO 多智能体交易 (动态 prompt 优化) | [arXiv:2510.15949](https://arxiv.org/abs/2510.15949) |
| **FactorMiner (2026)** | - | 技能+经验记忆因子挖掘 (embedding 去重) | [arXiv:2602.14670](https://arxiv.org/abs/2602.14670) |
| **Alpha-R1 (2026)** | - | RL + 推理模型做情境化因子筛选 | [arXiv:2512.23515](https://arxiv.org/abs/2512.23515) |
| **Fin-R1** | - | Qwen2.5-7B + RL 中文金融推理 (SUFE Lab) | GitHub: SUFE-AIFLM-Lab/Fin-R1 |
| **FinGPT** | 14k+ | 开源金融 LLM 生态 (LoRA 适配) | [github.com/AI4Finance-Foundation/FinGPT](https://github.com/AI4Finance-Foundation/FinGPT) |
| **Hermes Agent** | - | 持久记忆 + 自动技能沉淀 + 越用越强 (Nous Research) | [hermes-agent.nousresearch.com](https://hermes-agent.nousresearch.com/) |
| **OpenClaw** | - | 多智能体编排 + Plugin SDK + 向量记忆 | [github.com/OpenClaw](https://github.com/openclaw) |
| **TiMi** | - | 数学反思 + LLM 策略参数调优 (微软 2026) | [Microsoft Research](https://www.microsoft.com/en-us/research/publication/trade-in-minutes/) |

---

## 建议执行顺序

```
Phase 0 — ✅ 已完成 (Bug 修复 + 基础设施)

Phase 0.1 — ✅ 已完成 (数据采集 + 清洗):
  A01~A38   datacollect 48 项全部完成 (HTTP客户端/限流/反爬/架构/高性能)
  P0-12~20  dataclean 9 项全部完成 (LLM客户端/Schema/清洗器/Prompt/Config)

Phase 1a — P1.1 系统风险 (第 5-7 周, 最优先):
  ★ P1-27~28  标的池分类 + 交易规则引擎 + UniverseProvider (A股/港股/ETF/两融)
  P1-32     分数 Kelly + 回撤自适应仓位 (1.5天, 直接提升风控)
  P1-35     Regime 门控信号过滤 (2天, 策略信号精细化)
  P1-01     Purged Walk-Forward CV (防标签泄露)
  P1-03~04  因子衰减 + 模型漂移监控
  P1-07     换手率约束
  P1-22     Deflated Sharpe Ratio / 多重检验修正
  P1-24     数据质量监控 + Pandera Schema 校验
  P1-25     系统级容错 & 降级 (Tenacity/熔断)

Phase 1b — ✅ P1.2 赚钱效应 ROI — 已完成:
  ✅ P1-30  BaseFactor ABC + FactorRegistry
  ✅ P1-33  北向资金流 Regime 信号
  ✅ P1-34  alphalens 因子质量门控
  ✅ P1-02  Rolling Walk-Forward 重训练 + Bandit
  ✅ P1-05  组合优化 (CAA + RiskParity)
  ✅ P1-06  风险归因 (简化 Barra)
  ✅ P1-16  6 维情绪合成指数
  ✅ P1-17  宏观状态分类器
  ✅ P1-18  Orchestrator 集成 Profile
  ✅ P1-19  情绪 API 完整化
  ✅ P1-37  跨资产 Regime 上下文
  ✅ P1-20  ETF 全球资产轮动策略
  ✅ P1-21  多源因子管线 (Alpha158+自动筛选)
  ✅ P1-36  风险平价优化

Phase 1c — ✅ P1.3 工程化 — 代码审查 17 项已完成:
  ✅ 代码审查发现全部修复 (手续费/认证/前视偏差/CORS/并发/CI-CD 等 17 项)
  → 特性任务迁入 P2: P2-32 (datacollect) | P2-33 (dataclean) | P2-34 (事件总线) | P2-35 (策略注册) | P2-36 (版本追溯)

Phase 2a — AI Agent 核心 (第 12-14 周, 最高 ROI):
  ★ P2-18   RD-Agent 联合迭代 (Bandit+Trace, 建议提升至 P1.2 同期, 5天, 年化2x验证)
  ★ P2-23   LLM 进化式因子挖掘 (QuantaAlpha+FactorMiner, 5天, 与P2-18协同)
  P2-24     因子 Embedding 去重 (与 P2-23 协同)
  P2-29     AI 新闻情报深度解读 Agent (3天, 情绪引擎LLM增强)

Phase 2b — 量化增强 (第 14-16 周):
  P2-01~03  量化增强 (滑点/XGB/绩效)
  P2-05~06  交易成本归因 + 多周期标签
  P2-07~14  采集+清洗+情绪高级功能
  P2-15~17  扩展引擎 (个股雷达/资金/风险)
  P2-19~21  知识蒸馏 (多教师共识标注/LoRA分层训练/数据飞轮部署)
  P2-22     配置管理迁移 (.env → TOML 分层)

Phase 2c — AI Agent 进阶 (第 16-18 周):
  P2-25~26  RAG 投研知识库 + FinBERT2 双塔
  P2-30     论文阅读 → 策略/因子进化 Agent (5天, 依赖P2-25)
  P2-27     多智能体投研架构 (TradingAgents+OpenClaw+Hermes, 5天)
  P2-31     LLM 择时参数自适应 (TiMi 范式, 3天, 在P1-35之后)
  P2-28     PPO 自适应 Alpha 加权 (在 P1-35 之后考虑, 远期)

Phase 3 (第 17 周+):
  P3-01~10  按需选择实现 (SHAP/MLflow/数据版本化/行业轮动/宏观)

Phase 4 — 全栈可观测性 (与其他 Phase 并行推进):
  P4-03     structlog 结构化日志 (可提前, 无外部依赖)
  P4-07     collect_metrics ORM (可提前)
  P4-01~02  OpenTelemetry + Prometheus 埋点
  P4-06     Docker Compose 基础设施部署 (Jaeger/Loki/Prometheus/Grafana)
  P4-04~05  Grafana 看板 + 告警规则
```
