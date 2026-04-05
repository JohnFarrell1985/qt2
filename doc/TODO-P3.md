# P3: 长期 (可选优化 + 远期规划)

> 最后更新: 2026-04-04
>
> 10 项 | 预估工作量 ~19 天
>
> 返回总览: [TODO.md](TODO.md)

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
| **shap** | >=0.50.0 | ✅ 2026最新 | `TreeExplainer` 对 LGB 有原生优化，O(TLD) 复杂度 |

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
| **mlflow** | >=2.20 | ✅ 2026活跃 | 核心: tracking + model registry |
| **Trace (自研)** | - | - | 借鉴 RD-Agent 的轻量实验历史链 |
| sqlite (轻量) 或 PostgreSQL | - | - | MLflow 后端存储 |

**参考文档:**
- **RD-Agent Trace 架构**: `rdagent/core/proposal.py` (`Trace` 类), `rdagent/scenarios/qlib/proposal/quant_proposal.py` (智能过滤)
- MLflow 官方: [mlflow.org](https://mlflow.org/)
- [MLflow 完整指南 (2026.03)](https://www.marktechpost.com/2026/03/01/a-complete-end-to-end-coding-guide-to-mlflow-experiment-tracking/)
- [MLflow Production Guide (2026.03)](https://www.youngju.dev/blog/ai-platform/2026-03-07-ai-platform-mlflow-experiment-tracking-model-registry.en)
- [MLflow Experiment Tracking Tutorial (2026)](https://oneuptime.com/blog/post/2026-01-27-mlflow-experiment-tracking/view)

---

### P3-03: 轻量级事件总线

| 属性 | 内容 |
|------|------|
| **模块** | common |
| **文件** | 新增 `src/common/event_bus.py` |
| **工作量** | 3 天 |

**为什么要做:**
当前模块间通过函数调用串联 (采集→清洗→情绪→策略→交易)。如果要新增一个 "数据采集完成后同时触发清洗+个股雷达+风险预警"，需要修改采集模块的代码。事件总线实现 "发布者不知道谁在监听"。

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| **blinker** | >=1.9 | ✅ 2024 | Flask 内部使用的信号库，轻量 |
| **PyPubSub** | >=4.0.7 | ✅ 2025.12 | 话题式发布订阅 |
| asyncio 自研 | Python 内置 | ✅ | 支持异步处理器 |

**参考文档:**
- Blinker: [blinker GitHub](https://github.com/pallets-eco/blinker) + [Python Signals for Decoupling](https://dev.to/recca0120/blinker-python-signals-for-decoupling-modules-441p)
- PyPubSub: [pypubsub.readthedocs.io](https://pypubsub.readthedocs.io/)
- [Event Bus with asyncio in Python (2026)](https://oneuptime.com/blog/post/2026-01-25-event-bus-asyncio-python/view)

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

### P3-06: 本地 FinBERT NLP

| 属性 | 内容 |
|------|------|
| **文件** | `src/dataclean/cleaners/finbert_cleaner.py` |
| **工作量** | 2 天 |

**为什么要做:**
LLM API 有成本和延迟。FinBERT 110M 参数，家用 GPU (GTX 1660+) 或 CPU 即可运行，替代 API 做高频情感分析。

**2025 最新进展: FinBERT2**
- 在 32B token 中文金融语料上预训练 — 最大的中文金融预训练模型
- 分类任务: 比 GPT-4-turbo 和 Claude 3.5 Sonnet 高 9.7%-12.3%
- 检索任务: 比 OpenAI text-embedding-3-large 高 4.2%
- MIT 开源协议

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| **FinBERT2** | 2025 | ✅ 最新 | [valuesimplex/FinBERT](https://github.com/valuesimplex/FinBERT) |
| transformers | >=4.46 | ✅ | HuggingFace 推理框架 |
| torch | >=2.4 | ✅ | GPU/CPU 推理 |

**参考文档:**
- FinBERT2 论文: [arxiv.org/abs/2506.06335](https://arxiv.org/abs/2506.06335)
- FinBERT2 代码: [github.com/valuesimplex/FinBERT](https://github.com/valuesimplex/FinBERT)
- FinBERT 官网: [finbert.org](https://finbert.org/)
- [FinBERT 金融情感分析完整指南 (2025)](https://blog.gitcode.com/573f7b1a41018f183b1d047a1a701979.html)

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
