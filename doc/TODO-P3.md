# P3: 长期 (可选优化 + 远期规划)

> 最后更新: 2026-04-14
>
> 9 + 2 项 (含代码审查发现) (P3-03 已提升至 P1-23, P3-06 已合并至 P2-19~P2-21) | 预估工作量 ~14 + ~2 天
>
> 返回总览: [TODO.md](TODO.md)

---

## 代码审查发现 — 长期改进 (2026-04-14)

### P3-R01: 配置管理从 .env 迁移到分层配置

| 属性 | 内容 |
|------|------|
| **文件** | `src/common/config.py`, `.env` |
| **工作量** | — |
| **关联** | **P2-22 (配置管理迁移)** |

当前 60+ 参数平铺在 `.env`, 随新模块增长将膨胀到 100+。JSON 字符串默认值 (如 `risk_pool`)、逗号分隔列表 (如 `xt_categories`) 类型安全弱。此问题将在 P2-22 实施时系统性解决。

---

### P3-R02: 测试基础设施增强

| 属性 | 内容 |
|------|------|
| **文件** | `tests/`, `pyproject.toml` |
| **工作量** | 2 天 |

审查发现以下测试改进方向:
- 单元测试覆盖率不均: `strategy/`, `portfolio/`, `backtest/` 模块测试偏薄
- E2E 测试的 `conftest.py` 修改 ORM `table.schema` 全局状态, 导致多测试文件同时运行时互相干扰。长期应改为 fixture-scoped schema 或独立测试数据库
- 缺少集成测试层: 端到端过重、单元太细, 需中间层验证模块间协作

---

### P3-01: SHAP 可解释性

| 属性 | 内容 |
|------|------|
| **模块** | ml |
| **文件** | `src/ml/lgb_model.py` 或新增 `explainability.py` |
| **工作量** | 1 天 |

**为什么要做:**
LGB 的 `feature_importance(gain)` 只告诉你 "哪个因子重要"，但不告诉你 "重要性方向" 和 "对单只股票的预测贡献"。SHAP 可以:
- **全局**: 哪些因子最影响预测？方向如何？(Summary Plot)
- **局部**: 这只股票被预测为涨，主要因为哪些因子？(Waterfall Plot)
- **因子选择**: SHAP 值可以替代 IC 做更精准的因子筛选

2025 年研究证实: SHAP 选出 Top-5 因子重训 LGB → 等权组合跑赢大盘。

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| **shap** | >=0.51 | ✅ 2026最新0.51.0 (+pandas 3.0兼容) | `TreeExplainer` 对 LGB 有原生优化，O(TLD) 复杂度 |

**参考文档:**
- SHAP 官方: [github.com/shap/shap](https://github.com/shap/shap)
- [SHAP Values Python Guide (2026)](https://pythondatabench.com/article/shap-values-python-practical-guide-explaining-ml-models)
- [Stock Return Forecasting Using SHAP (2025 论文)](https://www.atlantis-press.com/proceedings/iciaai-25/126015307)
- [Interpreting LightGBM with SHAP](https://toxigon.com/interpreting-lightgbm-models-with-shap-values)
- [interpretable-lightgbm 工具库](https://github.com/ccomkhj/interpretable-lightgbm)

**落地方案:**
```python
import shap

explainer = shap.TreeExplainer(lgb_model)
shap_values = explainer.shap_values(X_test)

# 全局特征重要性
shap.summary_plot(shap_values, X_test, feature_names=factor_names)
# 单只股票归因
shap.waterfall_plot(shap.Explanation(shap_values[0], base_values=explainer.expected_value))
```

---

### P3-02: 实验管理 (MLflow + Trace 模式)

| 属性 | 内容 |
|------|------|
| **模块** | ml |
| **文件** | 新增 `src/ml/experiment_tracker.py` |
| **工作量** | 2 天 (含 Trace 模式) |

**为什么要做:**
当前 ML 迭代没有实验追踪 — 无法回答 "上次用哪个因子组合、什么超参、训练了多长时间、结果如何"。每次迭代结果丢失，重复实验浪费算力。

**业界最佳实践:**

#### 方案 A: MLflow (业界标准)
- **MLflow**: Apache 2.0 开源，支持自部署。2026 年最新版支持 PostgreSQL 后端 + S3 artifact 存储
- **核心功能**: 记录超参 (LR, num_leaves, max_depth) → 记录指标 (IC, ICIR, Sharpe) → 存储模型 artifact → Model Registry 管理模型版本
- **2026 金融应用**: [Financial Market Intelligence Platform](https://github.com/cdobratz/market-intelligence-mvp) 使用 MLflow + Airflow + FastAPI 的完整管道

#### 方案 B: Trace 模式 (借鉴 RD-Agent) ⭐

微软 RD-Agent 设计了一套轻量级 **Trace (实验历史记忆)** 模式，比 MLflow 更贴合我们的迭代场景:

```python
class Trace:
    """实验历史记忆链: [(Experiment, HypothesisFeedback), ...]"""
    hist: list[tuple[Experiment, Feedback]]
    scen: Scenario

class Experiment:
    hypothesis: Hypothesis       # 本次实验的假设 ("尝试加入换手率因子")
    sub_tasks: list[Task]        # 具体实现任务
    result: pd.Series | None     # 8 维指标 (IC, ICIR, Sharpe 等)
    based_experiments: list[Experiment]  # 基于哪些先前实验

class HypothesisFeedback:
    decision: bool               # 本次假设是否被验证通过
    reason: str                  # 分析 (LLM 或规则生成)
    observations: str            # 关键观察
```

**Trace 智能过滤 (RD-Agent 核心设计):**
不是把所有历史都保留/传递，而是按当前任务类型过滤:
- **做因子时**: 保留全部因子实验 + 仅保留最新一个成功的模型实验
- **做模型时**: 保留全部模型实验 + 仅保留最新一个成功的因子实验
- 这样既提供了上下文，又避免了历史膨胀

**推荐**: 先实现 Trace 模式 (轻量，1 天)，再选择性集成 MLflow (重量级，需要部署)。Trace 可以序列化为 pickle/JSON 存储在 PostgreSQL 中。

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| **mlflow** | >=3.0 | ✅ 2026最新3.10.1 (**2.x→3.x大版本**, +AI自动诊断/Pickle-free) | 核心: tracking + model registry |
| **Trace (自研)** | - | - | 借鉴 RD-Agent 的轻量实验历史链 |
| sqlite (轻量) 或 PostgreSQL | - | - | MLflow 后端存储 |

**参考文档:**
- **RD-Agent Trace 架构**: `rdagent/core/proposal.py` (`Trace` 类), `rdagent/scenarios/qlib/proposal/quant_proposal.py` (智能过滤)
- MLflow 官方: [mlflow.org](https://mlflow.org/)
- [MLflow 完整指南 (2026.03)](https://www.marktechpost.com/2026/03/01/a-complete-end-to-end-coding-guide-to-mlflow-experiment-tracking/)
- [MLflow Production Guide (2026.03)](https://www.youngju.dev/blog/ai-platform/2026-03-07-ai-platform-mlflow-experiment-tracking-model-registry.en)
- [MLflow Experiment Tracking Tutorial (2026)](https://oneuptime.com/blog/post/2026-01-27-mlflow-experiment-tracking/view)

---

### ~~P3-03: 轻量级事件总线~~ → **已提升至 P1-23**

> 此任务因架构审查发现其为多模块协作的基础设施, 已提升至 P1-23。
> 详见 [TODO-P13.md](TODO-P13.md) P1-23。

---

### P3-04: 数据版本化

| 属性 | 内容 |
|------|------|
| **模块** | data |
| **文件** | `src/data/` |
| **工作量** | 2 天 |

**为什么要做:** 确保回测可复现 — 同一份因子数据 + 同一个模型 = 相同的回测结果。数据更新后需要保留历史快照。

---

### P3-05: ProxyPool 代理池

| 属性 | 内容 |
|------|------|
| **文件** | `src/datacollect/proxy_pool.py` |
| **工作量** | 1 天 |

**为什么要做:** 当 IP 被封禁时的最后手段。curl_cffi + 居民代理可将成功率从 82% 提升到 91%。

**参考:** [How to Bypass Akamai Bot Detection 2026](https://dev.to/vhub_systems_ed5641f65d59/how-to-bypass-akamai-bot-detection-in-2026-curl-cffi-residential-proxies-5h3k)

---

### ~~P3-06: 本地 FinBERT NLP~~ → 已合并至 P2-19~P2-21

> **状态: 已合并**
>
> 原 P3-06 设计为"直接部署 FinBERT 替代 LLM API"。该方案已升级为完整的知识蒸馏模块
> (多教师共识标注 + LoRA 分层训练 + 数据飞轮)，编号 P2-19~P2-21，优先级从 P3 提升至 P2。
>
> 详见: [TODO-P2.md — P2-19~P2-21](TODO-P2.md#p2-19--p2-21-知识蒸馏模块-llm-教师--轻量学生模型)

---

### P3-07: GenericExtraction Schema

| 属性 | 内容 |
|------|------|
| **文件** | `src/dataclean/schemas/generic.py` |
| **工作量** | 0.5 天 |

通用自定义清洗模板，用户可定义任意抽取字段。

---

### P3-08: 热门股/一日游识别模型

| 属性 | 内容 |
|------|------|
| **文件** | `src/sentiment/` 或 `src/ml/` |
| **工作量** | 2 天 |

**为什么要做:** A 股短线最大陷阱是 "一日游" (今天涨停明天砸盘)。量化识别特征:
- 量化席位占比 > 50% + 游资 < 20%
- 封成比 < 0.5 + 换手率 > 15%
- 板块涨停 < 3 只
- 无基本面驱动

**落地:** LGB 二分类 (目标: 次日跌幅 ≥ 2%)，RPS + 封板质量 + 板块联动 + 资金结构作为特征。

---

### P3-09 ~ P3-10: 远期扩展引擎

| # | 引擎 | 描述 | 路径 | 工作量 |
|---|------|------|------|--------|
| P3-09 | sectorwatch | 行业轮动/政策驱动 → 行业配置 | `src/sectorwatch/` | 3 天 |
| P3-10 | macrotrack | GDP/CPI/PMI/利率 → 长期趋势 | `src/macrotrack/` | 3 天 |

---
