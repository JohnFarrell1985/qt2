# P1: 重要 (量化核心 + 模块完善 + ETF 轮动)

> 最后更新: 2026-04-04
>
> 20 项 | 预估工作量 ~40 天
>
> 返回总览: [TODO.md](TODO.md)

---

### P1-01: Purged Walk-Forward Cross-Validation

| 属性 | 内容 |
|------|------|
| **模块** | ml |
| **文件** | `src/ml/cross_validation.py` (新增), `src/ml/dataset.py` |
| **工作量** | 2-3 天 |

**为什么要做:**
当前 ML 模块使用简单的 train/val/test 三段切分。这在金融时间序列中会导致严重的**标签泄露 (look-ahead bias)**:
- `label_period=2` 意味着 T 日的标签依赖 T+1 和 T+2 的价格
- 简单切分时，训练集末尾的样本标签可能与验证集开头的样本在时间上重叠
- **后果**: 回测 Sharpe 可能虚高 30-50%，实盘完全无法复现

**业界最佳实践:**
- **Marcos López de Prado (2018)**: 在 *Advances in Financial Machine Learning* 第7章提出 **Purged K-Fold CV**:
  - **Purging**: 从训练集中删除所有与测试集标签时间范围重叠的样本
  - **Embargo**: 在测试集之后额外添加一个时间缓冲区 (通常为样本总数的 5%)，排除因市场滞后效应导致的信息泄露
- **Combinatorial Purged CV (CPCV)**: de Prado 的改进版，从 N 个折中选 k 个作为测试集，生成更多回测路径
- **Rolling Walk-Forward**: 每 6 个月前滚重新训练，确保模型始终使用最新数据

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| **skfolio** | >=0.5 | ✅ 2025-2026活跃 | 提供 `WalkForward` 和 `CombinatorialPurgedCV`，scikit-learn 兼容 |
| **mlfinlab** | >=2.0 | ✅ | Hudson & Thames 实现，`PurgedKFold` + `ml_cross_val_score` |
| 自研 | - | - | 也可基于 scikit-learn `BaseCrossValidator` 自行实现 |

**参考文档:**
- Marcos López de Prado, *Advances in Financial Machine Learning*, Ch.7 (原始论文)
- Wikipedia: [Purged Cross-Validation](https://en.wikipedia.org/wiki/Purged_cross-validation)
- skfolio 文档: [skfolio.org/user_guide/model_selection.html](https://skfolio.org/user_guide/model_selection.html)
- Hudson & Thames: [PurgedKFold Notebook](https://github.com/hudson-and-thames/example-notebooks/blob/main/Cross_validation/Chapter7_Cross_Validation.ipynb)
- [KFold CV with Purging and Embargo (Medium)](https://antonio-velazquez-bustamante.medium.com/kfold-cross-validation-with-purging-and-embargo-the-ultimate-cross-validation-technique-for-time-2d656ea6f476)

**落地方案:**
```python
class PurgedTimeSeriesSplit(BaseCrossValidator):
    def __init__(self, n_splits=5, purge_days=3, embargo_pct=0.05):
        self.n_splits = n_splits
        self.purge_days = purge_days
        self.embargo_pct = embargo_pct

    def split(self, X, y=None, groups=None):
        # groups = date column
        dates = groups.unique().sort_values()
        fold_size = len(dates) // self.n_splits
        for i in range(self.n_splits):
            test_start = dates[i * fold_size]
            test_end = dates[(i+1) * fold_size - 1]
            # Purge: remove train samples whose labels overlap test
            train_end = test_start - timedelta(days=self.purge_days)
            # Embargo: exclude samples after test
            embargo_end = test_end + timedelta(days=int(len(dates) * self.embargo_pct))
            ...
```

---

### P1-02: Rolling Walk-Forward 重训练 + Bandit 自动资源分配

| 属性 | 内容 |
|------|------|
| **模块** | ml |
| **文件** | `src/ml/auto_iterate.py` |
| **工作量** | 3 天 (含 Bandit) |

**为什么要做:**
A 股市场风格每 3-6 个月显著切换 (如 2024 小盘成长 → 2025 大盘价值)。固定训练集的模型会逐渐失效 (alpha decay)。研究显示美国市场年化 alpha 衰减成本为 5.6%，欧洲为 9.9%。

此外，在自动迭代中，系统需要决定 **"这一轮应该挖掘新因子还是优化模型？"** — 当前是人工决定，但微软 RD-Agent 证明可以用**强化学习 (Thompson Sampling 多臂老虎机)** 自动做出最优决策。

**业界最佳实践:**
- **Qlib Rolling Retrain Pipeline**: 24 月训练 + 6 月验证 + 6 月测试，每 6 月前滚
- **动量策略生命周期**: ~10 个月后转负，必须在此之前重训练
- **自动化**: 每周/月自动触发重训练，不依赖人工判断
- **RD-Agent(Q) Bandit Action Selection** (微软, arXiv:2505.15155): 使用 8 维量化指标向量 (IC, ICIR, Rank IC, Rank ICIR, 年化收益, IR, 最大回撤, Sharpe) 驱动 **Linear Thompson Sampling 双臂老虎机**，在 "factor" 和 "model" 两个臂之间自动选择下一轮迭代方向。实验反馈直接更新 Bandit 后验概率，无需人工干预

**RD-Agent Bandit 架构:**
```python
class Metrics:
    """8 维量化指标向量 (来自 Qlib 回测结果)"""
    ic: float; icir: float; rank_ic: float; rank_icir: float
    arr: float; ir: float; mdd: float; sharpe: float
    # 权重: (0.1, 0.1, 0.05, 0.05, 0.25, 0.15, 0.1, 0.2)
    # reward = dot(weights, [ic, icir, rank_ic, rank_icir, arr, ir, -mdd, sharpe])

class LinearThompsonTwoArm:
    """双臂: "factor" vs "model", 8维线性上下文, 高斯后验 Thompson Sampling"""
    def next_arm(self, context_x): ...  # 采样奖励, 选更高的臂

class EnvController:
    """决策器: record(metrics, prev_arm) → decide(metrics) → "factor" | "model" """
```

**参考文档:**
- Qlib Workflow: [github.com/microsoft/qlib](https://github.com/microsoft/qlib)
- **RD-Agent**: [github.com/microsoft/RD-Agent](https://github.com/microsoft/RD-Agent) (微软开源，LLM 驱动自主因子-模型联合进化)
- RD-Agent(Q) 论文: [arXiv:2505.15155](https://arxiv.org/abs/2505.15155) — *Data-Centric Multi-Agent for Joint Factor and Model Optimization*
- [Signal Decay Analysis: Understanding Alpha Lifecycles](https://microalphas.com/signal-decay-patterns/)
- [Multi-Factor Strategies Framework for Independent Quants](https://dev.to/quant001/multi-factor-strategies-arent-exclusive-to-big-firms-a-research-framework-for-independent-quants-38ka)

**落地方案:**
1. **Rolling Walk-Forward**: 24+6+6 月窗口，每 6 月前滚重新训练
2. **Bandit 自动决策** (可选，P2 阶段细化): 每轮迭代结束后收集 8 维指标，更新 Thompson Sampling 后验，自动选择下轮做 "因子挖掘" 还是 "模型调优"
3. 集成入 `auto_iterate.py` 的 `iterate()` 主循环

---

### P1-03: 因子衰减监控

| 属性 | 内容 |
|------|------|
| **模块** | monitoring |
| **文件** | 新增 `src/monitoring/factor_monitor.py` |
| **工作量** | 2 天 |

**为什么要做:**
因子有效性会随时间衰减 (alpha decay)。2026 年的研究显示稳定股票因子 60% 衰减、动量因子约 10 个月后转负。没有监控 = 策略失效也不自知。

**业界最佳实践:**
- **核心 KPI (每日监控)**: 滚动 IC (20/60 日)、ICIR、因子换手率、hit-rate by decile
- **阈值**: IC 连续 20 天 < 0.02 → 告警; ICIR < 0.5 → 降权
- **PSI (Population Stability Index)**: 检测因子分布漂移，PSI > 0.2 → 中度关注，> 0.4 → 严重
- **KS 检验**: 比较训练期和实盘期的因子分布差异
- **分级响应**: 告警 → 缩减仓位 → 停止新开仓 → 隔离策略 → 触发重训练

**技术选型:**

| 技术 | 版本 | 说明 |
|------|------|------|
| scipy.stats | >=1.12 | `ks_2samp()` KS 检验 |
| numpy | >=1.26 | PSI 计算 |
| Alphalens-reloaded | >=0.0.14 | 因子分析可视化 (可选) |

**参考文档:**
- [Concept Drift Alarms for Quant Signals](https://stockalpha.ai/alpha-learning/concept-drift-alarms-for-quant-signals-detecting-when-alpha-decays)
- [Signal Decay Analysis](https://microalphas.com/signal-decay-patterns/)
- [Alphalens 因子评估指南](https://medium.com/@er.mananjain26/separating-signal-from-noise-a-practical-guide-to-evaluating-alpha-factors-with-alphalens-b883070aab14)

---

### P1-04: 模型漂移检测

| 属性 | 内容 |
|------|------|
| **模块** | monitoring |
| **文件** | 新增 `src/monitoring/model_monitor.py` |
| **工作量** | 2 天 |

**为什么要做:**
LightGBM 模型的预测能力会随市场结构变化退化 (concept drift)。PSI 可检测输入特征分布是否偏移。

**业界最佳实践:**
- **预测值 vs 实际收益滚动相关性**: 每日计算 20 日滚动 correlation
- **PSI**: `PSI = Σ (actual% - expected%) × ln(actual% / expected%)`，对每个特征独立计算
- **Bayesian Change-Point Detection**: 识别时序结构性断点
- **Shadow Backtest**: 实时用最新数据跑影子回测，与实盘比对

**参考文档:** 同 P1-03

---

### P1-05: 组合优化器

| 属性 | 内容 |
|------|------|
| **模块** | portfolio |
| **文件** | 新增 `src/portfolio/optimizer.py` |
| **工作量** | 5-7 天 (含 CAA 模式) |

**为什么要做:**
当前 `PositionSizer` 只支持等权/ATR/Kelly 三种简单分配，不控制:
- 行业集中度 (可能 80% 资金在一个行业)
- 风格暴露 (可能全是小盘股)
- 换手率 (高频换仓侵蚀 alpha)
- 组合风险最优化

**业界最佳实践:**

#### 方法 1: CAA — Classical Asset Allocation (Keller, Butler & Kipnis, 2015) ⭐ 推荐

> 论文: *Momentum and Markowitz: a Golden Combination* (Keller, Butler, Kipnis, 2015)

CAA 是动量驱动的纯多头 MVO 模型，百年回测 (1915-2014) 证明它**始终大幅跑赢等权 (1/N)**。业界曾普遍认为 MVO "不稳定、误差放大" (Michaud 1989, DeMiguel 2007, Ang 2014)，但 Keller 等人证明这是因为传统实现犯了两个错误:

1. **允许做空** — 做空权重放大了估计误差。Ma (2002) 证明纯多头约束消除了 MVO 大部分不稳定性
2. **回望期过长 (60 个月)** — 5 年处于价格均值回归区间 (Asness 2012)，过去表现好的资产未来往往变差

CAA 的核心修正:
- **纯多头 (long-only)** — 我们 A 股散户天然纯多头，完美契合
- **短回望期 (1-12 月)** — 利用动量因子的最优窗口
- **收益估计 = 1/3/6/12 月动量均值** — 跨越动量有效区间，减少单窗口偏差
- **协方差 = 近 12 个月** — 波动率和相关性也有短期持续性 ("generalized momentum")
- **权重上限 (cap=25%)** — 强制分散化，降低集中度风险
- **现金不设上限** — 极端恐慌时可 100% 现金 (与我们情绪引擎完美联动)
- 使用 **CLA (Critical Line Algorithm)** 而非通用二次优化器 — 在 N >> T 时不受协方差矩阵奇异影响

**百年回测数据:**

| 宇宙 | 模型 | CAGR | 波动率 | 最大回撤 | Sharpe | Calmar |
|------|------|------|--------|---------|--------|--------|
| N=8 全球多资产 | **CAA** (TV=10%) | **12.7%** | 8.3% | **-17.3%** | **0.92** | **0.45** |
| | EW (1/N) | 8.7% | 9.2% | -49.7% | 0.40 | 0.07 |
| N=39 全球大宇宙 | **CAA** (TV=10%) | **15.4%** | 10.4% | **-22.8%** | **1.00** | **0.46** |
| | EW (1/N) | 8.8% | 10.7% | -63.3% | 0.35 | 0.06 |

- N=39 的 Sharpe 达到 **1.0** (EW 的 3 倍)，最大回撤仅为 EW 的 **1/3**
- 2008 金融危机前模型自动切换至 100% 国债 (动量信号驱动)
- **结果对 cap 参数 (10%-100%) 全部稳健** — CAA 始终打败 EW，无论 cap 取何值
- 年换手率约 4-7 倍，交易成本在 0.7% 以内对结论无影响

**CAA 与 Smart Beta 的关系 (Hallerbach 2013):**

| Smart Beta 策略 | 等价于 CAA/MSR 的假设 |
|----------------|---------------------|
| 等权 (1/N) | 所有收益、波动率、相关性相等 |
| 最小方差 (MV) | 所有收益相等 |
| 最大分散化 (MD) | 所有 Sharpe ratio 相等 |
| 风险平价 (ERC) | Sharpe 相等 + 相关性相同 |

**CAA 数学性质 (保障稳健性):**
- **尺度不变性**: 月度/年度收益换算不影响最优权重
- **水平不变性**: 所有资产收益平移相同常数 (如减去无风险利率) 不影响最优权重
- **IIA (独立于无关备选)**: 加入完全相关的复制资产不改变结果

#### 方法 2: skfolio (scikit-learn 原生组合优化)

当需要更复杂的约束 (行业暴露上限、CVaR 风险度量、Black-Litterman 观点融合) 时，可使用 skfolio 作为 CAA 的补充或替代。

#### 方法 3: Risk Parity / HRP

- **Risk Parity**: 风险贡献均等化，不依赖收益预测，稳健性好
- **HRP (Hierarchical Risk Parity)**: López de Prado 提出，使用层次聚类确定资产权重，比传统 MVO 更稳定
- **适用场景**: 不愿对收益做预测时 (但 CAA 论文认为: 用动量做收益预测时，MVO 效果远优于 Risk Parity)

#### 约束优化

所有方法均需施加:
- 行业暴露 ≤ 15%、单只 ≤ 5% (或 CAA 默认的 25%)、日换手率 ≤ 20%

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| **自研 CLA** | - | - | 实现论文中的 Critical Line Algorithm (Python 版 Bailey & de Prado 2013 已开源) |
| **skfolio** | >=0.5 | ✅ 2026活跃 | 基于 scikit-learn 的组合优化库，支持 MVO/Risk Parity/HRP/Black-Litterman，内置 WalkForward CV |
| **cvxpy** | >=1.5 | ✅ | 凸优化求解器，skfolio 底层依赖 |
| **Riskfolio-Lib** | >=7.2 | ✅ | 另一选择，24+ 凸风险度量 |
| **riskparity.py** | >=0.1 | ✅ | 专用风险平价库 |
| numpy/pandas | >=2.0 | ✅ | 协方差矩阵 + 动量计算 |

**参考文档:**
- 📄 **Keller, Butler & Kipnis (2015)**: *Momentum and Markowitz: a Golden Combination*, SSRN (34 页，含完整 CLA R 代码) — **最核心参考**
- Bailey & López de Prado (2013): *An Open-Source Implementation of the Critical-Line Algorithm*, Algorithms 2013, 6, 169-196 (Python CLA 实现, SSRN 2197616)
- Ma & Jagannathan (2002): *Risk Reduction in Large Portfolios: Why Imposing the Wrong Constraints Helps*, NBER w8922 (证明纯多头约束提升 MVO 稳健性)
- Kwan (2007): *A Simple Spreadsheet-Based Exposition of the Markowitz Critical Line Method*, Spreadsheets in Education (CLA Excel 教程)
- skfolio 官方: [skfolio.org](https://skfolio.org/) (scikit-learn 原生集成)
- skfolio 优化指南: [skfolio.org/user_guide/optimization.html](https://skfolio.org/user_guide/optimization.html)
- Riskfolio-Lib: [riskfolio-lib.readthedocs.io](https://riskfolio-lib.readthedocs.io/en/latest)
- [Portfolio Optimization with Python (2026)](https://pub.towardsai.net/portfolio-optimization-with-python-mean-variance-vs-risk-parity-vs-min-vol-28fee8192d2f)
- [cvxpy Portfolio Optimization Tutorial](https://trader-algoritmico.com/blog/portfolio-optimization-with-cvxpy-mean-variance-vs-hrp-in-python)

**落地方案:**

**方案 A: CAA 模式 (推荐作为默认)**
```python
class CAAOptimizer:
    """Classical Asset Allocation — Keller, Butler & Kipnis (2015)
    动量驱动的纯多头均值-方差优化，使用 CLA 求解。
    """
    def __init__(self, target_vol=0.10, cap=0.25, cash_assets=None):
        self.target_vol = target_vol     # 目标年化波动率 (进取=10%, 稳健=5%)
        self.cap = cap                   # 风险资产权重上限 (默认 25%)
        self.cash_assets = cash_assets   # 现金类资产不设上限 (如国债ETF)

    def optimize(self, prices_12m: pd.DataFrame) -> dict[str, float]:
        # 1. 动量收益估计: (ROC_1m + ROC_3m + ROC_6m + ROC_12m) / 22
        ret_forecast = (
            prices_12m.pct_change(1).iloc[-1]
            + prices_12m.pct_change(3).iloc[-1]
            + prices_12m.pct_change(6).iloc[-1]
            + prices_12m.pct_change(12).iloc[-1]
        ) / 22

        # 2. 协方差矩阵: 近 12 个月月度收益
        monthly_returns = prices_12m.resample("ME").last().pct_change().dropna()
        cov_matrix = monthly_returns.cov()

        # 3. 权重上限: 风险资产 cap%, 现金类 100%
        weight_limits = {col: 1.0 if col in self.cash_assets else self.cap
                         for col in prices_12m.columns}

        # 4. CLA 求解 (target volatility 模式)
        weights = self._cla_solve(cov_matrix, ret_forecast, weight_limits)
        return weights

    def _cla_solve(self, cov_mat, ret_forecast, weight_limits):
        """Markowitz Critical Line Algorithm
        参考: Bailey & de Prado (2013), Kwan (2007)
        从有效前沿最高收益点出发，沿前沿向左搜索满足目标波动率的权重组合。
        """
        ...  # 实现 CLA 角点遍历 + 二分搜索目标波动率
```

**方案 B: skfolio 模式 (高级约束)**
```python
from skfolio.optimization import MeanRisk, ObjectiveFunction, RiskMeasure
from skfolio.model_selection import WalkForward

model = MeanRisk(
    objective_function=ObjectiveFunction.MAXIMIZE_RATIO,  # Max Sharpe
    risk_measure=RiskMeasure.CVAR,
    max_weight=0.05,  # 单只 ≤ 5%
)
cv = WalkForward(train_size=252*2, test_size=63)  # 2年训练+3月测试
```

**PositionSizer 集成:**
```python
class PositionSizer:
    def allocate(self, ..., method="equal"):
        if method == "caa":
            return CAAOptimizer(target_vol=settings.sizer.caa_target_vol,
                                cap=settings.sizer.caa_cap).optimize(prices_12m)
        elif method == "skfolio":
            return SkfolioOptimizer(...).optimize(...)
        elif method == "atr":
            ...  # 现有 ATR 逻辑
        else:
            ...  # 等权
```

**`.env` 新增参数:**
```bash
SIZER_METHOD=caa               # equal / atr / kelly / caa / skfolio
SIZER_CAA_TARGET_VOL=0.10      # CAA 目标年化波动率 (进取=0.10, 稳健=0.05)
SIZER_CAA_CAP=0.25             # CAA 风险资产权重上限
SIZER_CAA_CASH_ASSETS=["511010.SH","511260.SH"]  # 现金类资产代码 (国债ETF等)
```

---

### P1-06: 风险归因 (简化 Barra 模型)

| 属性 | 内容 |
|------|------|
| **模块** | portfolio |
| **文件** | 新增 `src/portfolio/risk_attribution.py` |
| **工作量** | 3 天 |

**为什么要做:**
不做风险归因就无法回答: "我的收益来自选股能力 (alpha) 还是行业暴露 (beta)？" 如果收益主要来自行业 beta，那策略在行业轮动时会崩溃。

**业界最佳实践:**
- **Barra CNE5/CNE6**: 中信建投、国泰君安的标配。10 大风格因子 (规模/价值/动量/波动率/流动性等) + 31 行业因子
- **截面回归**: `R_stock = α + Σ(β_style × Style_factor) + Σ(β_industry × Industry_dummy) + ε`
- **协方差估计**: Newey-West 调整 + 特征值风险调整 + 波动率偏误调整

**技术选型:**

| 技术 | 版本 | 说明 |
|------|------|------|
| statsmodels | >=0.14 | 截面 OLS 回归 |
| numpy/pandas | - | 因子矩阵构建 |

**参考文档:**
- Barra CNE5 Python: [github.com/xinyue6688/Barra-CNE5](https://github.com/xinyue6688/Barra-CNE5)
- Barra CNE6 + LGB: [github.com/finexsf/Barra-CNE6-LightGBM](https://github.com/finexsf/Barra-CNE6-LightGBM)
- [基于Barra CNE6的A股风险模型实践 (国君金工)](https://finance.sina.com.cn/stock/stockzmt/2024-06-04/doc-inaxpkzq3963139.shtml)
- [DolphinDB Barra 多因子风险模型](https://docs.dolphindb.com/zh/tutorials/barra_multi_factor_risk_model_0.html)
- [量化投资进阶：Barra多因子模型](https://cloud.baidu.com/article/3791053)

**落地方案 (简化版 5 因子):**
```python
STYLE_FACTORS = ["size", "value", "momentum", "volatility", "liquidity"]

def attribute_returns(portfolio_returns, factor_exposures):
    """简化 Barra 归因: 将组合收益分解为 alpha + 风格 + 行业"""
    X = factor_exposures[STYLE_FACTORS + INDUSTRY_DUMMIES]
    model = sm.OLS(portfolio_returns, sm.add_constant(X)).fit()
    attribution = {
        "alpha": model.params["const"],
        "style": {f: model.params[f] * factor_exposures[f].mean() for f in STYLE_FACTORS},
        "industry": ...,
        "residual": model.resid.std()
    }
    return attribution
```

---

### P1-07: 换手率约束

| 属性 | 内容 |
|------|------|
| **模块** | strategy |
| **文件** | `src/strategy/signal_arbiter.py` 或 `position_sizer.py` |
| **工作量** | 1 天 |

**为什么要做:**
高换手率侵蚀 alpha。回测中频繁换仓看似 "精准"，但实盘中手续费 + 滑点 + 冲击成本会吃掉大部分收益。A 股印花税 0.05% + 佣金 0.025% ≈ 单边 0.075%，双边 0.15%，年化换手率 200% 就意味着 30% 的费率成本。

**落地方案:**
在 `SignalArbiter` 中增加 `max_daily_turnover` 参数 (如 20%)，当日买卖金额 / 总资产超过阈值时截断低优先级信号。

---

### P1-08 ~ P1-11: datacollect 完善

| # | 描述 | 文件 | 工作量 |
|---|------|------|--------|
| P1-08 | `CollectRouter` 自适应路由 | `src/datacollect/router.py` | 1.5 天 |
| P1-09 | `OpenClawReceiver` POST 推送 | `src/datacollect/collectors/openclaw_receiver.py` | 1 天 |
| P1-10 | `XtdataCollector` QMT 本地缓存 | `src/datacollect/collectors/xtdata_collector.py` | 1 天 |
| P1-11 | APScheduler 定时调度 | `src/datacollect/scheduler.py` | 1.5 天 |

**P1-08 为什么要做:**
不同数据源的可靠性不同，需要自适应降级链: akshare (免费优先) → HTTP 爬虫 → Playwright 浏览器 → Tavily API (付费兜底)。

**P1-11 技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| **APScheduler** | >=4.0 (alpha) / 3.10 (stable) | ✅ 2025-2026 | 轻量级进程内调度，支持 cron/interval/date 三种触发器 |

**为什么不用 Celery:** Celery 需要 Redis/RabbitMQ 消息中间件，架构过重。APScheduler 单进程内运行，适合日级低频采集 (4 个时段/天)。

**参考文档:**
- APScheduler 官方: [apscheduler.readthedocs.io](https://apscheduler.readthedocs.io/)
- [APScheduler vs Celery (2026)](https://leapcell.io/blog/scheduling-tasks-in-python-apscheduler-vs-celery-beat)

---

### P1-12 ~ P1-15: dataclean 完善

| # | 描述 | 文件 | 工作量 |
|---|------|------|--------|
| P1-12 | `StockEventExtraction` Schema + Cleaner | `src/dataclean/schemas/` + `cleaners/` | 1 天 |
| P1-13 | `RiskAlertExtraction` Schema | `src/dataclean/schemas/risk_alert.py` | 0.5 天 |
| P1-14 | Schema + Prompt 注册表 | `src/dataclean/registry.py` | 1 天 |
| P1-15 | 清洗日志 ORM (LLM token 追踪) | `src/dataclean/models.py` | 0.5 天 |

**为什么要做:** 情绪只是数据清洗的一种输出。个股事件 (利好/利空/重组/增减持)、风险预警 (监管处罚/质押爆仓) 等也需要结构化抽取。注册表机制使新增 Schema 只需 "注册" 而非改代码。

---

### P1-16 ~ P1-19: sentiment 完善

| # | 描述 | 文件 | 工作量 |
|---|------|------|--------|
| P1-16 | `composite_index.py` 6维情绪合成指数 | `src/sentiment/composite_index.py` | 1.5 天 |
| P1-17 | `macro_classifier.py` 宏观状态分类器 | `src/sentiment/macro_classifier.py` | 2 天 |
| P1-18 | Orchestrator 集成 Profile | `src/strategy/orchestrator.py` | 1.5 天 |
| P1-19 | 情绪 API 完整化 | `src/api/routers/sentiment_router.py` | 1.5 天 |

**为什么要做:** 情绪合成指数 (CSI) 将 6 个维度 (量价/资金/情绪/波动/结构/衍生品) 加权合成为单一数值，驱动宏观状态分类器输出 6 种状态 (牛市/震荡偏多/震荡/震荡偏空/熊市/极端恐慌)。每种状态对应一套策略参数 Profile。

**落地参考:** 详见 [doc/11-市场情绪引擎.md](11-市场情绪引擎.md)

---

### P1-20: ETF 全球资产轮动策略 (Tactical Asset Allocation)

| 属性 | 内容 |
|------|------|
| **模块** | strategy / etf_rotation |
| **文件** | 新增 `src/strategy/etf_rotation/` (策略) + `doc/14-ETF资产配置轮动.md` (设计文档) |
| **工作量** | 7-10 天 |

**为什么要做:**

当前系统 10 个策略全部面向 **个股/可转债** — 数据量大、财务指标复杂、研报依赖高。对于 A 股散户来说，有一类更简单但回报卓越的方法: **ETF 全球资产轮动 (Tactical Asset Allocation)**。

核心优势:
- **数据量极少**: 仅需 10-20 只 ETF 的日线 OHLCV，无需财报/基本面
- **无选股压力**: 不挑个股，直接买 "一篮子" 资产类别
- **天然分散化**: 跨资产 (A 股/美股/黄金/债券)、跨国家、跨风格
- **学术背景深厚**: Keller (VAA/DAA/RAA)、Antonacci (Dual Momentum)、Faber (GTAA) 均有 SSRN 论文 + 10 年以上实盘验证
- **与个股策略正交**: 个股策略赚 alpha，ETF 轮动赚 beta + 趋势溢价，两者组合可显著提升整体 Sharpe
- **回测结果优异**: BigQuant/聚宽社区回测年化 24-35%，Sharpe 1.2-1.5，最大回撤 -11% ~ -20%
- **zhangsensen/etf-rotation-strategy**: A 股实盘 6 周收益 +6.37%，胜率 83.3%，样本外 Sharpe 1.38

**不做的后果:**
系统只能做个股，无法享受全球大类资产的动量溢价和危机对冲收益。黄金 2024-2025 年涨幅 40%+、纳指 2023-2024 年涨幅 80%+，纯做 A 股散户完全错过。

---

#### 一、策略原理: 为什么 ETF 轮动有效

**动量效应 (Momentum Factor)**:
过去 1-12 个月表现强的资产，未来 1-3 个月大概率继续强势。这是学术界最稳健的异象之一 (Jegadeesh & Titman 1993, Asness 2014)。

**均值回归的时间边界**:
动量在 1-12 个月有效，12 个月以上进入均值回归。因此轮动频率取月度 (捕捉动量) 而非年度 (避免反转)。

**"广度动量" (Breadth Momentum)**:
Keller (2017) 发现: 当多数资产动量为正 → 牛市，当动量为负的资产增多 → 危机前兆。这比单看指数更灵敏。

**免费午餐: 跨资产相关性**:
A 股、美股、黄金、债券的相关性长期 < 0.3。轮动入最强资产 + 危机时切换债券/黄金 → 同时提升收益和降低回撤。

---

#### 二、ETF 候选池设计 (基于 A 股场内可交易 ETF)

**池设计原则:**
1. **必须场内交易** (QMT 可直接下单)
2. **日均成交额 ≥ 1 亿元** (保证流动性)
3. **覆盖 5+ 资产类别** (分散化)
4. **跨境 ETF 优先 T+0** (灵活止损)

| 分类 | 代码 | 名称 | 资产类别 | T+0? | 说明 |
|------|------|------|----------|------|------|
| **A 股宽基** | 510300.SH | 沪深 300 ETF | A 股大盘 | ❌ | 最具代表性 |
| | 159915.SZ | 创业板 ETF | A 股成长 | ❌ | 中小盘成长 |
| | 510500.SH | 中证 500 ETF | A 股中盘 | ❌ | 中盘 alpha |
| | 159612.SZ | 中证 A50 ETF | A 股核心蓝筹 | ❌ | 行业龙头 |
| **A 股风格** | 510880.SH | 红利 ETF | A 股红利 | ❌ | 高股息防守 |
| **港股** | 513180.SH | 恒生科技 ETF | 港股科技 | ✅ | 互联网龙头 |
| | 513060.SH | 恒生 ETF | 港股大盘 | ✅ | 港股基准 |
| **美股** | 513100.SH | 纳指 100 ETF | 美股科技 | ✅ | QDII 王者 |
| | 513500.SH | 标普 500 ETF | 美股大盘 | ✅ | 全球基准 |
| **日欧** | 513880.SH | 日经 225 ETF | 日本股市 | ✅ | 日股行情 |
| | 513030.SH | 德国 DAX ETF | 欧洲大盘 | ✅ | 欧洲配置 |
| **商品** | 518880.SH | 黄金 ETF | 贵金属 | ✅ | 终极避险 |
| | 159985.SZ | 豆粕 ETF | 农产品 | ✅ | 通胀对冲 |
| **债券** | 511260.SH | 十年国债 ETF | 国债 | ✅ | 防御资产 |
| | 511010.SH | 国债 ETF | 短债 | ✅ | 现金替代 |
| **Canary (哨兵)** | 513100.SH | (复用) 纳指 100 | 新兴市场代理 | - | 全球风险晴雨表 |
| | 511260.SH | (复用) 十年国债 | 债券聚合代理 | - | 利率敏感度 |

> **推荐起步池**: 黄金(518880) + 纳指(513100) + 创业板(159915) + 沪深300(510300) + 十年国债(511260) — 5 只 ETF 即可覆盖核心资产类别

---

#### 三、动量评分体系 (三种方法, 用户可选)

##### 方法 A: 13612W 动量 (Keller, 2017) ⭐ 推荐

Keller 在 VAA/DAA 论文中提出的加权动量公式，对近期价格变化赋予更高权重 (最近 1 月权重 40%，传统 12 月动量仅 8%):

```
momentum_13612W = (12 × r₁ + 4 × r₃ + 2 × r₆ + 1 × r₁₂) / 4

其中 rₜ = p₀ / pₜ - 1 (t 月回望收益率)
```

特点: 响应速度最快，对趋势拐点灵敏，被 VAA/DAA/RAA 三大策略采用。

##### 方法 B: 趋势质量评分 (BigQuant 社区, 广泛使用)

动量不仅看涨幅，还看趋势稳定性 (R² 拟合优度):

```
1. 取近 N 日对数收盘价 ln(close)
2. 线性回归: ln(close) = α + β × t + ε
3. 年化收益率 = (e^(β×252) - 1) × 100
4. R² = 拟合优度 (0~1)
5. 动量评分 = 年化收益率 × R²
```

特点: 过滤高波动高涨幅但趋势不稳的 "毛刺行情"，对 A 股 ETF 特别有效。BigQuant 回测年化 27-35%。

##### 方法 C: 双动量 (Antonacci, 2014)

```
1. 相对动量: 在 ETF 池中按近 N 月回报排名
2. 绝对动量: 排名第一的 ETF 回报 > 无风险利率? (如十年国债收益率)
3. 若是 → 买入; 若否 → 全仓切换至国债 ETF (防御)
```

特点: 最简单、最经典。Antonacci 回测 1974-2013 年化 17.4%，最大回撤 -19.6%。

---

#### 四、崩盘保护机制 (Crash Protection)

这是 ETF 轮动区别于简单动量排序的 **核心差异化**。

##### 机制 1: 广度动量 / 哨兵资产 (Keller VAA/DAA)

```python
# 计算哨兵资产 (canary) 的 13612W 动量
canary_scores = {etf: calc_13612w(etf) for etf in canary_universe}

# 统计动量为负的哨兵数量
n_negative = sum(1 for s in canary_scores.values() if s <= 0)

# 防御仓位比例 = n_negative / len(canary_universe)
# 若 2 只哨兵全部为负 → 100% 切换至国债 ETF
# 若 1 只为负 → 50% 国债 + 50% 最强风险 ETF
# 若 0 只为负 → 100% 按动量选择风险 ETF
cash_fraction = n_negative / len(canary_universe)
```

VAA 论文回测: 年化 >10%，最大回撤 <15%，成功规避 2008/2020 崩盘。

##### 机制 2: 绝对动量门控

```python
# 所有风险 ETF 动量均为负 → 100% 国债
# 只买动量 > 0 的 ETF
eligible = [etf for etf in ranked_etfs if momentum[etf] > 0]
if not eligible:
    return {"511260.SH": 1.0}  # 全仓国债
```

##### 机制 3: 波动率门控 (zhangsensen 实战方案)

```python
# 基于波动率百分位动态调仓
vol_pct = current_vol / rolling_vol_max
if vol_pct > 0.9:    position_scale = 0.10  # 极端波动 → 90% 现金
elif vol_pct > 0.7:  position_scale = 0.40
elif vol_pct > 0.5:  position_scale = 0.70
else:                position_scale = 1.00  # 正常 → 满仓
```

---

#### 五、选择与调仓规则

| 参数 | 推荐值 | 说明 |
|------|--------|------|
| **调仓频率** | 每月首个交易日 | 月度捕捉动量，避免过高换手 |
| **持仓数量 K** | 1-3 只 | 集中持仓: K=1 收益最高但波动大; K=3 更稳健 |
| **权重分配** | 等权 (1/K) 或 动量加权 | 简单等权即可，动量加权略有提升 |
| **动量回望期** | 20 日 (方法 B) / 1-12 月 (方法 A) | 方法 B 推荐 20-25 日; 方法 A 自动多窗口 |
| **安全区间** | 评分 ∈ (0, 5] | 避免过热 (>5) 和趋势消失 (≤0) |
| **最小持有天数** | 9 个交易日 | 防止频繁换仓 (anti-whipsaw) |
| **排名差异阈值** | ≥10% | 新 ETF 排名需比持仓高 10% 才触发换仓 |
| **止损** | 单日跌 ≥5% 或 3 日累计 ≥8% | 极端事件快速离场 |

---

#### 六、与现有系统的集成设计

##### 模块结构

```
src/strategy/etf_rotation/
├── __init__.py
├── universe.py          # ETF 池管理 (候选池/哨兵池/防御池)
├── momentum.py          # 动量评分 (13612W / R²×Return / DualMomentum)
├── crash_guard.py       # 崩盘保护 (广度动量/绝对动量/波动率门控)
├── rotator.py           # 核心轮动引擎 (选择/调仓/信号生成)
└── etf_rotation_strategy.py  # 继承 BaseStrategy, 接入 Orchestrator
```

##### 数据流

```
xtquant (ETF 日线下载)
   ↓
PostgreSQL (etf_daily 表)
   ↓
momentum.py (计算动量评分)
   ↓
crash_guard.py (崩盘保护门控)
   ↓
rotator.py (排名/选择/反转过滤/生成 Signal)
   ↓
Orchestrator → PositionSizer → Trading
```

##### 与 Orchestrator 集成

```python
class ETFRotationStrategy(BaseStrategy):
    """ETF 全球资产轮动策略 — 月度调仓"""

    def generate_signals(self, holdings, **kwargs) -> list[Signal]:
        # 1. 从 DB 拉取 ETF 池近 12 个月日线
        prices = self._load_etf_prices(lookback_months=12)

        # 2. 计算动量评分
        scores = self.scorer.score(prices, method=self.config.momentum_method)

        # 3. 崩盘保护
        cash_frac = self.crash_guard.evaluate(prices, self.config.canary_etfs)

        # 4. 是否到调仓日?
        if not self._is_rebalance_day(holdings):
            return []  # 非调仓日, 持有不动

        # 5. 选择 top-K ETF
        selected = self._select_top_k(scores, holdings, k=self.config.top_k)

        # 6. 应用 cash_frac 调整仓位
        signals = []
        risk_weight = (1 - cash_frac) / len(selected) if selected else 0
        for etf in selected:
            signals.append(Signal(
                code=etf, direction="buy",
                target_weight_pct=risk_weight * 100,
                strategy_name="etf_rotation",
            ))
        if cash_frac > 0:
            for def_etf in self.config.defensive_etfs:
                signals.append(Signal(
                    code=def_etf, direction="buy",
                    target_weight_pct=cash_frac * 100 / len(self.config.defensive_etfs),
                    strategy_name="etf_rotation",
                ))

        # 7. 对持仓中不在 selected 的 ETF 生成卖出信号
        for h in holdings:
            if h.code not in [s.code for s in signals]:
                signals.append(Signal(code=h.code, direction="sell",
                                      strategy_name="etf_rotation"))
        return signals
```

##### 与情绪引擎联动 (可选增强)

```python
# 宏观状态 → 调整 ETF 轮动参数
if macro_state == "极端恐慌":
    cash_frac = max(cash_frac, 0.8)  # 至少 80% 防御
elif macro_state == "牛市":
    config.top_k = 1  # 集中持仓最强 ETF
```

##### 与 P1-05 CAA 优化器联动 (可选增强)

当持仓 K ≥ 3 时，可用 CAAOptimizer 对选出的 ETF 做均值-方差优化分配权重，而非简单等权:

```python
if self.config.use_caa_weights and len(selected) >= 3:
    weights = CAAOptimizer(
        target_vol=self.config.caa_target_vol,
        cap=self.config.caa_cap,
    ).optimize(prices[selected])
```

---

#### 七、`.env` 新增参数

```bash
# === ETF 轮动策略 ===
ETF_ROTATION_ENABLED=true
ETF_ROTATION_MOMENTUM_METHOD=13612w        # 13612w / r2_return / dual_momentum
ETF_ROTATION_LOOKBACK_DAYS=25              # 方法B回望天数
ETF_ROTATION_TOP_K=2                       # 每期持有ETF数
ETF_ROTATION_REBALANCE_INTERVAL=20         # 调仓间隔(交易日), 约1个月
ETF_ROTATION_MIN_HOLD_DAYS=9               # 最小持有天数(反转过滤)
ETF_ROTATION_RANK_THRESHOLD=0.10           # 排名差异阈值(10%)
ETF_ROTATION_SCORE_MIN=0.0                 # 动量评分下限
ETF_ROTATION_SCORE_MAX=5.0                 # 动量评分上限(方法B)
ETF_ROTATION_STOP_LOSS_DAILY=0.05          # 单日止损 5%
ETF_ROTATION_STOP_LOSS_3D=0.08             # 3日累计止损 8%
ETF_ROTATION_USE_CAA_WEIGHTS=false         # 是否使用CAA优化权重
ETF_ROTATION_CAA_TARGET_VOL=0.10           # CAA目标波动率
ETF_ROTATION_VOLATILITY_GATE=true          # 是否启用波动率门控
# ETF 池 (JSON 数组)
ETF_ROTATION_RISK_POOL=["510300.SH","159915.SZ","510500.SH","510880.SH","513180.SH","513100.SH","513500.SH","513880.SH","513030.SH","518880.SH","159985.SZ"]
ETF_ROTATION_DEFENSIVE_POOL=["511260.SH","511010.SH"]
ETF_ROTATION_CANARY_POOL=["513100.SH","511260.SH"]
```

---

#### 八、回测验证方案

| 维度 | 方案 |
|------|------|
| **数据源** | xtquant `download_history_data` 拉取 ETF 日线 (2015 至今, 约 10 年) |
| **基准** | 沪深 300 ETF (510300.SH) Buy & Hold |
| **对照组** | 等权持有全部 ETF、60/40 (沪深300 60% + 国债 40%) |
| **核心指标** | 年化收益 ≥15%、Sharpe ≥1.0、最大回撤 ≤-20%、Calmar ≥0.5 |
| **鲁棒性** | 参数敏感性 (K=1/2/3, lookback=15/20/25/60) |
| **费率** | ETF 佣金万 0.5 + 0 印花税 (ETF 免印花税) |
| **Walk-Forward** | 训练 3 年 + 测试 1 年滚动 |

---

**业界最佳实践:**

| 策略名称 | 作者 | 年份 | 核心创新 | CAGR | MaxDD | Sharpe | 论文/来源 |
|----------|------|------|----------|------|-------|--------|-----------|
| **VAA** | Keller & Keuning | 2017 | 广度动量 + 13612W | >10% | <-15% | ~1.0 | SSRN 3002624 |
| **DAA** | Keller & Keuning | 2018 | Canary 哨兵宇宙 | ~12% | <-13% | ~1.1 | SSRN 3212862 |
| **RAA** | Keller | 2021 | 失业率 + 哨兵 + All-Weather | ~10% | <-15% | ~0.9 | SSRN 3752294 |
| **ADM** | Engineered Portfolio | 2017 | 加速双动量 1/3/6 月 | ~15% | <-20% | ~1.0 | allocatesmartly.com |
| **PAA** | Keller & Keuning | 2016 | 保护型多资产 | >10% | <-10% | ~1.2 | SSRN 2759734 |
| **GTAA** | Faber | 2007 | 全球战术 + SMA 过滤 | ~11% | <-15% | ~0.8 | SSRN 962461 |
| **R²×Return** | BigQuant 社区 | 2024 | 趋势质量加权 | 27-35% | -11~-20% | 1.2-1.5 | BigQuant 策略社区 |
| **zhangsensen v8** | zhangsensen | 2026 | 49 ETF + 23 因子 + WFO | 53.9% (OOS) | - | 1.38 | GitHub |

**技术选型:**

| 技术 | 版本 | 最新状态 | 说明 |
|------|------|---------|------|
| xtquant | 随 QMT | ✅ | ETF 日线数据下载 (`download_history_data`) |
| numpy | >=2.0 | ✅ | 动量计算 / 线性回归 |
| scipy.stats | >=1.12 | ✅ | 线性回归 R² |
| pandas | >=2.0 | ✅ | 时间序列处理 |
| skfolio (可选) | >=0.5 | ✅ 2026 | 若启用 CAA 权重优化 |

**参考文档:**
- 📄 Keller & Keuning (2017): *Breadth Momentum and Vigilant Asset Allocation (VAA)*, [SSRN 3002624](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3002624)
- 📄 Keller & Keuning (2018): *Defensive Asset Allocation (DAA)*, [SSRN 3212862](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3212862)
- 📄 Keller (2021): *Resilient Asset Allocation (RAA)*, [SSRN 3752294](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=3752294)
- 📄 Keller & Keuning (2016): *Protective Asset Allocation (PAA)*, [SSRN 2759734](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2759734)
- 📄 Antonacci (2014): *Dual Momentum Investing*, McGraw-Hill
- 📄 Faber (2007): *A Quantitative Approach to Tactical Asset Allocation*, [SSRN 962461](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=962461)
- 🔗 BigQuant ETF 动量轮动: [bigquant.com/wiki/doc/onmfWFbXGU](https://bigquant.com/wiki/doc/onmfWFbXGU)
- 🔗 zhangsensen/etf-rotation-strategy: [github.com/zhangsensen/etf-rotation-strategy](https://github.com/zhangsensen/etf-rotation-strategy)
- 🔗 oronimbus/tactical-asset-allocation: [github.com/oronimbus/tactical-asset-allocation](https://github.com/oronimbus/tactical-asset-allocation)
- 🔗 迅投 QMT ETF 轮动复现: [xuntou.net/forum](https://www.xuntou.net/forum.php?mobile=2&mod=viewthread&tid=2429)
- 🔗 Allocate Smartly (TAA 策略对比): [allocatesmartly.com](https://allocatesmartly.com/)
- 🔗 跨境 ETF 完整清单 (2026): [163.com](https://www.163.com/dy/article/KKOLTIL40556A1IK.html)

---
