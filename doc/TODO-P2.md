# P2: 增强 (高级功能 + 扩展引擎 + 研究驱动前沿)

> 最后更新: 2026-04-14
>
> 31 + 10 项 (含代码审查发现) | 预估工作量 ~64 + ~5 天 (P2-04 已完成, P2-22~P2-28 研究驱动前沿, **新增 P2-29~P2-31 AI Agent 应用**)
>
> 返回总览: [TODO.md](TODO.md)

---

## 代码审查发现 — 量化策略/回测/因子 (2026-04-14)

> 三视角审查 (高级量化交易员 + 高级软件工程师) 发现以下量化逻辑问题。
> 部分与已有 P2 项相关, 在此集中列出以便跟踪。

### P2-R01: CAA 优化器目标函数与注释不符

| 属性 | 内容 |
|------|------|
| **文件** | `src/portfolio/optimizer.py` CAAOptimizer |
| **工作量** | 0.5 天 |
| **关联** | P1-05 (已完成) |

`CAAOptimizer._objective` 注释为 "最小化方差", 但实现为最大化 Sharpe (含均值项)。虽然最大化 Sharpe 可能是正确意图, 但注释与代码不一致易误导后续维护。需对齐注释, 并验证无风险利率参数是否传入。

---

### P2-R02: ETF 轮动 13612W 动量除以 4

| 属性 | 内容 |
|------|------|
| **文件** | `src/strategy/etf_rotation/momentum.py` |
| **工作量** | 0.5 天 |
| **关联** | P1-20 (已完成) |

13612W 动量 = (1 月 + 3 月 + 6 月 + 12 月收益率) / 4。这对收益率量级不同的窗口做简单平均, 而非加权平均 (Antonacci 原版对短期窗口给更高权重)。若刻意简化则在注释中说明。

---

### P2-R03: ETF 轮动调仓日近似交易日

| 属性 | 内容 |
|------|------|
| **文件** | `src/strategy/etf_rotation/etf_rotation_strategy.py` |
| **工作量** | 0.5 天 |
| **关联** | P1-20 (已完成) |

`_is_rebalance_day` 用简单日历判断 (月末 / `monthday == N`), 未排除 A 股非交易日。遇到节假日调仓日可能无法正确执行。建议对接交易日历 (如 `exchange_calendars` 或从 DB 查询)。

---

### P2-R04: 风险归因 factor_exposures 横截面含义

| 属性 | 内容 |
|------|------|
| **文件** | `src/portfolio/risk_attribution.py` |
| **工作量** | 0.5 天 |
| **关联** | P1-06 (已完成) |

`_build_factor_exposures` 用 `log(市值)` / `1/PB` 等构造因子暴露。正规 Barra 需要对这些原始值做**截面标准化** (Z-score)。当前实现未标准化, 导致 factor contribution 量纲不一致。

---

### P2-R05: 回测无动态滑点模型

| 属性 | 内容 |
|------|------|
| **文件** | `src/backtest/fees.py`, `src/backtest/engine.py` |
| **工作量** | — |
| **关联** | **P2-01 (滑点模型)** |

当前回测仅有固定费率, 无基于成交量的滑点。此问题将在 P2-01 实施时一并解决, 此处仅作追踪。

---

### P2-R06: 涨跌停处理简化

| 属性 | 内容 |
|------|------|
| **文件** | `src/backtest/engine.py` |
| **工作量** | 0.5 天 |
| **关联** | P2-01 / P2-03 |

回测引擎未检查标的当日是否涨停/跌停。涨停买入 / 跌停卖出在 A 股实际无法成交, 当前回测默认可以成交, 导致回测收益虚高。需增加涨跌停封板检测逻辑。

---

### P2-R07: 动量策略 close[lookback_days-1] off-by-one

| 属性 | 内容 |
|------|------|
| **文件** | `src/strategy/rules/momentum.py` |
| **工作量** | 0.5 天 |

`MomentumBreakout` 用 `close[lookback_days - 1]` 取回看起点。当 `lookback_days=20` 时取 index 19, 但如果序列是按时间倒序排列, 则含义与命名不符。需确认数据排列顺序并添加断言。

---

### P2-R08: 标的池 get_tradable 幸存者偏差

| 属性 | 内容 |
|------|------|
| **文件** | `src/data/universe_provider.py` / `src/strategy/instrument_pool.py` |
| **工作量** | 0.5 天 |
| **关联** | P2-04 (Survivorship Bias) |

P2-04 (PIT 数据管理) 已完成 `UniverseManager`, 但 `UniverseProvider.get_tradable()` 和 `InstrumentPool` 是否已切换到 PIT 接口尚需验证。回测中仍使用当前成分股列表会引入幸存者偏差。

---

### P2-R09: dataset.py 逐行 concat 性能

| 属性 | 内容 |
|------|------|
| **文件** | `src/ml/dataset.py` L115 |
| **工作量** | 0.5 天 |

`_load_multi_stock` 循环中逐行 `pd.concat()` 复杂度 O(n^2)。当标的数量 > 500 时明显变慢。建议改为先收集 list 后一次 `pd.concat`。

---

### P2-R10: ETF rotator 单日止损语义

| 属性 | 内容 |
|------|------|
| **文件** | `src/strategy/etf_rotation/rotator.py` |
| **工作量** | 0.5 天 |
| **关联** | P1-20 (已完成) |

`_check_stop_loss` 只比较当日收盘 vs 买入价, 而非跟踪持仓期最大回撤。当前语义为 "总止损" 而非 "回撤止损"。如果是设计意图, 需在注释中明确; 否则需改为 trailing stop。

---

### P2-01: 滑点模型

| 属性 | 内容 |
|------|------|
| **模块** | backtest |
| **文件** | `src/backtest/fees.py` |
| **工作量** | 1 天 |

**为什么要做:**
回测与实盘的收益差距通常在 -20% 到 -50%，其中滑点和冲击成本是最大来源。当前回测只有固定费率，没有基于成交量的动态滑点。

**业界最佳实践:**
- **Almgren-Chriss 模型**: 经典市场冲击模型，`impact = η × σ × (V_order / V_avg)^β`
- **简化版 (散户适用)**: `slippage = base_spread + impact_coeff × (order_size / daily_volume) × volatility`
- **不对称费率**: A 股卖出有 0.05% 印花税，买入没有

**技术选型:**

| 技术 | 版本 | 说明 |
|------|------|------|
| 自研 SlippageModel | - | 固定 bps + 成交量冲击 |

**参考文档:**
- [Almgren-Chriss Market Impact Model](https://github.com/shubhamcodez/Market-Impact-Model)
- [Realistic Backtesting: Transaction Costs, Slippage (2025)](https://hyper-quant.tech/research/realistic-backtesting-methodology)
- [Estimating Implicit Transaction Costs (Medium)](https://medium.com/@msndourr/estimating-implicit-transaction-costs-under-a-linear-market-impact-model-c30f26cfd5a7)

**落地方案:**
```python
class SlippageModel:
    def __init__(self, fixed_bps=5, impact_coeff=0.1):
        self.fixed_bps = fixed_bps
        self.impact_coeff = impact_coeff

    def estimate(self, order_value, daily_volume, volatility):
        fixed = order_value * self.fixed_bps / 10000
        impact = self.impact_coeff * (order_value / daily_volume) * volatility * order_value
        return fixed + impact
```

---

### P2-02: XGBoost / CatBoost 真正实现 + Ensemble

| 属性 | 内容 |
|------|------|
| **模块** | ml |
| **文件** | `src/ml/xgb_model.py`, `src/ml/catboost_model.py` |
| **工作量** | 2 天 |

**为什么要做:**
当前 XGB/CatBoost 是空壳 (调 LGB 并打 warning)。模型集成 (ensemble) 可降低单模型过拟合风险:
- LGB: 速度最快，叶子生长策略
- XGB: 更正则化，层级生长策略
- CatBoost: 原生类别特征处理，有序提升 (ordered boosting)

**业界最佳实践:**
- **Rank Averaging**: 每个模型输出排名 (而非原始预测值)，取排名均值。这消除了模型间尺度差异
- **Stacking**: 三模型预测值作为 meta-learner (如 Ridge/Logistic) 的输入
- **实战效果**: Kaggle 金融竞赛中 XGB+LGB+CatBoost stacking 是标配方案，Sharpe 提升 10-20%
- **PenguinBoost (2025)**: 专为金融设计的混合 GBDT 库，内置 Era Boosting 和特征中性化

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| **xgboost** | >=3.0 | ✅ 2026最新3.2.0 (2.x→3.x大版本跳跃, 注意API变化) | `pip install xgboost` |
| **catboost** | >=1.2.10 | ✅ 2026最新1.2.10 (+Spark4/Polars支持) | `pip install catboost` |
| **penguinboost** | >=0.3.3 | ✅ 2025 | 金融专用 GBDT (可选) |

**参考文档:**
- [Stacking Ensembles: XGBoost + LightGBM + CatBoost (Medium)](https://medium.com/@stevechesa/stacking-ensembles-combining-xgboost-lightgbm-and-catboost-to-improve-model-performance-d4247d092c2e)
- [Quantitative ML/DL Ensemble AlgoTrading](https://github.com/suraj-phanindra/quantitative-ml-dl-ensemble-algotrading)
- [Kaggle Ensemble: XGB + LGB + CatBoost](https://www.kaggle.com/code/suhanigupta04/ensemble-xgb-lgb-catboost-predict-scores)
- PenguinBoost: [pypi.org/project/penguinboost](https://pypi.org/project/penguinboost/0.3.3/)

---

### P2-03: 绩效分析增强

| 属性 | 内容 |
|------|------|
| **模块** | backtest |
| **文件** | `src/backtest/performance.py` |
| **工作量** | 2 天 |

**为什么要做:**
当前绩效只有基础指标 (年化收益/Sharpe/最大回撤)。缺少:
- 月度收益热力图 (直观发现季节性)
- 滚动 Sharpe/Alpha (检测策略是否阶段性失效)
- Bootstrap 显著性检验 (Sharpe > 0 的 p-value)
- 信息比率 IR + Tracking Error (相对基准评估)

**参考文档:**
- quantstats: [github.com/ranaroussi/quantstats](https://github.com/ranaroussi/quantstats) (自动生成完整报告)

---

### ~~P2-04: Survivorship Bias / PIT 数据管理~~ → ✅ 已完成

> 已实现: `src/data/universe_manager.py` — `StockUniverse` ORM (SCD Type 2) + `UniverseManager.get_tradable()` PIT 查询。

---

### P2-05: 交易成本归因

| 属性 | 内容 |
|------|------|
| **模块** | backtest |
| **文件** | `src/backtest/performance.py` |
| **工作量** | 1 天 |

**落地方案:** 回测报告增加: 年化换手率、交易成本占毛收益比、扣费后 Sharpe、分策略换手统计。

---

### P2-06: 多周期标签

| 属性 | 内容 |
|------|------|
| **模块** | ml |
| **文件** | `src/ml/dataset.py` |
| **工作量** | 1 天 |

**为什么要做:** 不同持仓周期对应不同的 alpha 模式。日内反转、3-5 日动量、20 日趋势可能同时存在。单一 `label_period=2` 只捕获一种模式。

**落地方案:** `FactorDataset` 同时生成 1/3/5/10/20 日前向收益标签，多模型并行训练后加权合成。

---

### P2-07 ~ P2-09: 数据采集高级功能

| # | 描述 | 技术 | 文件 | 工作量 |
|---|------|------|------|--------|
| P2-07 | `TavilyCollector` 搜索 API | Tavily Python SDK v0.5+ | `collectors/tavily_collector.py` | 1 天 |
| P2-08 | `BrowserCollector` Playwright | Playwright >=1.48 | `collectors/browser_collector.py` | 1.5 天 |
| P2-09 | `HttpCollector` 通用 HTTP | curl_cffi >=0.7 | `collectors/http_collector.py` | 1 天 |

**P2-07 Tavily 参考:**
- Tavily Python SDK: [github.com/tavily-ai/tavily-python](https://github.com/tavily-ai/tavily-python) (2026.03 更新)
- Market Researcher 示例: [docs.tavily.com/examples/use-cases/market-researcher](https://docs.tavily.com/examples/use-cases/market-researcher)
- 开源 Market Researcher: [github.com/tavily-ai/market-researcher](https://github.com/tavily-ai/market-researcher)

**P2-08 Playwright 反爬要点 (2026):**
- 禁用 `navigator.webdriver` 标志
- 伪造 `navigator.plugins` 和 WebGL 指纹
- 会话一致性 > 随机化 (viewport/UA/locale/timezone 对齐)
- 居民代理 IP > 数据中心 IP
- 参考: [How Sites Detect Headless Browsers (2026)](https://dev.to/vhub_systems_ed5641f65d59/how-sites-detect-headless-browsers-and-how-to-evade-each-signal-2026-guide-2jj0)
- 参考: [Playwright Anti-Bot Detection (2026)](https://alterlab.io/blog/playwright-anti-bot-detection-what-actually-works-in-2026)

---

### P2-10 ~ P2-12: 数据清洗高级 Schema

| # | 描述 | 文件 | 工作量 |
|---|------|------|--------|
| P2-10 | `SectorSignalExtraction` Schema (行业轮动) | `schemas/sector_signal.py` | 1 天 |
| P2-11 | `FundFlowExtraction` Schema (资金流向) | `schemas/fund_flow.py` | 0.5 天 |
| P2-12 | `MacroIndicatorExtraction` Schema (宏观经济) | `schemas/macro_indicator.py` | 0.5 天 |

---

### P2-13 ~ P2-14: 情绪引擎高级功能

| # | 描述 | 文件 | 工作量 |
|---|------|------|--------|
| P2-13 | `feature_builder.py` 情绪特征工程 → LGB | `src/sentiment/feature_builder.py` | 2 天 |
| P2-14 | 合成指数权重自动学习 | `src/sentiment/composite_index.py` | 1 天 |

**P2-13 为什么要做:** 情绪指标需要二次加工才能喂给 LGB:
- 滚动均值 (5/10/20日): 平滑噪声
- Z-score: 标准化可跨指标比较
- 差分: 捕捉变化速度
- 分位数分类 (恐慌/正常/过热): LGB 对分类特征更友好

**P2-13 蒸馏模型 → news_sentiment_score 集成路径:**

P2-19~P2-21 蒸馏模型训练完成后, `feature_builder.py` 需要对接本地推理:

```
news_sentiment_score 数据来源降级链:

FinBERT2-Base 本地 ONNX — 情绪分类 (Phase 2-3 目标态, 95% 流量)
Qwen3-0.6B + LoRA 本地 GGUF — 结构化抽取
    │ 置信度 < 0.7 / Schema 校验失败 → 飞轮队列 + API 兜底
    ▼
DeepSeek V3 API (低置信样本 + Phase 1 全量)
    │ 失败/超时
    ▼
Qwen3.5-Plus API (备选)
    │ 失败
    ▼
RuleCleaner 关键词匹配 → score = ±0.3 (粗粒度)
```

`feature_builder.py` 中对接蒸馏模型输出:

```python
def build_news_sentiment_features(self, df: pd.DataFrame) -> pd.DataFrame:
    """构建新闻情绪特征, 自动选择本地蒸馏或 API"""
    if settings.distill_enabled:
        from dataclean.cleaners.distilled_cleaner import DistilledCleaner
        cleaner = DistilledCleaner()
        df["news_mood"] = df["raw_news"].apply(
            lambda x: cleaner.clean(x).cleaned_data["news_sentiment_score"]
        )
    else:
        df["news_mood"] = df["news_sentiment_score"]  # API 清洗结果

    df["news_mood_ma5"] = df["news_mood"].rolling(5).mean()
    df["news_mood_zscore"] = (
        (df["news_mood"] - df["news_mood"].rolling(20).mean())
        / df["news_mood"].rolling(20).std()
    )
    df["news_mood_diff"] = df["news_mood"].diff()
    return df
```

**情绪因子效果评估 (与 doc/11 联动):**
- 新增 IC/ICIR 日监控: `news_mood` 与 `forward_return_t+1` 的 20 日滚动相关性
- 自动降权: 连续 30 天 IC < 0.01 → `SENTIMENT_W_NEWS` 降至 0
- 消融实验: 每月对比有/无新闻情绪因子的 Sharpe 差异

**P2-14:** 用 LGB 的 `feature_importance` 自动学习 6 维权重，替代 `.env` 手动配置。

---

### P2-15 ~ P2-17: 扩展分析引擎

| # | 引擎 | 描述 | 路径 | 工作量 |
|---|------|------|------|--------|
| P2-15 | stockradar | 个股舆情/事件/利好利空 → 信号增强 | `src/stockradar/` | 3 天 |
| P2-16 | fundflow | 北向/融资/大单深度分析 → 跟随聪明钱 | `src/fundflow/` | 3 天 |
| P2-17 | riskmonitor | 黑天鹅/政策突变/闪崩 → 紧急止损 | `src/riskmonitor/` | 2 天 |

---

### P2-18: LLM 驱动自动因子-模型联合迭代 (借鉴 RD-Agent) ⭐ 建议提升至 P1.2

| 属性 | 内容 |
|------|------|
| **模块** | ml |
| **文件** | 新增 `src/ml/rd_loop.py`, `src/ml/bandit.py`, `src/ml/experiment_tracker.py` |
| **工作量** | 5 天 |
| **优先级** | **★ 极高 — 建议提升至 P1.2, 直接填充空的 factor_meta/factor_values 表, 年化收益 2x 验证** |

**为什么做这个比其他 P2 任务更紧迫:**

1. **数据库空表**: `factor_meta` 和 `factor_values` 表当前为空, P1-21 (Alpha158) 需要手工实现 158 个因子; P2-18 的 RD-Agent 可以 **自动生成因子代码并入库**, 互相加速
2. **本地已有源码**: RD-Agent 仓库 (`c:\Users\dongg\git\RD-Agent`) 已 clone, 可直接参考其 `rdagent/scenarios/qlib/` 实现
3. **ROI 验证**: arXiv:2505.15155 报告年化收益 2x, 是所有 P2 任务中 ROI 最高的
4. **与 P2-23/P2-24/P2-29/P2-30 协同**: Bandit + Trace 是后续进化式因子挖掘、论文→代码管线的基础组件

**为什么要做:**
当前 `auto_iterate.py` 的迭代循环是固定的: 训练 LGB → 评估 → 调参 → 重复。它不会:
- 自动决定 "这一轮应该挖掘新因子还是优化模型超参"
- 利用 LLM 基于历史反馈提出新假设 (如 "上一轮加入换手率因子后 IC 提升了, 下一步试试加入量比因子")
- 记住历史实验结果, 避免重复无效尝试

微软 RD-Agent(Q) 已在论文 (arXiv:2505.15155) 中验证了这种 **LLM + Bandit + Trace** 的联合迭代架构的有效性。本地已有 RD-Agent 源码 (`c:\Users\dongg\git\RD-Agent`), 可直接参考实现。

**2026.02-04 最新相关研究:**
- **FactorMiner** (arXiv:2602.14670): Ralph Loop (检索→生成→评估→蒸馏) + 经验记忆 + 技能模块, 高质量因子产出 3x
- **QuantEvolve** (arXiv:2510.18569): 多 Agent 进化框架, 策略自动适应 regime 变化
- **Hermes Agent** (Nous Research): 持久记忆 + 自动技能沉淀, 越用越强
- **TiMi** (Microsoft): 数学反思 + LLM 参数调优, 比纯规则方法更灵活

**RD-Agent 架构 (我们的简化版):**

```
┌─────────────────────────────────────────────────────────────┐
│                   RD Loop (联合迭代主循环)                      │
│                                                               │
│  ┌─────────┐    ┌──────────────┐    ┌────────┐    ┌────────┐ │
│  │ Bandit   │──→│ LLM Propose  │──→│ Execute │──→│Feedback│ │
│  │ 选择方向  │    │ 生成假设+代码 │    │ 回测验证 │    │ 评估结果│ │
│  │factor/   │    │              │    │         │    │        │ │
│  │model     │    │              │    │         │    │        │ │
│  └─────────┘    └──────────────┘    └────────┘    └───┬────┘ │
│       ↑                                                │      │
│       └──────────── Trace (实验历史记忆) ←──────────────┘      │
└─────────────────────────────────────────────────────────────┘
```

**核心组件:**

1. **Bandit 行动选择器** (`src/ml/bandit.py`):
   - 8 维指标向量: IC, ICIR, Rank IC, Rank ICIR, 年化收益, IR, 最大回撤, Sharpe
   - Thompson Sampling 双臂: "factor" (挖掘新因子) vs "model" (优化模型)
   - 根据上一轮实验反馈自动决定下一轮方向

2. **Trace 实验历史** (`src/ml/experiment_tracker.py`):
   - 记录每轮: 假设 → 实现 → 结果 → 反馈
   - 智能过滤: 当前做因子时只看因子历史 + 最新成功模型; 反之亦然
   - 防止重复: LLM 可以看到 "上次试过 XX 因子, IC 只有 0.01, 不值得再试"

3. **LLM 假设生成** (可选, 使用 `src/dataclean/llm_client.py`):
   - 基于场景描述 + 历史 Trace + 当前 SOTA 状态
   - 输出: 新因子公式或模型调参方案
   - 降级: LLM 不可用时回退为规则引擎 (随机因子组合 / 网格搜索)

**技术选型:**

| 技术 | 版本 | 说明 |
|------|------|------|
| numpy | >=2.0 | ✅ 2026最新2.4.4 | Thompson Sampling 采样 |
| openai SDK | >=2.0 | ✅ 2026最新2.30.0 | LLM 假设生成 (可选) |
| pickle | 内置 | Trace 序列化 |

**参考文档:**
- **RD-Agent 源码**: [github.com/microsoft/RD-Agent](https://github.com/microsoft/RD-Agent) v0.8.0
  - Bandit: `rdagent/scenarios/qlib/proposal/bandit.py`
  - Trace: `rdagent/core/proposal.py`
  - 联合循环: `rdagent/app/qlib_rd_loop/quant.py` (`QuantRDLoop`)
  - 因子去重: `rdagent/scenarios/qlib/developer/factor_runner.py`
- **RD-Agent(Q) 论文**: [arXiv:2505.15155](https://arxiv.org/abs/2505.15155) — *Data-Centric Multi-Agent for Joint Factor and Model Optimization*

**落地方案 (简化版, 不依赖完整 RD-Agent 框架):**
```python
class SimpleRDLoop:
    def __init__(self):
        self.bandit = LinearThompsonTwoArm(n_features=8)
        self.trace = Trace()
        self.weights = [0.1, 0.1, 0.05, 0.05, 0.25, 0.15, 0.1, 0.2]

    def iterate(self):
        # 1. Bandit 选择方向
        prev_metrics = self.trace.last_metrics()
        action = self.bandit.next_arm(prev_metrics)  # "factor" or "model"

        if action == "factor":
            # 2a. 生成新因子 (LLM 或规则)
            new_factors = self.propose_factors(self.trace)
            # 3a. 去重 (IC < 0.99)
            new_factors = deduplicate_factors(self.sota_factors, new_factors)
            # 4a. 训练 + 回测
            result = self.run_backtest(factors=self.sota_factors + new_factors)
        else:
            # 2b. 优化模型
            new_params = self.propose_model_changes(self.trace)
            result = self.run_backtest(model_params=new_params)

        # 5. 反馈 + 更新
        metrics = extract_metrics(result)
        reward = np.dot(self.weights, metrics)
        self.bandit.update(action, reward, metrics)
        self.trace.append(action, metrics, result)
```

---

### P2-19 ~ P2-21: 知识蒸馏模块 (LLM 教师 → 轻量学生模型)

> **升级自 P3-06 (本地 FinBERT NLP)**
>
> 原 P3-06 设计为"直接部署 FinBERT 替代 API"，这浪费了 LLM 已有的高质量输出能力。
> 蒸馏方案利用双教师共识标注 + 难度感知训练 + 持续数据飞轮，将 LLM 知识"压缩"到本地小模型中。
>
> P3-06 已标记为 "已合并至 P2-19~P2-21"。

**核心价值:**
- API 成本归零 (从 ~2 元/百万 token 降至 0)
- 推理延迟从 200-500ms 降至 <5ms
- 离线可用，无网络依赖
- 情绪因子质量接近 LLM 水平 (90-99% 保留率)

**与豆包对话方案的 6 大升级 (基于 2026 全球最新实践):**

| # | 豆包方案 (旧) | 2026 最佳实践 (新) | 来源 |
|---|-------------|-------------------|------|
| 1 | 单教师软标签 | **多模型共识标注 + 分歧挖掘** | EvasionBench (2026) |
| 2 | 一次性蒸馏 | **持续数据飞轮 (Data Flywheel)** | NVIDIA Blueprint (2025) |
| 3 | 均匀训练全部数据 | **难度感知分层训练 (SFT→DPO)** | ODA-Fin arXiv:2603.07223 |
| 4 | KL 散度蒸馏损失 | **程序化策展 + LoRA 微调** (更简单同等效果) | TensorZero (2025) |
| 5 | 从零标注 | **SetFit 冷启动** (8 样本/类即可) | HuggingFace SetFit |
| 6 | 全量微调 (需 A800) | **LoRA 微调** (家用 GTX 1660+ 即可) | NVIDIA/HF 通用 |

**系统架构:**

```
┌─────────────────── 蒸馏增强设计 ───────────────────────┐
│                                                         │
│  DeepSeek ──┐                                           │
│             ├→ 共识仲裁器 → 难度分层 ─→ 学生模型(LoRA)  │
│  Qwen ──────┘     │            │          │             │
│              (分歧→Judge)  easy→SFT    本地推理<5ms      │
│                            hard→DPO        │            │
│                                       数据清洗          │
│                                         │               │
│  ┌──── 数据飞轮 ←── 低置信样本 ←─ 生产推理             │
│  │                                                      │
│  └→ 教师重标注 → 增量重训 → 热更新模型 → 生产推理 → ... │
└─────────────────────────────────────────────────────────┘
```

---

### P2-19: 多教师共识标注管线 (Multi-Teacher Consensus Labeling)

| 属性 | 内容 |
|------|------|
| **模块** | distill |
| **文件** | 新增 `src/distill/data_pipeline.py`, `src/distill/consensus.py`, `src/distill/models.py` |
| **工作量** | 2.5 天 |

**为什么要做:**
传统蒸馏用单一教师模型生成软标签，存在两大问题:
1. **教师偏差**: 单模型的系统性错误直接传递给学生
2. **边界样本质量差**: 难以区分的样本 (如 "央行降准" → 利好还是利空？) 得到的标签噪声最大

EvasionBench (2026) 证明: 用 2 个独立 LLM 标注 + 分歧挖掘，比单教师蒸馏提升 2.4%，且分歧样本作为 hard examples 训练后"起到隐式正则化作用"。

**业界最佳实践:**
- **Multi-Model Consensus (EvasionBench 2026)**: 双模型独立标注 + Judge 仲裁，Cohen's Kappa 达 0.835
- **ODA-Fin (arXiv:2603.07223, 2026.03)**: 难度感知采样，>50% 失败率的样本单独做 RL，8B 模型超越同规模所有开源金融 LLM
- **NVIDIA Data Flywheel Blueprint**: 生产级金融蒸馏框架，49-70B→1-8B，成本降低 98%

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| openai SDK | >=2.0 | ✅ 2026最新2.30.0 | DeepSeek/Qwen 统一调用 (复用 LLMClient) |
| pydantic | >=2.6 | ✅ | 标注结果 Schema |
| PostgreSQL JSONB | >=16 | ✅ | 标注存储 |

**参考文档:**
- EvasionBench (多模型共识): [arXiv:2601.09142](https://arxiv.org/abs/2601.09142) — 比单教师 +2.4%, 4B 模型 81.3% 准确率
- ODA-Fin (难度感知): [arXiv:2603.07223](https://arxiv.org/abs/2603.07223) — 难度+可验证性感知采样
- NVIDIA Blueprint: [github.com/NVIDIA-AI-Blueprints/ai-model-distillation-for-financial-data](https://github.com/NVIDIA-AI-Blueprints/ai-model-distillation-for-financial-data) — 生产级飞轮
- TensorZero: [tensorzero.com/blog](https://www.tensorzero.com/blog/fine-tuned-small-llms-can-beat-large-ones-at-5-30x-lower-cost-with-programmatic-data-curation/) — 程序化策展 5-30x 降本

**落地方案:**
```python
class ConsensusArbiter:
    """双教师共识仲裁 + 难度评分"""

    def __init__(self, llm_client, judge_model="deepseek-r1"):
        self.llm = llm_client
        self.judge_model = judge_model

    async def label_batch(self, texts: list[str]) -> list[ConsensusLabel]:
        results = []
        for text in texts:
            label_a = await self.llm.classify(text, model="deepseek")
            label_b = await self.llm.classify(text, model="qwen")

            if label_a == label_b:
                results.append(ConsensusLabel(
                    text=text, label=label_a,
                    confidence=1.0, is_hard=False,
                    teacher_agreement=True
                ))
            else:
                judge_label = await self.llm.classify(
                    text, model=self.judge_model,
                    context=f"Teacher A: {label_a}, Teacher B: {label_b}"
                )
                results.append(ConsensusLabel(
                    text=text, label=judge_label,
                    confidence=0.6, is_hard=True,
                    teacher_agreement=False
                ))
        return results

    def score_difficulty(self, labels, base_student):
        """ODA-Fin 风格: 用未训练学生预测，失败率>50%标记为hard"""
        for label in labels:
            pred = base_student.predict(label.text)
            label.difficulty_score = 1.0 if pred != label.label else 0.0
        failure_rate = sum(l.difficulty_score for l in labels) / len(labels)
        hard_set = [l for l in labels if l.difficulty_score > 0]
        easy_set = [l for l in labels if l.difficulty_score == 0]
        return easy_set, hard_set
```

**数据库 Schema:**
```sql
CREATE TABLE distill_labels (
    id SERIAL PRIMARY KEY,
    text TEXT NOT NULL,
    teacher_a_label VARCHAR(20),
    teacher_b_label VARCHAR(20),
    consensus_label VARCHAR(20) NOT NULL,
    judge_model VARCHAR(50),
    confidence FLOAT DEFAULT 1.0,
    is_hard BOOLEAN DEFAULT FALSE,
    difficulty_score FLOAT,
    metadata JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_distill_hard ON distill_labels (is_hard) WHERE is_hard = TRUE;
CREATE INDEX idx_distill_confidence ON distill_labels (confidence);
```

---

### P2-20: 学生模型分层训练 (Staged Student Training)

| 属性 | 内容 |
|------|------|
| **模块** | distill |
| **文件** | 新增 `src/distill/trainer.py`, `src/distill/lora_config.py`, `src/distill/student_registry.py` |
| **工作量** | 3 天 |

**为什么要做:**
传统蒸馏的 KL 散度损失在金融领域效果并不稳定 (TensorZero 2025 实测: 程序化策展 + 标准微调 = 同等效果且更简单)。
分层训练策略效果更优:
- **Phase 0 冷启动**: 在极少数标注数据下快速出 baseline
- **Phase 1 主训练**: 在海量共识标签上 LoRA 微调
- **Phase 2 难样本强化**: 利用教师分歧信息做偏好对齐

**三阶段训练:**

| 阶段 | 方法 | 数据 | 耗时 | 效果 |
|------|------|------|------|------|
| Phase 0: 冷启动 | SetFit (对比学习) | 8-16 人工标注/类 | ~30 秒 | 快速 baseline (F1 ~75%) |
| Phase 1: 主训练 | LoRA SFT | P2-19 的 `easy_set` (万级) | 1-3 小时 | 接近教师水平 (F1 ~90%) |
| Phase 2: 强化 | DPO 偏好对齐 | P2-19 的 `hard_set` (千级) | 0.5-1 小时 | 边界样本提升 (+2-3%) |

**学生模型选择 (2 档, 2026 Q2 调研结论):**

| 学生模型 | 参数量 | 架构 | LoRA 训练显存 | 推理速度 | 适用场景 |
|----------|--------|------|-------------|---------|---------|
| **FinBERT2-Base** | 125M | Encoder | ~4GB | ~5ms (CPU) | 中文金融情绪分类 (推荐默认) |
| **Qwen3-0.6B** | 600M | Decoder | ~6GB | ~50ms (CPU) | 结构化 JSON 抽取 (事件/风险/行业) |

> ~~TinyFinBERT (14.5M)~~ 已淘汰: 英文预训练, 不支持中文金融语料。详见 [13-数据清洗与LLM](13-数据清洗与LLM.md)。

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| **setfit** | >=1.1 | ✅ 2026 | Phase 0 冷启动 (8样本/类) |
| **peft** (LoRA) | >=0.18 | ✅ 2026最新0.18.1 (+EVA初始化/hot-swap/int8-LoRA) | Phase 1 参数高效微调 |
| **trl** | >=1.0 | ✅ 2026最新1.0.0 (**0.x→1.0大版本**, +GRPO/DPPO/SDPO) | Phase 2 DPO 偏好对齐 |
| **transformers** | >=5.0 | ✅ 2026最新5.5.0 (**4.x→5.x大版本**, 周更模式) | HuggingFace 模型加载 |
| **torch** | >=2.8 | ✅ 2026最新2.9.1 (+Blackwell GPU/CUDA13) | 训练后端 |
| **accelerate** | >=1.2 | ✅ | 混合精度 + 多卡 |

**参考文档:**
- SetFit 冷启动: [github.com/SetFit/setfit](https://github.com/SetFit/setfit) — 8 样本/类达到 RoBERTa-Large 水平
- FinBERT2: [github.com/valuesimplex/FinBERT](https://github.com/valuesimplex/FinBERT) — 最强中文金融 NLP (32B token 预训练)
- Qwen3-0.6B: [Qwen 官方](https://huggingface.co/Qwen/Qwen3-0.6B) — 600M 参数, 32K 上下文, 中文原生
- TinyLoRA: [MarkTechPost 2026.03](https://www.marktechpost.com/2026/03/24/this-ai-paper-introduces-tinylora/) — 仅 13 参数微调达 91.8% GSM8K
- ~~TinyFinBERT: [arXiv:2409.18999](https://arxiv.org/abs/2409.18999) — 已淘汰, 英文专用~~
- TensorZero: [tensorzero.com](https://www.tensorzero.com/blog/fine-tuned-small-llms-can-beat-large-ones-at-5-30x-lower-cost-with-programmatic-data-curation/) — 程序化策展 5-30x 成本降低

**落地方案:**
```python
class StagedTrainer:
    """三阶段渐进式训练: SetFit冷启动 → LoRA SFT → DPO强化"""

    def __init__(self, student_name="tinyfinbert", lora_rank=16):
        self.student_name = student_name
        self.lora_rank = lora_rank

    def phase0_setfit(self, few_shot_examples: dict[str, list[str]]):
        """Phase 0: 8样本/类冷启动 (30秒)"""
        from setfit import SetFitModel, SetFitTrainer
        model = SetFitModel.from_pretrained(self.student_name)
        trainer = SetFitTrainer(model=model, train_dataset=few_shot_examples)
        trainer.train()
        return model

    def phase1_lora_sft(self, easy_dataset, base_model=None):
        """Phase 1: LoRA微调, 显存仅需4-6GB (GTX 1660+可用)"""
        from peft import LoraConfig, get_peft_model
        from transformers import AutoModelForSequenceClassification

        model = AutoModelForSequenceClassification.from_pretrained(
            self.student_name, num_labels=3
        )
        lora_config = LoraConfig(
            r=self.lora_rank, lora_alpha=32,
            target_modules=["query", "value"],
            task_type="SEQ_CLS"
        )
        model = get_peft_model(model, lora_config)
        # LoRA 仅训练 0.1-1% 参数, 显存需求降低 80%
        trainer = Trainer(model=model, train_dataset=easy_dataset)
        trainer.train()
        return model

    def phase2_dpo(self, hard_dataset, model):
        """Phase 2: 利用教师分歧构造偏好对, DPO强化边界样本"""
        from trl import DPOTrainer, DPOConfig
        # 偏好对: (text, chosen=consensus_label, rejected=wrong_teacher_label)
        dpo_config = DPOConfig(beta=0.1, learning_rate=5e-6)
        trainer = DPOTrainer(model=model, train_dataset=hard_dataset, args=dpo_config)
        trainer.train()
        return model
```

---

### P2-21: 数据飞轮 + 生产部署 (Data Flywheel + Deployment)

| 属性 | 内容 |
|------|------|
| **模块** | distill |
| **文件** | 新增 `src/distill/inference.py`, `src/distill/flywheel.py`, 修改 `src/dataclean/cleaners/` |
| **工作量** | 2.5 天 |

**为什么要做:**
一次性蒸馏的学生模型会随市场风格变化逐渐"过时"。NVIDIA Data Flywheel Blueprint (2025) 证明:
持续收集生产中低置信度样本 → 教师重标注 → 增量重训学生模型，可实现**模型自我进化**，保持与市场同步。

**业界最佳实践:**
- **NVIDIA Data Flywheel**: 生产数据→教师标注→训练学生→部署→收集反馈→迭代, 成本降低 98%
- **模型导出**: PyTorch → ONNX Runtime (跨平台) → 可选 TensorRT (NVIDIA GPU 加速)
- **量化**: INT8 量化体积再减 50%, 精度损失 <1%
- **降级链**: 蒸馏模型(主路径) → LLM API(兜底) → 规则引擎(最后手段)

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| **onnxruntime** | >=1.21 | ✅ 2026最新1.21.1 (+TensorRT 10.8/ChatGLM/Baichuan2) | 跨平台推理 (CPU/GPU 通用) |
| **optimum** | >=1.23 | ✅ 2026 | HuggingFace ONNX 导出工具 |
| **tensorrt** | >=10.0 | ✅ 2026 | NVIDIA GPU 加速 (可选) |
| **APScheduler** | >=3.11 (stable) | ✅ 2026最新稳定3.11.2 | 飞轮周期任务调度 |

**参考文档:**
- NVIDIA Data Flywheel: [build.nvidia.com/nvidia/ai-model-distillation-for-financial-data](https://build.nvidia.com/nvidia/ai-model-distillation-for-financial-data) — 49-70B→1-8B, 98% 降本
- NVIDIA Technical Blog: [Build Efficient Financial Data Workflows](https://developer.nvidia.com/blog/build-efficient-financial-data-workflows-with-ai-model-distillation) — 完整工作流
- ONNX Runtime + TensorRT 推理加速: [腾讯云开发者社区](https://cloud.tencent.com/developer/article/2593373)

**落地方案:**

**1. 模型导出与量化:**
```python
from optimum.onnxruntime import ORTModelForSequenceClassification, ORTQuantizer
from optimum.onnxruntime.configuration import AutoQuantizationConfig

model = ORTModelForSequenceClassification.from_pretrained(
    "models/distilled/tinyfinbert-lora-merged", export=True
)
model.save_pretrained("models/distilled/onnx/")

quantizer = ORTQuantizer.from_pretrained("models/distilled/onnx/")
qconfig = AutoQuantizationConfig.avx512_vnni(is_static=False)
quantizer.quantize(save_dir="models/distilled/onnx-int8/", quantization_config=qconfig)
```

**2. 降级链集成:**
```python
class DistilledCleaner(BaseCleaner):
    """蒸馏模型清洗器: 本地推理为主, LLM API 为兜底"""

    def __init__(self):
        self.local_model = ORTModelForSequenceClassification.from_pretrained(
            settings.distill_model_path
        )
        self.tokenizer = AutoTokenizer.from_pretrained(settings.distill_model_path)
        self.llm_fallback = LLMClient()

    async def clean(self, text: str) -> CleanResult:
        inputs = self.tokenizer(text, return_tensors="np", truncation=True)
        logits = self.local_model(**inputs).logits
        probs = softmax(logits, axis=-1)
        max_prob = probs.max()

        if max_prob >= settings.distill_flywheel_low_conf_threshold:
            label = ["negative", "neutral", "positive"][probs.argmax()]
            return CleanResult(label=label, confidence=float(max_prob), source="distilled")
        else:
            # 低置信度: 记录到飞轮队列 + 回退 LLM
            await self._enqueue_flywheel(text, probs)
            return await self.llm_fallback.classify(text)
```

**3. 数据飞轮自动化:**
```python
class DataFlywheel:
    """持续数据飞轮: 低置信样本 → 教师重标注 → 增量重训 → 热更新"""

    def __init__(self, consensus: ConsensusArbiter, trainer: StagedTrainer):
        self.consensus = consensus
        self.trainer = trainer

    async def weekly_iteration(self):
        """APScheduler 周任务"""
        # 1. 从飞轮队列取低置信样本
        low_conf_texts = await db.fetch("SELECT text FROM flywheel_queue WHERE processed = FALSE")

        # 2. 双教师重标注
        new_labels = await self.consensus.label_batch([r.text for r in low_conf_texts])

        # 3. 追加到训练集
        await db.insert_many("distill_labels", new_labels)

        # 4. 增量 LoRA 微调 (在全量数据上)
        all_easy = await db.fetch("SELECT * FROM distill_labels WHERE is_hard = FALSE")
        new_model = self.trainer.phase1_lora_sft(all_easy)

        # 5. 评估: 新模型 vs 旧模型
        new_f1 = evaluate(new_model, test_set)
        old_f1 = evaluate(current_model, test_set)

        if new_f1 > old_f1:
            export_onnx(new_model, settings.distill_model_path)
            reload_model()
            log.info(f"Flywheel: model upgraded F1 {old_f1:.3f} → {new_f1:.3f}")

        # 6. 标记已处理
        await db.execute("UPDATE flywheel_queue SET processed = TRUE WHERE processed = FALSE")
```

**飞轮数据库 Schema:**
```sql
CREATE TABLE flywheel_queue (
    id SERIAL PRIMARY KEY,
    text TEXT NOT NULL,
    predicted_probs JSONB,
    max_confidence FLOAT,
    processed BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_flywheel_unprocessed ON flywheel_queue (processed) WHERE processed = FALSE;
```

**.env 新增参数:**
```env
# ===== 蒸馏模块 (P2-19~P2-21) =====
DISTILL_TEACHER_A=deepseek                 # 教师 A 模型
DISTILL_TEACHER_B=qwen                     # 教师 B 模型
DISTILL_JUDGE_MODEL=deepseek-r1            # 分歧仲裁 Judge 模型
DISTILL_CONSENSUS_THRESHOLD=0.7            # 共识置信度阈值
DISTILL_HARD_EXAMPLE_FAILURE_RATE=0.5      # ODA-Fin 难度阈值 (失败率>此值=hard)
DISTILL_STUDENT_MODEL=tinyfinbert          # 学生模型: tinyfinbert / finbert2-base / qwen-0.5b
DISTILL_LORA_RANK=16                       # LoRA 秩 (越大越精准, 越大显存越多)
DISTILL_LORA_ALPHA=32                      # LoRA alpha
DISTILL_USE_ONNX=true                      # 是否导出 ONNX 推理
DISTILL_INT8=false                         # 是否 INT8 量化
DISTILL_FLYWHEEL_SCHEDULE=weekly           # 飞轮重训频率: weekly / biweekly
DISTILL_FLYWHEEL_LOW_CONF_THRESHOLD=0.7    # 低于此置信度的样本进入飞轮队列
DISTILL_MODEL_PATH=models/distilled/       # 蒸馏模型存储路径
```

**应用场景扩展:**

| 场景 | 蒸馏应用 | 对应模块 | 学生模型推荐 |
|------|---------|---------|-------------|
| 金融情感分析 | 多教师共识 → LoRA SFT | sentiment (P2-13) | **FinBERT2-Base 125M** (encoder) |
| 事件驱动量化 | 利好/利空/重组 → 多标签分类 | stockradar (P2-15) | FinBERT2-Base 125M (encoder) |
| 风险预警 | 黑天鹅/政策突变 → 二分类 | riskmonitor (P2-17) | FinBERT2-Base 125M (encoder) |
| 结构化抽取 | 财报/公告 → JSON | dataclean | **Qwen3-0.6B** (decoder) |
| 语义 Alpha | 文本→768d 向量→LGB 特征 | ml/factor | FinBERT2-Base 125M (encoder) |

**关键参考文献 (全部 2025-2026):**

| 文献 | 核心贡献 | 链接 |
|------|---------|------|
| EvasionBench (2026) | 多模型共识 + 分歧挖掘, 比单教师 +2.4% | [arXiv:2601.09142](https://arxiv.org/abs/2601.09142) |
| ODA-Fin (2026.03) | 难度感知蒸馏, 8B 超越同规模 SOTA | [arXiv:2603.07223](https://arxiv.org/abs/2603.07223) |
| NVIDIA Data Flywheel (2025) | 生产级金融蒸馏蓝图, 成本降 98% | [GitHub](https://github.com/NVIDIA-AI-Blueprints/ai-model-distillation-for-financial-data) |
| TensorZero (2025.07) | 程序化策展 + 微调 = 5-30x 降本 | [Blog](https://www.tensorzero.com/blog/fine-tuned-small-llms-can-beat-large-ones-at-5-30x-lower-cost-with-programmatic-data-curation/) |
| SetFit (HuggingFace) | 8 样本/类冷启动, 无需 prompt | [GitHub](https://github.com/SetFit/setfit) |
| FinBERT2 (2025) | 最强中文金融 NLP (32B token 预训练, 125M) | [GitHub](https://github.com/valuesimplex/FinBERT) |
| Qwen3-0.6B (2025) | 600M decoder, 32K 上下文, 中文原生 | [HuggingFace](https://huggingface.co/Qwen/Qwen3-0.6B) |
| ~~TinyFinBERT (2024)~~ | ~~已淘汰: 英文专用, 不适合中文金融~~ | ~~[arXiv:2409.18999](https://arxiv.org/abs/2409.18999)~~ |
| TinyLoRA (2026.03) | 仅 13 参数微调达 91.8% GSM8K | [MarkTechPost](https://www.marktechpost.com/2026/03/24/this-ai-paper-introduces-tinylora/) |

---

### P2-22: 配置管理迁移 (.env → YAML/TOML 分层配置)

| 属性 | 内容 |
|------|------|
| **模块** | common |
| **文件** | 新增 `config/`, 修改 `src/common/config.py` |
| **工作量** | 2 天 |

**为什么要做:**
当前所有参数 (60+ 项) 都堆在一个 `.env` 文件中, 随着 P0-P1 持续新增模块, 预计将膨胀到 100+ 行。`.env` 的局限:
- 没有层级结构: 所有参数平铺, 不能按模块分组
- 没有类型: 所有值都是字符串, 需要手动转换
- 不支持默认值覆盖: 无法 `config.base.yaml` → `config.prod.yaml` 分层覆盖
- 敏感参数 (API key) 和普通配置 (窗口大小) 混在一起

**业界最佳实践:**
- **12-Factor App**: 环境变量存密钥, 配置文件存非敏感参数
- **TOML (pyproject.toml 风格)**: Python 3.11+ 内置 `tomllib`, 无需额外依赖
- **Hydra (Meta/Facebook)**: 企业级配置管理框架 (可能过重, 备选)
- **pydantic-settings**: 支持 YAML/TOML + env 混合加载

**落地方案:**
```
config/
├── base.toml        # 默认配置 (所有非敏感参数, 提交到 git)
├── production.toml  # 生产环境覆盖 (可选)
└── .env             # 仅存放敏感信息 (API keys, passwords, 不提交)
```

```toml
# config/base.toml
[data]
lookback_years = 5
akshare_rate = 0.15

[ml]
lgb_n_estimators = 1000
lgb_learning_rate = 0.05
cv_folds = 5

[factor]
alpha158_enabled = true
alpha158_windows = [5, 10, 20, 30, 60]
screen_ic_threshold = 0.03

[etf]
rebalance_day = "last_trading_day"
top_n = 4
```

```python
# src/common/config.py
import tomllib
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # 敏感参数从 .env 读取
    xt_account: str
    openai_api_key: str
    
    @classmethod
    def from_toml(cls, path: str = "config/base.toml"):
        with open(path, "rb") as f:
            toml_config = tomllib.load(f)
        # merge with env vars (env vars override toml)
        return cls(**toml_config)
```

**参考文档:**
- [Python tomllib (3.11+)](https://docs.python.org/3/library/tomllib.html)
- [pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [12-Factor Config](https://12factor.net/config)

---

### P2-23: LLM 进化式因子挖掘 (QuantaAlpha + FactorMiner 融合) ⭐

| 属性 | 内容 |
|------|------|
| **模块** | factor |
| **文件** | 新增 `src/factor/llm_mining/` (evolve.py, sandbox.py, evaluator.py, skill_store.py) |
| **工作量** | 5 天 |
| **优先级** | **★ 极高 — 研究驱动, 最高 ROI 潜力, 建议与 P2-18 同批实施** |

**为什么要做:**

2026 年前沿研究表明, LLM 引导的进化式因子挖掘在 A 股 (CSI 300/500) 上取得了显著超额收益:
- **QuantaAlpha** (arXiv:2602.07085): 轨迹级变异/交叉, CSI 300 IC 0.1501, 年化 27.75%, 回撤 7.98%
- **FactorEngine** (arXiv:2603.16365): 因子=可执行代码, 逻辑修改与参数搜索分离, SOTA IC/ICIR
- **Agentic Factor Investing** (arXiv:2603.14288): 自主信号闭环, 美股 Sharpe 3.11
- **FactorMiner** (arXiv:2602.14670): **Ralph Loop** (检索→生成→评估→蒸馏) + 经验记忆 + 技能模块, 高质量因子产出 3x

核心流程: LLM (DeepSeek/Qwen) 生成因子假设 → 转为可执行 Python 代码 → 在本地沙箱回测 → IC/ICIR 门控 → 进化 (保留优秀轨迹, 变异/交叉) → **技能沉淀 (Hermes 式)** → 入库

**与现有设计的关系:** 扩展 P2-18 (RD-Agent) 的因子挖掘能力, 增加进化搜索层 + FactorMiner 的 Ralph Loop + Hermes 的技能沉淀。

**FactorMiner Ralph Loop (新增融合):**
```
Retrieve (检索经验记忆中相似成功因子)
   → Analyze (分析为何相似因子成功/失败)
   → Launch (LLM 生成新因子代码)
   → Purify (IC/ICIR 门控 + embedding 去重)
   → Harvest (成功因子入库, 失败模式记录)
```

**Hermes 技能沉淀 (新增融合):**
每次成功挖掘, 自动将因子的"生成模式"沉淀为可复用技能文档:
- 适用 regime / 适用行业
- 数据前置条件
- 成功公式模板
- 已知反模式

**落地方案:**

```python
class EvolutionaryFactorMiner:
    """QuantaAlpha 风格进化式因子挖掘"""

    def mine(self, n_generations=10, population_size=20):
        population = self._init_population(population_size)

        for gen in range(n_generations):
            # 1. LLM 生成因子代码
            for individual in population:
                individual.code = self.llm.generate_factor_code(
                    hypothesis=individual.hypothesis,
                    parent_code=individual.parent_code,
                )
            # 2. 沙箱回测
            for individual in population:
                individual.metrics = self.sandbox.evaluate(individual.code)

            # 3. IC 门控
            population = [i for i in population if i.metrics["ic"] > 0.03]

            # 4. 选择 + 变异 + 交叉
            parents = self._select_top(population, k=population_size // 2)
            offspring = self._crossover_mutate(parents)
            population = parents + offspring

        return self._select_top(population, k=5)  # 最终因子
```

**参考文档:**
- **QuantaAlpha**: [arXiv:2602.07085](https://arxiv.org/abs/2602.07085)
- **FactorEngine**: [arXiv:2603.16365](https://arxiv.org/abs/2603.16365)
- **Agentic Factor Investing**: [arXiv:2603.14288](https://arxiv.org/abs/2603.14288)
- **AlphaForgeBench**: [arXiv:2602.18481](https://arxiv.org/abs/2602.18481) — LLM 交易智能体行为不稳定, 应产出可执行 alpha 再回测

---

### P2-24: 因子 Embedding 去重与经验记忆

| 属性 | 内容 |
|------|------|
| **模块** | factor |
| **文件** | 新增 `src/factor/factor_memory.py` |
| **工作量** | 2 天 |
| **优先级** | **中 — 与 P2-23 协同** |

**为什么要做:**

FactorMiner (arXiv:2602.14670) 发现: LLM 因子挖掘的核心瓶颈不是"找不到好因子", 而是"反复挖掘同类因子"。当因子库规模扩大时, 新因子与已有因子的重叠率急剧上升。

解决方案: 维护一个"因子经验记忆库" (已拒绝/已上线因子的 embedding), LLM 生成新因子前先检索去重。

**落地方案:**

```python
class FactorMemory:
    """因子经验记忆: embedding 检索去重"""

    def __init__(self, embedding_model="text-embedding-3-small"):
        self.embeddings = []  # (factor_name, embedding, status, metrics)

    def is_duplicate(self, new_factor_description: str, threshold=0.85) -> bool:
        new_emb = self._embed(new_factor_description)
        for _, emb, _, _ in self.embeddings:
            if cosine_similarity(new_emb, emb) > threshold:
                return True
        return False

    def record(self, factor_name, description, status, metrics):
        emb = self._embed(description)
        self.embeddings.append((factor_name, emb, status, metrics))
```

**参考文档:**
- **FactorMiner**: [arXiv:2602.14670](https://arxiv.org/abs/2602.14670)

---

### P2-25: RAG 投研知识库

| 属性 | 内容 |
|------|------|
| **模块** | research |
| **文件** | 新增 `src/research/rag_engine.py`, `src/research/knowledge_base.py` |
| **工作量** | 4 天 |
| **优先级** | **中 — 研究驱动, 增强投研能力** |

**为什么要做:**

2026 年 RAG (检索增强生成) 在金融分析领域取得突破:
- **CARAG** (EACL 2026): 因果-时序知识图谱从财报中抽取证据, 预测财报后价格冲击
- **LLM-RAG 金融分析** (arXiv:2504.06279): 向量检索 + RAG 查询模块

现有 `dataclean` 模块已将公告/研报清洗为结构化 JSON。下一步: 将清洗后文档存入 embedding 索引, 支持 RAG 查询, 用于盘前投研而非直接信号。

**落地方案:**

```python
class ResearchRAG:
    """RAG 投研知识库: 清洗后文档 → embedding → 检索 → LLM 生成"""

    def query(self, question: str, top_k=5) -> str:
        # 1. 检索相关文档块
        chunks = self.vector_store.search(question, top_k=top_k)
        # 2. 构造 RAG prompt
        context = "\n\n".join([c.text for c in chunks])
        # 3. LLM 生成回答
        return self.llm.generate(
            f"基于以下研报/公告内容回答问题:\n{context}\n\n问题: {question}"
        )
```

**参考文档:**
- **CARAG**: EACL 2026 (2026.eacl-long.141)
- **LLM-RAG 金融分析**: [arXiv:2504.06279](https://arxiv.org/abs/2504.06279)
- **FinSrag**: [arXiv:2502.05878](https://arxiv.org/abs/2502.05878)

---

### P2-26: FinBERT2 + Qwen 双塔检索/生成

| 属性 | 内容 |
|------|------|
| **模块** | research / dataclean |
| **文件** | 新增 `src/research/dual_tower.py` |
| **工作量** | 3 天 |
| **优先级** | **中 — 增强 P2-25 RAG 和因子去重** |

**为什么要做:**

FinBERT2 (arXiv:2506.06335) 是 2025 年最强的中文金融 Encoder 模型, 适合做 embedding/检索/分类。与 Qwen/DeepSeek 组成**双塔架构**: FinBERT2 负责检索, Qwen 负责生成。

**参考文档:**
- **FinBERT2**: [arXiv:2506.06335](https://arxiv.org/abs/2506.06335) — 中文金融语料 BERT 预训练
- **Fin-R1**: SUFE-AIFLM-Lab, Qwen2.5-7B + RL 金融推理

---

### P2-27: 多智能体投研架构 (TradingAgents + OpenClaw + Hermes)

| 属性 | 内容 |
|------|------|
| **模块** | research |
| **文件** | 新增 `src/research/agents/` |
| **工作量** | 5 天 |
| **优先级** | **中 — 远期但架构价值高, 为 P2-29/P2-30/P2-31 提供统一框架** |

**为什么要做:**

TradingAgents (49,628 stars, Tauric Research) 提出多角色 LLM 智能体协作投研:
- **基本面分析师**: 解读财报, 计算估值
- **情绪分析师**: 解读新闻/社交媒体 (与 P2-29 协同)
- **技术分析师**: 解读图表/指标
- **因子研究员**: 论文阅读+因子挖掘 (与 P2-30 协同)
- **多空辩论**: 买方 vs 卖方论证
- **风控官**: 检查仓位/风险限制
- **组合管理**: 综合决策

核心原则: **LLM 输出信号, 不直接下单** (AlphaForgeBench 结论)。信号通过 JSON schema 对接现有 SignalArbiter。

**OpenClaw 架构融入:**
OpenClaw (2026) 的 plugin SDK + 向量记忆可作为多 Agent 编排的底层框架:
- **Plugin 机制**: 每个 Agent (情绪/基本面/技术) 以 Plugin 形式注册, 热插拔
- **向量记忆**: Agent 共享的研报/新闻记忆池 (复用 P2-25 RAG 知识库)
- **消息总线**: Agent 间通过结构化 JSON 消息通信, 而非自由文本

**Hermes 持久记忆融入:**
Hermes Agent 的自动技能创建和持久记忆适合作为 Agent 层的增强:
- 每个 Agent 维护自己的 **经验记忆** (成功/失败案例)
- 跨 Agent **技能共享**: 情绪 Agent 学到的"政策解读模式"可供基本面 Agent 参考
- **自进化**: 持续学习新模式, 不需人工更新 prompt

**参考文档:**
- **TradingAgents**: [github.com/TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents) (49K stars)
- **OpenClaw**: 多智能体编排 + Plugin SDK + 向量记忆
- **Hermes Agent**: [hermes-agent.nousresearch.com](https://hermes-agent.nousresearch.com/) — 持久记忆 + 技能沉淀
- **ATLAS**: [arXiv:2510.15949](https://arxiv.org/abs/2510.15949) — Adaptive-OPRO 动态优化 prompt
- **QuantAgent**: [arXiv:2509.09995](https://arxiv.org/abs/2509.09995) — 四智能体 HFT 架构
- **FinAgent**: [arXiv:2402.18485](https://arxiv.org/abs/2402.18485) — 多模态金融交易智能体

---

### P2-28: PPO 自适应 Alpha 动态加权

| 属性 | 内容 |
|------|------|
| **模块** | ml / strategy |
| **文件** | 新增 `src/ml/alpha_weighter.py` |
| **工作量** | 3 天 |
| **优先级** | **低 — 远期, 在 P1-35 Regime 门控之后考虑** |

**为什么要做:**

PPO Adaptive Alpha Weighting (arXiv:2509.01393, Chen & Kawashima 2026) 使用 PPO 强化学习动态调整多路 alpha 信号的权重, 比固定权重或简单等权在更高 Sharpe/更低回撤上表现更好。

建议路径: 先实现 P1-35 Regime 门控 (规则方法) → 验证 A 股效果 → 若有余力再引入 PPO 加权。

**参考文档:**
- **PPO Adaptive Alpha**: [arXiv:2509.01393](https://arxiv.org/abs/2509.01393)
- **FinRL-DeepSeek**: [arXiv:2502.07393](https://arxiv.org/abs/2502.07393) — 风险敏感 RL + LLM
- **Alpha-R1**: [arXiv:2512.23515](https://arxiv.org/abs/2512.23515) — RL + 推理模型做情境化因子筛选

---

### P2-29: AI 新闻情报深度解读 Agent (情绪引擎 LLM 增强)

| 属性 | 内容 |
|------|------|
| **模块** | sentiment / dataclean |
| **文件** | 新增 `src/sentiment/news_intelligence.py`, 修改 `src/api/routers/sentiment_router.py` |
| **工作量** | 3 天 |
| **优先级** | **高 — 直接提升情绪引擎准确度, 与 P1-16~19 协同** |

**为什么要做:**

当前新闻处理链路: `新闻 → dataclean 结构化抽取 → SentimentDaily.news_sentiment_score (单一分数)`。这丢失了大量信息:
- **事件类型缺失**: 政策利好 vs 财报超预期 vs 并购重组, 对市场的影响机制完全不同
- **影响范围缺失**: 个股利好 vs 行业利好 vs 全市场事件
- **时间窗口缺失**: 短期冲击 (1-3 天) vs 长期改善 (1-3 月)
- **置信度缺失**: 确定性政策 vs 市场传闻

2026 研究进展:
- **TradingAgents** (49K stars): 专门的情绪分析 Agent 角色, 多维输出
- **FinBERT2**: 中文金融情感分类达 SOTA, 可作为轻量前置过滤
- **CARAG** (EACL 2026): 从新闻/财报中抽取因果链, 预测价格冲击方向

**落地方案:**

```python
class NewsIntelligenceAgent:
    """AI 新闻情报深度解读 — 多维度结构化输出"""

    OUTPUT_SCHEMA = {
        "event_type": str,           # policy/earnings/merger/lawsuit/macro/rumor
        "impact_scope": str,         # stock/sector/market
        "affected_codes": list[str], # 受影响标的代码
        "affected_sectors": list[str],
        "sentiment_score": float,    # -1 ~ +1
        "impact_magnitude": str,     # low/medium/high/extreme
        "time_horizon": str,         # intraday/short(1-5d)/medium(1-3m)/long(3m+)
        "confidence": float,         # 0 ~ 1
        "reasoning": str,            # 推理过程
    }

    def analyze(self, news_items: list[dict]) -> list[dict]:
        # 1. FinBERT2 快速过滤 (CPU <5ms/条): 中性新闻直接跳过
        filtered = self._finbert_filter(news_items, threshold=0.3)

        # 2. LLM 深度分析 (DeepSeek/Qwen): 多维度结构化输出
        results = []
        for item in filtered:
            result = self.llm.extract(
                prompt=self._build_prompt(item),
                schema=self.OUTPUT_SCHEMA,
            )
            results.append(result)

        # 3. 写入 SentimentDaily.extra (JSONB) + key_events
        return results
```

**与现有设计的关系:**
- `SentimentDaily` 表已有 `extra` (JSONB)、`key_events` (JSONB)、`hot_sectors` (JSONB) — 无需改表
- `sentiment_router.py` 的 `/ingest/external` API 已支持外部数据推送 — 直接复用
- 与 P1-16 (情绪合成指数) 联动: 事件影响等级作为 `news_mood` 的输入权重

**参考文档:**
- **TradingAgents 情绪Agent**: [github.com/TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)
- **CARAG**: EACL 2026 — 因果时序知识图谱
- **FinBERT2**: [github.com/valuesimplex/FinBERT](https://github.com/valuesimplex/FinBERT)

---

### P2-30: 论文阅读 → 策略/因子进化 Agent

| 属性 | 内容 |
|------|------|
| **模块** | research / factor |
| **文件** | 新增 `src/research/paper_reader.py`, `src/research/code_evolver.py` |
| **工作量** | 5 天 |
| **优先级** | **中 — 长期研究效率, 依赖 P2-25 RAG 基础设施** |

**为什么要做:**

量化研究的核心工作之一是跟踪前沿论文并将新想法转化为代码。2026 年多个框架验证了 AI 自动化这一流程的可行性:
- **RD-Agent(Q)** (NeurIPS 2025): 论文假设 → 因子代码 → 回测 → Bandit 调度, 年化收益 2x
- **FactorMiner** (arXiv:2602.14670): 经验记忆 + 技能模块, 3x 高质量因子产出
- **QuantEvolve** (arXiv:2510.18569): 多 Agent 进化框架, 自动适应 regime 变化
- **Hermes Agent** (Nous Research): 持久记忆 + 自动技能沉淀, 越用越强

**核心流程:**
```
arXiv 定期扫描 (每周)
    ↓ 过滤: 关键词 (alpha, factor, momentum, sentiment, A-share)
    ↓
论文 PDF → LLM 解读 (提取: 假设/公式/数据需求/实验结果)
    ↓ 写入 RAG 知识库 (P2-25)
    ↓
假设转化 Agent: "论文提出 X 因子, 基于 Y 数据, 公式 Z"
    ↓ 生成 Python 因子代码 (P2-23 EvolutionaryFactorMiner)
    ↓
沙箱回测: IC / ICIR / Sharpe 门控
    ↓ 经验记忆 (P2-24 FactorMemory): 成功/失败模式
    ↓
优秀因子 → factor_meta/factor_values 入库 → 下一轮 ML 训练
```

**落地方案:**

```python
class PaperReader:
    """arXiv 论文自动阅读与知识抽取"""

    def scan_arxiv(self, keywords: list[str], max_results=20) -> list[dict]:
        """扫描最新论文, 返回标题/摘要/PDF链接"""
        import arxiv
        search = arxiv.Search(
            query=" OR ".join(keywords),
            max_results=max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate,
        )
        return [{"title": r.title, "abstract": r.summary, "pdf": r.pdf_url}
                for r in search.results()]

    def extract_hypotheses(self, paper_text: str) -> list[dict]:
        """从论文中提取可执行的因子/策略假设"""
        return self.llm.extract(
            prompt=f"""从以下量化金融论文中提取所有可执行的交易假设:
            {paper_text[:8000]}

            对每个假设输出:
            - hypothesis: 一句话描述
            - formula: 数学公式 (如有)
            - data_required: 需要的数据字段
            - expected_ic: 论文报告的IC值 (如有)
            - market: 适用市场 (A股/美股/全球)
            """,
            schema=list[dict],
        )

class CodeEvolver:
    """论文假设 → 因子代码 → 回测 → 进化"""

    def evolve_from_paper(self, hypothesis: dict) -> dict | None:
        # 1. LLM 生成因子代码
        code = self.llm.generate(
            f"将以下金融假设转为 Python 因子计算函数:\n{hypothesis}\n"
            f"函数签名: def compute_factor(df: pd.DataFrame) -> pd.Series"
        )
        # 2. 沙箱执行 + IC 评估
        metrics = self.sandbox.evaluate(code)
        # 3. 经验记忆
        self.memory.record(hypothesis["hypothesis"], code, metrics)
        # 4. 门控
        if metrics["ic"] > 0.03 and metrics["icir"] > 0.3:
            return {"code": code, "metrics": metrics, "source": "paper"}
        return None
```

**Hermes 式技能沉淀 (可选增强):**

每次成功的论文→因子转化, 自动生成一个"技能文档" (类似 Hermes Agent 的 agentskills.io 格式), 记录:
- 适用市场条件 (regime)
- 数据前置条件
- 因子计算模板
- 已知失败模式

后续遇到类似假设时, Agent 可自动加载相关技能, 避免重复探索。

**前置依赖:** P2-25 (RAG 知识库) + P2-23 (进化式因子挖掘) + P2-24 (因子记忆)

**参考文档:**
- **RD-Agent**: [github.com/microsoft/RD-Agent](https://github.com/microsoft/RD-Agent)
- **FactorMiner**: [arXiv:2602.14670](https://arxiv.org/abs/2602.14670)
- **QuantEvolve**: [arXiv:2510.18569](https://arxiv.org/abs/2510.18569)
- **Hermes Agent Skill Synthesis**: [hermes-agent.nousresearch.com](https://hermes-agent.nousresearch.com/docs/)
- **arxiv Python API**: [github.com/lukasschwab/arxiv.py](https://github.com/lukasschwab/arxiv.py)

---

### P2-31: LLM 择时参数自适应 (TiMi 范式)

| 属性 | 内容 |
|------|------|
| **模块** | strategy / sentiment |
| **文件** | 新增 `src/strategy/llm_param_tuner.py`, 修改 `src/strategy/orchestrator.py` |
| **工作量** | 3 天 |
| **优先级** | **中 — 在 P1-35 Regime 门控 + P1-16~19 情绪引擎完成后实施** |

**为什么要做:**

微软 TiMi (Trade in Minutes, 2026) 证明了一种新范式: LLM 不直接产生买卖信号, 而是**根据市场状态动态调整策略参数**。这比 P1-35 的规则门控更灵活:

| 维度 | P1-35 Regime 门控 (规则) | P2-31 LLM 参数调优 |
|------|------------------------|-------------------|
| 输入 | 63 日上涨比例 + 波动率百分位 | SentimentDaily 全字段 + 近期市场走势 |
| 输出 | 策略通过/不通过 (布尔) | 策略参数覆盖 (连续值) |
| 灵活度 | 固定阈值, 难以覆盖新场景 | LLM 可推理罕见组合 |
| 延迟 | <1ms | ~500ms (可缓存) |
| 适用时机 | P1 阶段实施 | P1-35 验证后, P2 阶段增强 |

**与现有设计的关系:**
- `strategy_profiles.json` 已支持按宏观状态覆盖策略参数 — P2-31 是其 **LLM 驱动的动态版本**
- `SentimentDaily` 表有完整的多维情绪数据 — 正好作为 LLM 输入
- `orchestrator.py` 已有 `macro_env → profile → 参数覆盖` 链路 — 只需插入 LLM 调优层

**落地方案:**

```python
class LLMParamTuner:
    """LLM 择时参数调优 — 基于 SentimentDaily + 市场状态生成策略参数覆盖"""

    def suggest_params(self, sentiment: dict, market_stats: dict) -> dict:
        prompt = f"""你是一个量化策略参数调优专家。
        当前市场状态:
        - 情绪合成指数: {sentiment['composite_sentiment']}
        - 赚钱效应: {sentiment['earning_effect']}
        - 北向资金 5 日累计: {sentiment.get('north_net_flow', 'N/A')} 亿
        - 波动率 (20日): {market_stats.get('volatility_20d', 'N/A')}
        - 宏观状态: {sentiment.get('applied_state', 'normal')}

        请输出以下策略参数的推荐值 (JSON):
        - kelly_fraction: 0.1~0.5 (凯利系数)
        - max_position_pct: 0.3~1.0 (最大仓位)
        - momentum_lookback: 10~60 (动量窗口)
        - stop_loss_pct: 0.03~0.10 (止损比例)
        """
        return self.llm.extract(prompt, schema=dict)
```

**参考文档:**
- **TiMi**: [Microsoft Research](https://www.microsoft.com/en-us/research/publication/trade-in-minutes-rationality-driven-agentic-system-for-quantitative-financial-trading/)
- **TradingAgents**: [github.com/TauricResearch/TradingAgents](https://github.com/TauricResearch/TradingAgents)
- **ATLAS**: [arXiv:2510.15949](https://arxiv.org/abs/2510.15949)

---
