# P2: 增强 (高级功能 + 扩展引擎)

> 最后更新: 2026-04-04
>
> 18 项 | 预估工作量 ~27 天
>
> 返回总览: [TODO.md](TODO.md)

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
| **xgboost** | >=2.1 | ✅ 2026活跃 | `pip install xgboost` |
| **catboost** | >=1.2 | ✅ 2025最新 | `pip install catboost` |
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

### P2-04: Survivorship Bias / PIT 数据管理

| 属性 | 内容 |
|------|------|
| **模块** | data |
| **文件** | 新增 `src/data/universe_manager.py` |
| **工作量** | 2 天 |

**为什么要做:**
不处理幸存者偏差的回测结果是虚假的:
- **年化收益虚高 1.5-4.5%** (累积 35-45%)
- **Sharpe 虚高 20-30%**
- **最大回撤低估 15-25%**

原因: 只用当前存活股票回测，遗漏了退市 (往往暴跌 80%+) 和被剔除指数成分的股票。

**业界最佳实践:**
- **SCD Type 2 (缓慢变化维度)**: 记录每只股票的生命周期 (`start_date`, `end_date`, `status_at_end`)
- **Point-in-Time 查询**: "T 日哪些股票是可交易的？" 而非 "今天的股票列表回溯到过去"
- **财务数据用 `announce_date`**: 而非 `report_date`，避免使用尚未公布的财报数据

**参考文档:**
- [量化回测中的幸存者偏差 (长牛笔记)](https://stay-bullish.com/p/survivor-bias-in-quantitative-backtesting)
- [破除量化回测中的幸存者偏差 (gs-quant)](https://blog.csdn.net/gitblog_00036/article/details/151534400)
- [量化回测的致命陷阱：深入解析生存偏差](https://technologynova.org/%E9%87%8F%E5%8C%96%E5%9B%9E%E6%B5%8B%E7%9A%84%E8%87%B4%E5%91%BD%E9%99%B7%E9%98%B1)
- [Historical Constituents of an Equity Index in Python](https://concretumgroup.com/historical-constituents-of-an-equity-index-in-python-norgate-data/)

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

**P2-14:** 用 LGB 的 `feature_importance` 自动学习 6 维权重，替代 `.env` 手动配置。

---

### P2-15 ~ P2-17: 扩展分析引擎

| # | 引擎 | 描述 | 路径 | 工作量 |
|---|------|------|------|--------|
| P2-15 | stockradar | 个股舆情/事件/利好利空 → 信号增强 | `src/stockradar/` | 3 天 |
| P2-16 | fundflow | 北向/融资/大单深度分析 → 跟随聪明钱 | `src/fundflow/` | 3 天 |
| P2-17 | riskmonitor | 黑天鹅/政策突变/闪崩 → 紧急止损 | `src/riskmonitor/` | 2 天 |

---

### P2-18: LLM 驱动自动因子-模型联合迭代 (借鉴 RD-Agent)

| 属性 | 内容 |
|------|------|
| **模块** | ml |
| **文件** | 新增 `src/ml/rd_loop.py`, `src/ml/bandit.py` |
| **工作量** | 5 天 |

**为什么要做:**
当前 `auto_iterate.py` 的迭代循环是固定的: 训练 LGB → 评估 → 调参 → 重复。它不会:
- 自动决定 "这一轮应该挖掘新因子还是优化模型超参"
- 利用 LLM 基于历史反馈提出新假设 (如 "上一轮加入换手率因子后 IC 提升了, 下一步试试加入量比因子")
- 记住历史实验结果, 避免重复无效尝试

微软 RD-Agent(Q) 已在论文 (arXiv:2505.15155) 中验证了这种 **LLM + Bandit + Trace** 的联合迭代架构的有效性。

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
| numpy | >=1.26 | Thompson Sampling 采样 |
| openai SDK | >=1.60 | LLM 假设生成 (可选) |
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
