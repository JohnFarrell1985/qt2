# P1.1: 系统风险 (最优先 — 不做会亏钱)

> 最后更新: 2026-04-12
>
> 11 项 | 预估工作量 ~22 天
>
> 优先级说明: 交易规则错误/标签泄露/过拟合/因子失效/容错降级 — 这些问题不解决, 回测虚高实盘亏钱
>
> 返回总览: [TODO.md](TODO.md) | 同级: [P1.2 赚钱效应](TODO-P12.md) | [P1.3 工程化](TODO-P13.md)

---

### P1-27: 标的池分类与交易规则引擎 (A股/港股/ETF/两融)

| 属性 | 内容 |
|------|------|
| **模块** | strategy / data |
| **文件** | `src/strategy/instrument_pool.py` (扩展), `src/strategy/trading_rules.py` (新增), `src/data/models.py` (扩展 `InstrumentPool`) |
| **工作量** | 3 天 |
| **优先级** | **最高 — 架构审查新增, 建议首批实施** |

**为什么要做:**

当前 `instrument_pool` 的 `asset_type` 仅支持 `stock` / `cb` / `etf` 三种, 且只用于 **池筛选** (决定走 DB 还是 QMT 板块)。系统没有按资产类型区分交易规则, 所有标的统一适用 A 股规则。这在以下场景会导致严重问题:

| 资产类型 | 交易制度 | 涨跌幅限制 | 印花税 | T+0 | 保证金 | 当前系统处理 |
|----------|----------|-----------|--------|-----|--------|------------|
| **A 股主板** | T+1 | ±10% | 0.05% | ❌ | — | ✅ 正确 |
| **A 股科创板** | T+1 | ±20% (前5日无限制) | 0.05% | ❌ | — | ⚠️ 涨跌幅硬编码 10% |
| **A 股创业板** | T+1 | ±20% | 0.05% | ❌ | — | ⚠️ 涨跌幅硬编码 10% |
| **A 股北交所** | T+1 | ±30% | 0.05% | ❌ | — | ❌ 未支持 |
| **港股通** | T+0 | 无涨跌幅 | 0 | ✅ | — | ❌ T+1 校验错误 |
| **ETF (场内)** | T+0 (跨境) / T+1 (境内) | 无涨跌幅 (多数) | 0 | 部分 | — | ⚠️ 统一 T+1 |
| **可转债** | T+0 | ±20% (临停) | 0 | ✅ | — | ⚠️ T+1 校验错误 |
| **两融标的** | T+1 | 同底层 | 同底层 | ❌ | 保证金比例 | ❌ 未支持融券卖出 |

**不做的后果:**
1. ETF 轮动策略 (P1-20) 中跨境 ETF 支持 T+0, 但 `SignalArbiter` 统一按 T+1 校验会阻止当日买卖
2. 可转债策略当日买入后无法当日止损 (实际可转债 T+0)
3. 港股通标的被错误限制涨跌幅 10%, 导致止损/止盈判断失准
4. 科创板/创业板 ±20% 涨跌幅被 10% 硬编码截断, 涨跌停模拟失真
5. 两融标的无法利用融券做空 (对冲策略的前提)

**落地方案:**

**子任务 1: 资产类型枚举与交易规则表** (1 天)

```python
from enum import Enum
from dataclasses import dataclass

class AssetType(str, Enum):
    A_STOCK_MAIN = "a_stock_main"       # A股主板
    A_STOCK_STAR = "a_stock_star"       # A股科创板 (688xxx)
    A_STOCK_GEM = "a_stock_gem"         # A股创业板 (300xxx)
    A_STOCK_BSE = "a_stock_bse"         # A股北交所 (8xxxxx/4xxxxx)
    HK_CONNECT = "hk_connect"           # 港股通
    ETF_DOMESTIC = "etf_domestic"       # 境内ETF (T+1)
    ETF_CROSS_BORDER = "etf_cross_border"  # 跨境/商品ETF (T+0)
    CONVERTIBLE_BOND = "cb"             # 可转债 (T+0)
    MARGIN_LONG = "margin_long"         # 两融-融资标的
    MARGIN_SHORT = "margin_short"       # 两融-融券标的

@dataclass(frozen=True)
class TradingRule:
    """资产交易规则"""
    asset_type: AssetType
    t_plus_n: int                     # T+0=0, T+1=1
    price_limit_pct: float | None     # 涨跌幅限制 (None=无限制)
    stamp_tax_rate: float             # 印花税率 (卖出)
    min_lot_size: int                 # 最小交易单位 (股/手)
    can_short: bool                   # 是否可做空
    margin_ratio: float | None        # 保证金比例 (仅两融)
    session_hours: str                # 交易时段

TRADING_RULES: dict[AssetType, TradingRule] = {
    AssetType.A_STOCK_MAIN: TradingRule(
        asset_type=AssetType.A_STOCK_MAIN,
        t_plus_n=1, price_limit_pct=0.10, stamp_tax_rate=0.0005,
        min_lot_size=100, can_short=False, margin_ratio=None,
        session_hours="09:30-11:30,13:00-15:00",
    ),
    AssetType.A_STOCK_STAR: TradingRule(
        asset_type=AssetType.A_STOCK_STAR,
        t_plus_n=1, price_limit_pct=0.20, stamp_tax_rate=0.0005,
        min_lot_size=200, can_short=False, margin_ratio=None,
        session_hours="09:30-11:30,13:00-15:00",
    ),
    AssetType.A_STOCK_GEM: TradingRule(
        asset_type=AssetType.A_STOCK_GEM,
        t_plus_n=1, price_limit_pct=0.20, stamp_tax_rate=0.0005,
        min_lot_size=100, can_short=False, margin_ratio=None,
        session_hours="09:30-11:30,13:00-15:00",
    ),
    AssetType.HK_CONNECT: TradingRule(
        asset_type=AssetType.HK_CONNECT,
        t_plus_n=0, price_limit_pct=None, stamp_tax_rate=0.0,
        min_lot_size=1, can_short=False, margin_ratio=None,
        session_hours="09:30-12:00,13:00-16:00",
    ),
    AssetType.ETF_CROSS_BORDER: TradingRule(
        asset_type=AssetType.ETF_CROSS_BORDER,
        t_plus_n=0, price_limit_pct=None, stamp_tax_rate=0.0,
        min_lot_size=100, can_short=False, margin_ratio=None,
        session_hours="09:30-11:30,13:00-15:00",
    ),
    AssetType.CONVERTIBLE_BOND: TradingRule(
        asset_type=AssetType.CONVERTIBLE_BOND,
        t_plus_n=0, price_limit_pct=0.20, stamp_tax_rate=0.0,
        min_lot_size=10, can_short=False, margin_ratio=None,
        session_hours="09:30-11:30,13:00-15:00",
    ),
    # ... 其余类型
}
```

**子任务 2: 代码→资产类型自动推断** (0.5 天)

```python
def infer_asset_type(code: str) -> AssetType:
    """根据证券代码自动推断资产类型"""
    prefix = code[:3] if len(code) >= 9 else code[:2]
    suffix = code.split(".")[-1] if "." in code else ""

    if suffix == "HK" or code.startswith("HK"):
        return AssetType.HK_CONNECT
    if code.startswith("688") or code.startswith("689"):
        return AssetType.A_STOCK_STAR
    if code.startswith("300") or code.startswith("301"):
        return AssetType.A_STOCK_GEM
    if code.startswith("8") or code.startswith("4"):
        return AssetType.A_STOCK_BSE
    if code.startswith("51") or code.startswith("159"):
        return _classify_etf(code)  # 进一步区分境内/跨境
    if code.startswith("11") or code.startswith("12"):
        return AssetType.CONVERTIBLE_BOND
    return AssetType.A_STOCK_MAIN
```

**子任务 3: SignalArbiter / PositionSizer 接入交易规则** (1.5 天)

```python
class SignalArbiter:
    def _check_t_plus_n(self, signal: Signal, holdings: list) -> bool:
        rule = TRADING_RULES[infer_asset_type(signal.code)]
        if rule.t_plus_n == 0:
            return True  # T+0 允许当日买卖
        # T+1: 检查今日买入的不能卖出
        return signal.code not in self._today_bought

    def _check_price_limit(self, signal: Signal, price: float, prev_close: float) -> bool:
        rule = TRADING_RULES[infer_asset_type(signal.code)]
        if rule.price_limit_pct is None:
            return True  # 无涨跌幅限制
        return abs(price / prev_close - 1) <= rule.price_limit_pct
```

**参考文档:**
- 深交所交易规则: [szse.cn](https://www.szse.cn/lawrules/rule/)
- 上交所交易规则: [sse.com.cn](http://www.sse.com.cn/lawandrules/)
- 港股通交易规则: [hkex.com.cn](https://www.hkex.com.cn/)
- 两融业务规则: [csrc.gov.cn](http://www.csrc.gov.cn/)
- QMT 港股通/两融 API: [迅投文档](https://dict.thinktrader.net/)

---

### P1-28: UniverseProvider 统一抽象接口

| 属性 | 内容 |
|------|------|
| **模块** | data / strategy |
| **文件** | 新增 `src/data/universe_provider.py`, 修改 `src/strategy/instrument_pool.py`, `src/strategy/orchestrator.py` |
| **工作量** | 1 天 |
| **优先级** | **高 — 架构审查新增, 建议与 P1-27 一起实施** |

**为什么要做:**

当前系统有两套 "标的来源", 职责交叉:
1. `UniverseManager` — PIT 回测侧, 回答 "某日哪些股票可交易" (仅 A 股)
2. `InstrumentPoolManager` — 策略侧, 从 DB 或 QMT 板块获取代码列表 (`BUILTIN_POOLS`)

问题:
- ETF 池、港股通池、两融池都没有纳入 `UniverseManager` 的 PIT 管理
- `InstrumentPoolManager._apply_filter_rules` 的 `asset_type` 分支是 if/elif 硬编码, 新增品种需改代码
- 回测时 ETF/可转债也需要 PIT 数据 (避免幸存者偏差), 但 `StockUniverse` 表只记股票

**落地方案:**

```python
from abc import ABC, abstractmethod

class UniverseProvider(ABC):
    """统一标的池提供者接口"""

    @abstractmethod
    def get_codes(self, trade_date: date, **filters) -> list[str]:
        """返回指定日期可交易的标的代码列表 (PIT 安全)"""
        ...

    @abstractmethod
    def get_asset_type(self, code: str) -> AssetType:
        """返回标的的资产类型"""
        ...

class AStockUniverseProvider(UniverseProvider):
    """A 股 (主板/科创/创业/北交) — 基于现有 UniverseManager"""
    ...

class ETFUniverseProvider(UniverseProvider):
    """ETF (境内 + 跨境) — 基于 QMT 板块 + PIT 过滤"""
    ...

class HKConnectUniverseProvider(UniverseProvider):
    """港股通 — 基于港股通名单 (每月更新)"""
    ...

class CBUniverseProvider(UniverseProvider):
    """可转债 — 基于转债列表 + 到期/退市过滤"""
    ...

class MarginUniverseProvider(UniverseProvider):
    """两融标的 — 基于交易所两融标的名单"""
    ...

class CompositeUniverseProvider(UniverseProvider):
    """组合式提供者 — 根据 pool 配置的 asset_type 委托到具体 Provider"""

    def __init__(self):
        self._providers: dict[AssetType, UniverseProvider] = {}

    def register(self, asset_type: AssetType, provider: UniverseProvider):
        self._providers[asset_type] = provider
```

**与 P1-27 的关系:** P1-27 定义了 `AssetType` 和 `TradingRule`; P1-28 让每种 `AssetType` 都有对应的 `UniverseProvider`, 两者共同构成完整的 "标的分类 + 交易规则" 体系。

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
| **skfolio** | >=0.15 | ✅ 2026最新0.15.7 | 提供 `WalkForward` 和 `CombinatorialPurgedCV`，scikit-learn 兼容 |
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

### P1-32: 分数 Kelly + 回撤自适应仓位缩减 (Quick Win)

| 属性 | 内容 |
|------|------|
| **模块** | strategy |
| **文件** | `src/strategy/position_sizer.py`, `src/strategy/position_monitor.py` |
| **工作量** | 1.5 天 |
| **优先级** | **高 — 研究驱动, Quick Win, 低复杂度高收益** |

**为什么要做:**

1. **分数 Kelly**: 当前 PositionSizer 的凯利模式使用完整 Kelly 公式。学术与实战共识: **完整 Kelly 波动过大**, 实际参数估计误差会导致爆仓风险。半 Kelly (f/2) 可获得 ~75% 的长期增长率, 但波动率仅约全 Kelly 的一半; 1/4 Kelly 更适合参数不确定的散户场景。
2. **回撤自适应**: 当组合回撤超过阈值时, 应自动缩减总仓位 (如回撤 >5% → 仓位缩至 75%; >10% → 50%). 这比固定仓位上限更灵活, 能在"伤口还小"时止血。

**学术依据:**
- **Kelly Criterion**: Kelly (1956); Thorp (2006) *The Kelly Criterion in Blackjack, Sports Betting, and the Stock Market*
- **Fractional Kelly 共识**: Ziemba (2003), MacLean (2010) — 半 Kelly 是实践中的黄金标准
- **Drawdown Control**: Grossman & Zhou (1993) *Optimal Investment Strategies for Controlling Drawdowns*; 多篇 2025-2026 博客实证

**落地方案:**

```python
class PositionSizer:
    def _kelly_fraction(self, win_rate, win_loss_ratio, kelly_frac=0.25):
        """分数 Kelly: 默认 1/4 Kelly (保守散户推荐)"""
        full_kelly = (win_rate * win_loss_ratio - (1 - win_rate)) / win_loss_ratio
        return max(0, full_kelly * kelly_frac)

class DrawdownGuard:
    """回撤自适应仓位缩减"""
    THRESHOLDS = [
        (-0.03, 0.90),   # 回撤 3% → 仓位缩至 90%
        (-0.05, 0.75),   # 回撤 5% → 75%
        (-0.08, 0.50),   # 回撤 8% → 50%
        (-0.12, 0.25),   # 回撤 12% → 25%
        (-0.15, 0.10),   # 回撤 15% → 几乎空仓
    ]

    def scale_factor(self, current_drawdown: float) -> float:
        for threshold, scale in self.THRESHOLDS:
            if current_drawdown <= threshold:
                return scale
        return 1.0
```

**.env 新增参数:**
```bash
SIZER_KELLY_FRACTION=0.25          # 分数 Kelly 系数 (0.25=四分之一, 0.5=半Kelly)
SIZER_DRAWDOWN_GUARD_ENABLED=true  # 启用回撤自适应
SIZER_DD_THRESHOLD_1=-0.03        # 回撤阈值 1 (3%)
SIZER_DD_SCALE_1=0.90             # 对应仓位缩减
SIZER_DD_THRESHOLD_2=-0.05
SIZER_DD_SCALE_2=0.75
SIZER_DD_THRESHOLD_3=-0.08
SIZER_DD_SCALE_3=0.50
```

---

### P1-35: Regime 门控信号过滤 (Drift Filter)

| 属性 | 内容 |
|------|------|
| **模块** | strategy |
| **文件** | `src/strategy/regime_gate.py` (新增), 修改 `src/strategy/signal_arbiter.py` |
| **工作量** | 2 天 |
| **优先级** | **高 — 研究驱动, 对现有策略收益有直接提升** |

**为什么要做:**

2025-2026 年多篇论文表明, 许多因子在"全时段"回测中表现平庸, 但在特定市场 regime 下表现优异:
- **Drift Regime Gating** (arXiv:2511.12490, Singha 2025): 仅在"漂移体制" (63日内上涨日占比 >60%) 下激活价值+反转因子, OOS Sharpe 大幅提升
- **Agentic Factor Investing** (arXiv:2603.14288, 2026): 强调 OOS + 经济叙事检查, 防止数据窥探
- **Kalman + Markov-Switching** (arXiv:2601.05716, 2026): 警告 regime 模型的 OOS 泛化风险

核心思路: 在 SignalArbiter 中增加 **regime 门控层**, 只在适合的市场环境下放行对应策略的信号, 而非让所有策略在所有环境下都运行。

**与现有设计的关系:**
- 现有 `macro_env.py` 通过 6 种宏观状态调整"仓位倍数"和"推荐/回避策略" — 这是**粗粒度**的
- Regime 门控是**细粒度**的: 在信号级别, 根据实时市场指标决定是否放行每个 Signal

**落地方案:**

```python
class RegimeGate:
    """Regime 门控: 根据市场 drift/volatility 状态过滤信号"""

    def __init__(self, drift_window=63, drift_threshold=0.60,
                 vol_percentile_window=252, vol_high_pct=0.80):
        self.drift_window = drift_window
        self.drift_threshold = drift_threshold
        self.vol_percentile_window = vol_percentile_window
        self.vol_high_pct = vol_high_pct

    def detect_regime(self, index_prices: pd.Series) -> str:
        """检测当前 regime: drift_up / drift_down / high_vol / normal"""
        returns = index_prices.pct_change()

        # Drift detection
        up_ratio = (returns.iloc[-self.drift_window:] > 0).mean()
        if up_ratio >= self.drift_threshold:
            return "drift_up"
        if up_ratio <= (1 - self.drift_threshold):
            return "drift_down"

        # Volatility detection
        current_vol = returns.iloc[-20:].std() * (252 ** 0.5)
        vol_pct = (returns.rolling(20).std() * (252 ** 0.5)).rank(pct=True).iloc[-1]
        if vol_pct >= self.vol_high_pct:
            return "high_vol"

        return "normal"

    # 策略 → 适用 regime 映射
    STRATEGY_REGIME_MAP = {
        "momentum":         ["drift_up", "normal"],
        "reversal":         ["drift_down", "high_vol"],
        "low_vol_dividend": ["normal", "high_vol", "drift_down"],
        "grid_trading":     ["normal"],
        "cb_dual_low":      ["normal", "drift_down", "high_vol"],
        "industry_rotation":["drift_up", "normal"],
        "moving_average":   ["drift_up", "normal"],
        "multifactor_*":    ["drift_up", "normal"],
        "lgb_ml":           ["drift_up", "normal"],
        "etf_rotation":     ["drift_up", "normal", "drift_down"],  # 有崩盘保护
    }

    def should_pass(self, signal: Signal, regime: str) -> bool:
        allowed = self.STRATEGY_REGIME_MAP.get(signal.strategy_name, ["normal"])
        return regime in allowed
```

**参考文档:**
- **Drift Regime**: [arXiv:2511.12490](https://arxiv.org/abs/2511.12490) — Discovery of a 13-Sharpe OOS Factor
- **Agentic Factor Investing**: [arXiv:2603.14288](https://arxiv.org/abs/2603.14288) — OOS + 经济叙事检查
- **Kalman + Markov-Switching**: [arXiv:2601.05716](https://arxiv.org/abs/2601.05716) — OOS 泛化失败风险警告
- **Man AHL Regime Detection**: [man.com/maninstitute/regime-based-asset-allocation](https://www.man.com/maninstitute/regime-based-asset-allocation)
- **AlphaForgeBench**: [arXiv:2602.18481](https://arxiv.org/abs/2602.18481) — LLM 不应直接下单, 应产出可执行 alpha 再确定性回测

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
| scipy.stats | >=1.15 | ✅ 2026最新1.17.1 | `ks_2samp()` KS 检验 |
| numpy | >=2.0 | ✅ 2026最新2.4.4 | PSI 计算 |
| Alphalens-reloaded | >=0.0.14 | 因子分析可视化 (可选) |

**因子拥挤度检测 (Factor Crowding, 架构审查新增):**

因子拥挤 = 过多资金追逐同一因子, 导致因子溢价消失甚至反转 (如 2020 年动量因子崩溃)。监控拥挤度可提前降权。

检测指标:
- **因子持仓集中度**: 因子 Top decile 的 Herfindahl Index > 阈值 → 拥挤
- **因子 Short Interest**: 做空端集中度异常 → 反转风险
- **成交量异常**: 因子 Top 组合近 20 日成交量 / 历史均值 > 2x → 过热
- **因子间相关性突增**: 正常不相关的因子 (如 Value 和 Momentum) 相关性突升至 >0.5 → 系统性风险

```python
class CrowdingDetector:
    def detect(self, factor_name: str, date: str) -> dict:
        return {
            "hhi": self._herfindahl(factor_name, date),
            "volume_ratio": self._volume_anomaly(factor_name, date),
            "cross_factor_corr": self._cross_corr_spike(date),
            "crowding_score": ...,  # 加权综合分 0-1
            "action": "reduce_weight" if score > 0.7 else "normal"
        }
```

**参考文档:**
- [Concept Drift Alarms for Quant Signals](https://stockalpha.ai/alpha-learning/concept-drift-alarms-for-quant-signals-detecting-when-alpha-decays)
- [Signal Decay Analysis](https://microalphas.com/signal-decay-patterns/)
- [Alphalens 因子评估指南](https://medium.com/@er.mananjain26/separating-signal-from-noise-a-practical-guide-to-evaluating-alpha-factors-with-alphalens-b883070aab14)
- [Factor Crowding (AQR)](https://www.aqr.com/Insights/Research/White-Papers/How-Can-a-Strategy-Still-Be-Valuable-If-Everyone-Knows-About-It)
- [Detecting Crowded Trades (JPM Quant)](https://www.pm-research.com/content/iijpormgmt/43/1/48)

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

### P1-22: Deflated Sharpe Ratio / 多重检验修正

| 属性 | 内容 |
|------|------|
| **模块** | backtest |
| **文件** | `src/backtest/performance.py` 扩展 |
| **工作量** | 1.5 天 |

**为什么要做:**
当系统积累了 10+ 策略 (当前已有 10 个规则策略 + ML 策略), 每个都跑回测选 "最好的", 本质上就是多重假设检验。即使策略全部随机, 10 个里也有 ~40% 概率出现 Sharpe > 1。不做修正 = "选到的好策略"可能只是运气。

**业界最佳实践:**
- **Deflated Sharpe Ratio (DSR)**: Bailey & López de Prado (2014) 提出, 根据尝试次数和策略空间调整 Sharpe
- **Probability of Backtest Overfitting (PBO)**: CSCV (Combinatorially Symmetric Cross-Validation) 方法
- **Bonferroni / Holm-Sidak 修正**: 经典统计多重检验修正

**落地方案:**
```python
def deflated_sharpe_ratio(
    observed_sharpe: float,
    num_trials: int,
    variance_of_sharpe_estimates: float,
    skewness: float,
    kurtosis: float,
    T: int  # 回测天数
) -> float:
    """
    返回 p-value: 在给定尝试次数下, 观察到的 Sharpe 有多大概率仅源于运气。
    p < 0.05 → 策略大概率有真实 alpha (而非过拟合)。
    """
    # E[max(SR)] under null, from Bailey & López de Prado (2014)
    expected_max_sr = expected_max_sharpe(num_trials, variance_of_sharpe_estimates)
    # Adjust for non-normal returns
    adjusted_sr = observed_sharpe * (1 - skewness * observed_sharpe / (4 * T)
                                      + (kurtosis - 3) * observed_sharpe**2 / (24 * T))
    return 1 - norm.cdf((adjusted_sr - expected_max_sr) / (1 / sqrt(T)))
```

**参考文档:**
- Bailey & López de Prado, "The Deflated Sharpe Ratio", *Journal of Portfolio Management* 2014
- [Advances in Financial Machine Learning, Ch.11 (Backtesting)](https://www.wiley.com/en-us/Advances+in+Financial+Machine+Learning-p-9781119482086)
- [PBO: Probability of Backtest Overfitting](https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2326253)

---

### P1-24: 数据质量监控 + Schema 校验

| 属性 | 内容 |
|------|------|
| **模块** | data / monitoring |
| **文件** | 新增 `src/data/quality.py`, `src/data/schemas.py` |
| **工作量** | 2 天 |

**为什么要做:**
"Garbage in, garbage out" — 数据质量直接决定模型和策略的有效性。当前系统无任何数据校验: 如果 akshare 返回缺失字段、类型错误或异常值 (如价格为负), 会静默流入 ML 训练, 导致不可预期的错误。

**业界最佳实践:**
- **Great Expectations / Pandera**: 数据质量框架, 定义 "期望" 并自动验证
- **Pandera** (推荐, 更轻量): 基于 pandas 的 schema 校验, 与 Pydantic 风格类似
- **分层校验**:
  1. **Schema 层**: 字段类型、非空、唯一约束
  2. **业务规则层**: `open > 0`, `high >= low`, `volume >= 0`, `date 连续`
  3. **统计层**: 日涨幅 |pct_change| < 22% (科创板), Z-score |z| < 10 → 异常值

**技术选型:**

| 技术 | 版本 | 说明 |
|------|------|------|
| **Pandera** | >=0.23 (2026 最新) | 轻量 DataFrame schema 校验 |
| pandas | >=2.2 | ✅ |

**落地方案:**
```python
import pandera as pa
from pandera import Column, Check

stock_daily_schema = pa.DataFrameSchema({
    "code": Column(str, Check.str_matches(r"^\d{6}\.(SH|SZ|BJ)$")),
    "date": Column("datetime64[ns]", nullable=False),
    "open": Column(float, Check.gt(0)),
    "high": Column(float, Check.gt(0)),
    "low": Column(float, Check.gt(0)),
    "close": Column(float, Check.gt(0)),
    "volume": Column(float, Check.ge(0)),
}, checks=[
    Check(lambda df: (df["high"] >= df["low"]).all(), error="high < low detected"),
    Check(lambda df: (df["high"] >= df["open"]).all(), error="high < open detected"),
])
```

**参考文档:**
- [Pandera](https://pandera.readthedocs.io/) — DataFrame schema validation
- [Great Expectations](https://docs.greatexpectations.io/) — 企业级数据质量
- [Data Quality for ML (Google)](https://developers.google.com/machine-learning/data-prep/construct/collect/data-size-quality)

---

### P1-25: 系统级容错 & 降级

| 属性 | 内容 |
|------|------|
| **模块** | common |
| **文件** | `src/common/resilience.py` |
| **工作量** | 2 天 |

**为什么要做:**
量化系统在实盘中面临多种故障源: QMT 断连、数据源超时、数据库宕机、LLM API 429。当前没有统一的容错机制, 任何一个环节故障都可能导致整个交易管道中断, 错过交易窗口或产生不一致的持仓状态。

**业界最佳实践:**
- **Circuit Breaker 模式** (熔断): 连续 N 次调用失败 → 自动熔断, 快速失败而非阻塞
- **Retry with Exponential Backoff**: 已部分实现 (SmartHttpClient), 需要推广到所有外部调用
- **降级策略**: LLM 不可用 → 降级到规则清洗; QMT 断连 → 停止下单但继续监控
- **Tenacity**: Python 重试库, 比自研更健壮

**落地方案:**
```python
from tenacity import retry, stop_after_attempt, wait_exponential, CircuitBreaker

breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)

@breaker
@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=30))
def call_external_api(url: str):
    ...

class DegradationManager:
    """统一降级管理"""
    LEVELS = {
        "normal": "全功能运行",
        "degraded_llm": "LLM 不可用, 降级到规则清洗",
        "degraded_data": "数据源异常, 使用缓存数据",
        "degraded_trade": "QMT 断连, 停止下单, 继续监控",
        "emergency": "全部暂停, 仅告警",
    }
```

**参考文档:**
- [Tenacity](https://tenacity.readthedocs.io/) — Python 重试库
- [Circuit Breaker Pattern (Martin Fowler)](https://martinfowler.com/bliki/CircuitBreaker.html)
- [Resilience4j Design Patterns](https://resilience4j.readme.io/docs/circuitbreaker)

---
