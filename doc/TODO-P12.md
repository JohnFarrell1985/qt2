# P1.2: 赚钱效应 ROI (次优先 — 做了能多赚钱)

> 最后更新: 2026-04-12
>
> 14 项 | 预估工作量 ~41 天
>
> 优先级说明: 新策略/因子扩充/组合优化/情绪引擎/择时信号 — 直接提升系统盈利能力
>
> 返回总览: [TODO.md](TODO.md) | 同级: ~~P1.1 系统风险~~ (✅ 已完成) | [P1.3 工程化](TODO-P13.md)

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

> **ETF 幸存者偏差警告 (架构审查新增):**
> ETF 同样存在幸存者偏差 — 过去 10 年退市/清盘的 A 股 ETF 约 200+ 只 (尤其小规模主题 ETF)。回测时:
> 1. ETF 候选池必须使用 **Point-in-Time** 数据: 在每个回测日期, 仅包含当时已上市且未清盘的 ETF
> 2. 对 `日均成交额 ≥ 1 亿元` 的筛选条件也要 PIT: 用回测日期前 N 日的历史成交额
> 3. 清盘 ETF 的最后净值通常接近面值 (而非归零), 但流动性枯竭阶段可能导致显著滑点
> 4. 建议: 仅选规模 ≥ 10 亿元的主流宽基/行业 ETF, 规避清盘风险

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
| numpy | >=2.0 | ✅ 2026最新2.4.4 | 动量计算 / 线性回归 |
| scipy.stats | >=1.15 | ✅ 2026最新1.17.1 | 线性回归 R² |
| pandas | >=2.2 (兼容 3.0) | ✅ 2026最新3.0.2 | 时间序列处理 |
| skfolio (可选) | >=0.15 | ✅ 2026最新0.15.7 | 若启用 CAA 权重优化 |

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

### P1-21: 多源因子管线 (Qlib Alpha158 + 迅投基本面 + 自动筛选)

| 属性 | 内容 |
|------|------|
| **模块** | factor |
| **文件** | 新增 `src/factor/alpha158.py`, `src/factor/xt_factor_loader.py`, `src/factor/auto_screen.py`, 修改 `src/factor/factor_pool.py` |
| **工作量** | 4-5 天 |

**为什么要做:**

当前 `src/factor/factor_calc.py` 仅有 **11 个手工技术因子** (动量/波动率/RSI/MACD 等)。这远远不够:
- 微软 Qlib Alpha158 有 **158 个**经过 LGB/Transformer 广泛验证的量价因子
- 因子数量少 → LGB 欠拟合 → 选股 IC 低 → 策略收益差
- 迅投因子看板有约 100-200 个**基本面因子** (财务/质量/成长/每股)，是量价因子的重要补充，但尚未接入系统
- 缺少自动化因子筛选管线: 目前 `factor_analysis.py` 只有单因子 IC/ICIR 计算，没有批量筛选、衰减检测、相关性去重

**因子库来源对比分析:**

| 来源 | 因子数 | 类型 | 获取方式 | 免费性 | IC 基准 | 适合角色 |
|------|--------|------|---------|--------|---------|---------|
| **Qlib Alpha158** (微软) | 158 | 量价二次加工 (6大类) | OHLCV 自算, 纯 pandas/numpy | 完全免费 | IC 0.02-0.04 (CSI300/500 公开验证) | **主力量价因子** |
| **迅投因子看板** | ~100-200 | 基本面 (8大类: 成长/质量/每股/情绪/风险/动量/基础/技术) | `xtdata.download_metatable_data()`, 本地 feather | 内测免费 (正式收费待定) | 无公开基准 | **基本面补充** |
| **聚宽 Alpha101** | 101 | WorldQuant 量价 | `jqdatasdk` API, 限频 30次/秒 | 试用版仅前15-3月数据 | 社区测评 IC ~0.02 | 可选验证 |
| **聚宽 Alpha191** | 191 | 国泰君安短周期量价 | `jqdatasdk` API, 计算慢易超时 | 同上 | 社区测评 IC ~0.01-0.03 | 可选验证 |
| **自研 (当前)** | 11 | 手工技术指标 | 已有 `factor_calc.py` | — | 未测 | 保留合并 |
| **FactorEngine (2026 SOTA)** | 自动挖掘 | LLM 引导代码因子 | 已在 P2-18 覆盖 | — | SOTA | 远期增强 |

**推荐结论:** 聚宽和迅投都不够单独依赖。最优策略是 **"Qlib Alpha158 自算 + 迅投基本面 + 自动筛选"**, 聚宽作为可选验证源。

**业界最佳实践:**

- **Qlib Alpha158** (微软, 39.8k Star): A 股量化标杆因子集，6 大类 158 个因子，经过 LightGBM, XGBoost, CatBoost, Transformer, Localformer 等 10+ 模型广泛验证。CSI300 上 IC 0.02-0.04, Sharpe 0.37-0.66。因子纯基于 OHLCV 数据计算，无外部 API 依赖
- **因子预处理流水线 (标准三步)**: 去极值(MAD) → 行业/市值中性化(OLS) → Z-score 标准化。中性化后因子年化收益提升 ~3%
- **自动筛选标准**: IC > 0.03 且 ICIR > 0.3 为有效因子; IC 正比例 > 55% 为稳定因子; Pearson 相关性 > 0.7 的因子组保留 IC 最高者
- **因子衰减检测**: 滚动 60 日 IC 的半衰期, 若半衰期 < 20 日则标记为衰减因子, 降低权重或剔除
- **FactorEngine (arXiv:2603.16365, 2026.03)**: LLM 引导的程序级因子挖掘，因子表达为可执行代码，IC/ICIR 达到 SOTA。已在 P2-18 (RD-Agent) 中部分覆盖

**三层因子架构:**

```
Layer 1: Qlib Alpha158 自算 (OHLCV 量价因子, 158个, 无外部依赖)
    ↓ calc_alpha158(daily_df) → 158 列
Layer 2: 迅投因子看板 (基本面/财务/质量/成长, ~100个, xtdata API)
    ↓ load_xt_factors(stock_list, factor_categories) → ~100 列
Layer 3: (可选) 聚宽补充 (Alpha101/191 验证, jqdatasdk API)
    ↓ load_jq_factors(stock_list, alpha_ids) → 验证用
         ↓
统一注册到 FactorPool (factor_name, source, category, ic_mean, ic_ir)
         ↓
自动预处理: MAD去极值 → 行业/市值中性化 → Z-score
         ↓
自动筛选: IC>0.03 & ICIR>0.3 & 衰减检测 & 相关性去重(<0.7)
         ↓
输出: 精选因子矩阵 → LGB/XGB/CatBoost 训练
```

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| pandas | >=2.2 (兼容 3.0) | ✅ 2026最新3.0.2 | Alpha158 因子计算, 预处理 |
| numpy | >=2.0 | ✅ 2026最新2.4.4 | 向量化运算 |
| scipy | >=1.15 | ✅ 2026最新1.17.1 | 相关性矩阵, 统计检验 |
| scikit-learn | >=1.7 | ✅ 2026最新1.8.0 | OLS 中性化 |
| xtquant (xtdata) | 已集成 | ✅ | 迅投因子数据下载 |
| jqdatasdk | >=1.9 | ✅ | 聚宽因子调用 (可选) |
| jqfactor_analyzer | >=2.4 | ✅ 2025.02 | 聚宽因子分析工具 (可选) |

**参考文档:**
- Qlib Alpha158 数据集: [github.com/microsoft/qlib (Alpha158 handler)](https://github.com/microsoft/qlib/blob/main/qlib/contrib/data/handler.py)
- Qlib Alpha158 详解: [158个量化因子如何提升策略收益](https://blog.gitcode.com/5d9a4f79559912ac9f7d1b83f61b59a4.html)
- Qlib 模型基准 (IC/Sharpe 对比): [github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md](https://github.com/microsoft/qlib/blob/main/examples/benchmarks/README.md)
- 聚宽 Alpha101 因子库: [joinquant.com/data/dict/alpha101](https://www.joinquant.com/data/dict/alpha101)
- 聚宽 Alpha191 因子库: [joinquant.com/data/dict/alpha191](https://www.joinquant.com/data/dict/alpha191)
- 聚宽因子分析工具: [github.com/JoinQuant/jqfactor_analyzer](https://github.com/JoinQuant/jqfactor_analyzer)
- 迅投因子数据文档: [dict.thinktrader.net/dictionary/xuntou_factor.html](https://dict.thinktrader.net/dictionary/xuntou_factor.html)
- 迅投因子获取 API: [dict.thinktrader.net/nativeApi/xtdata.html](http://dict.thinktrader.net/nativeApi/xtdata.html)
- FactorEngine (2026 SOTA): [arXiv:2603.16365](https://arxiv.org/abs/2603.16365) — LLM 引导的程序级因子挖掘
- 因子预处理最佳实践: [聚宽因子预处理指南](https://iris.findtruman.io/ai/tool/ai-quantitative-trading/e/joinquant/factor-data-preprocessing)
- LGB+158因子 A股十年实证: [年化24%, 回撤10%](http://www.360doc.com/content/23/1012/15/1099933775_1099933775.shtml)
- 多因子选股工程化 Pipeline: [github.com/Parsnip77/Multi-factor-Model-for-Stock-Selection](https://github.com/Parsnip77/Multi-factor-Model-for-Stock-Selection)
- 因子检验深度解析: [量化投资进阶：因子检验](https://cloud.baidu.com/article/3790846)

**落地方案:**

**子任务 1: Alpha158 因子计算器** (1.5 天)

参考 Qlib `Alpha158` handler 实现 6 大类 158 个量价因子:

| 类别 | 因子数 | 代表因子 | 说明 |
|------|--------|---------|------|
| KBAR (K线形态) | ~16 | `(close-open)/open`, `(high-low)/close` | 日内价格结构 |
| PRICE (价格趋势) | ~18 | `close/close_5d`, `close/close_20d` | 多周期价格动量 |
| VOLUME (成交量) | ~18 | `vol/vol_5d`, `vol_5d/vol_20d` | 量能变化 |
| STD (波动率) | ~6 | `std_5d`, `std_20d`, `std_60d` | 多周期波动 |
| RSRS (阻力支撑) | ~6 | `high_max_5d/close`, `low_min_5d/close` | 价格极值 |
| CORR/COV/BETA | ~94 | `corr(close, vol, 5d)`, `beta(close, index, 20d)` | 量价相关性、市场 beta |

```python
class Alpha158Calculator:
    """Qlib Alpha158 因子计算器 (纯 pandas/numpy, 不依赖 Qlib 框架)"""

    WINDOWS = [5, 10, 20, 30, 60]

    def calc(self, df: pd.DataFrame) -> pd.DataFrame:
        """输入: 单股 OHLCV 日线, 输出: 附加 158 个因子列"""
        result = df.copy()
        c, o, h, l, v = df['close'], df['open'], df['high'], df['low'], df['volume']

        # KBAR 因子
        result['KBAR_open'] = (c - o) / o
        result['KBAR_high'] = (h - l) / o
        result['KBAR_close'] = (c - o) / (h - l + 1e-12)
        result['KBAR_upper'] = (h - np.maximum(o, c)) / (h - l + 1e-12)
        result['KBAR_lower'] = (np.minimum(o, c) - l) / (h - l + 1e-12)

        for w in self.WINDOWS:
            # PRICE 因子: 多周期动量
            result[f'PRICE_mom_{w}'] = c / c.shift(w) - 1
            result[f'PRICE_mean_{w}'] = c / c.rolling(w).mean()

            # VOLUME 因子
            result[f'VOL_mean_{w}'] = v.rolling(w).mean() / (v.rolling(w * 4).mean() + 1e-12)
            result[f'VOL_std_{w}'] = v.rolling(w).std() / (v.rolling(w).mean() + 1e-12)

            # STD 因子
            ret = c.pct_change()
            result[f'STD_{w}'] = ret.rolling(w).std()

            # RSRS 因子
            result[f'RSRS_high_{w}'] = h.rolling(w).max() / c
            result[f'RSRS_low_{w}'] = l.rolling(w).min() / c

            # CORR 因子: 量价相关性
            result[f'CORR_cv_{w}'] = c.rolling(w).corr(v)
            result[f'CORR_hv_{w}'] = h.rolling(w).corr(v)

            # BETA 因子: 量变率 vs 价变率
            result[f'COV_cv_{w}'] = c.pct_change().rolling(w).cov(
                v.pct_change()
            )

        return result
```

**子任务 2: 迅投因子接入** (1 天)

```python
class XtFactorLoader:
    """迅投因子看板数据加载器"""

    FACTOR_CATEGORIES = [
        'factor_growth',           # 成长类
        'factor_base_derivative',  # 基础科目及衍生
        'factor_metrics',          # 每股指标
        'factor_quality',          # 质量类
        'factor_momentum',         # 动量类
        'factor_risk',             # 风险/风格类
        'factor_sentiment',        # 情绪类
        'factor_technical',        # 技术指标
    ]

    def __init__(self):
        from xtquant import xtdata
        self.xtdata = xtdata

    def download_all(self):
        """下载全部因子元数据和数据"""
        self.xtdata.download_metatable_data()
        metainfo = self.xtdata.get_metatable_list()
        logger.info(f"迅投因子看板共 {len(metainfo)} 个因子")
        return metainfo

    def load_factor(self, stock_list: list[str], factor_category: str) -> pd.DataFrame:
        """加载指定类别的因子数据"""
        import os
        datadir = os.path.join(self.xtdata.data_dir, factor_category)
        frames = []
        for factor_file in os.listdir(datadir):
            if factor_file.endswith('_Xdat2'):
                data_path = os.path.join(datadir, factor_file, 'data.fe')
                if os.path.exists(data_path):
                    df = pd.read_feather(data_path)
                    frames.append(df)
        if frames:
            return pd.concat(frames, axis=1)
        return pd.DataFrame()

    def register_to_pool(self, pool: FactorPool, metainfo: dict):
        """将迅投因子注册到 FactorPool"""
        for en_name, zh_name in metainfo.items():
            pool.register(
                factor_name=en_name,
                category=self._guess_category(en_name),
                description=zh_name,
                data_source='xuntou',
            )
```

**子任务 3: 自动筛选管线** (1.5 天)

```python
class AutoFactorScreen:
    """自动因子筛选: IC阈值 + ICIR + 衰减检测 + 相关性去重"""

    def __init__(
        self,
        ic_threshold: float = 0.03,
        icir_threshold: float = 0.3,
        ic_positive_ratio: float = 0.55,
        corr_threshold: float = 0.7,
        decay_halflife_min: int = 20,
    ):
        self.ic_threshold = ic_threshold
        self.icir_threshold = icir_threshold
        self.ic_positive_ratio = ic_positive_ratio
        self.corr_threshold = corr_threshold
        self.decay_halflife_min = decay_halflife_min

    def screen(
        self,
        factor_matrix: pd.DataFrame,
        forward_returns: pd.Series,
    ) -> list[str]:
        """
        输入: 截面因子矩阵 (index=日期x股票, columns=因子名)
        输出: 通过筛选的因子名列表
        """
        # Step 1: IC/ICIR 阈值筛选
        ic_results = {}
        for col in factor_matrix.columns:
            ic_series = calc_ic_series(factor_matrix, forward_returns, col)
            ic_mean = abs(ic_series.mean())
            icir = abs(calc_icir(ic_series))
            pos_ratio = (ic_series > 0).mean() if len(ic_series) > 0 else 0

            if (ic_mean >= self.ic_threshold
                and icir >= self.icir_threshold
                and pos_ratio >= self.ic_positive_ratio):
                ic_results[col] = {
                    'ic_mean': ic_mean, 'icir': icir,
                    'pos_ratio': pos_ratio, 'ic_series': ic_series
                }

        passed = list(ic_results.keys())
        logger.info(f"IC/ICIR 筛选: {len(factor_matrix.columns)} → {len(passed)}")

        # Step 2: 因子衰减检测 (滚动 IC 半衰期)
        non_decayed = []
        for col in passed:
            rolling_ic = ic_results[col]['ic_series'].rolling(60).mean()
            if self._halflife(rolling_ic) >= self.decay_halflife_min:
                non_decayed.append(col)
        logger.info(f"衰减检测: {len(passed)} → {len(non_decayed)}")

        # Step 3: 相关性去重 (Pearson > 0.7 保留 IC 高者)
        if len(non_decayed) < 2:
            return non_decayed

        corr_matrix = factor_matrix[non_decayed].corr()
        to_drop = set()
        for i in range(len(non_decayed)):
            if non_decayed[i] in to_drop:
                continue
            for j in range(i + 1, len(non_decayed)):
                if non_decayed[j] in to_drop:
                    continue
                if abs(corr_matrix.iloc[i, j]) > self.corr_threshold:
                    ic_i = ic_results[non_decayed[i]]['ic_mean']
                    ic_j = ic_results[non_decayed[j]]['ic_mean']
                    drop = non_decayed[j] if ic_i >= ic_j else non_decayed[i]
                    to_drop.add(drop)

        final = [f for f in non_decayed if f not in to_drop]
        logger.info(f"相关性去重: {len(non_decayed)} → {len(final)}")
        return final

    @staticmethod
    def _halflife(series: pd.Series) -> float:
        """计算 IC 序列半衰期 (OLS 拟合指数衰减)"""
        valid = series.dropna()
        if len(valid) < 10:
            return float('inf')
        y = np.log(np.abs(valid) + 1e-12)
        X = np.arange(len(y)).reshape(-1, 1)
        from sklearn.linear_model import LinearRegression
        model = LinearRegression().fit(X, y)
        lam = model.coef_[0]
        if lam >= 0:
            return float('inf')
        return -np.log(2) / lam
```

**子任务 4 (可选): 聚宽因子接入** (1 天)

```python
class JqFactorLoader:
    """聚宽因子加载器 (可选验证源)"""

    def __init__(self, username: str, password: str):
        import jqdatasdk as jq
        jq.auth(username, password)
        self.jq = jq

    def load_alpha101(self, date: str, stock_list: list[str], alpha_ids: list[int]) -> pd.DataFrame:
        """加载指定 Alpha101 因子"""
        from jqlib.alpha101 import alpha_001  # noqa: 动态导入
        results = {}
        for aid in alpha_ids:
            fn = getattr(__import__(f'jqlib.alpha101', fromlist=[f'alpha_{aid:03d}']), f'alpha_{aid:03d}')
            results[f'alpha101_{aid:03d}'] = fn(date, stock_list)
        return pd.DataFrame(results)
```

**.env 新增参数:**
```env
# ===== 多源因子管线 (P1-21) =====
FACTOR_ALPHA158_ENABLED=true               # 启用 Alpha158 自算因子
FACTOR_ALPHA158_WINDOWS=5,10,20,30,60      # Alpha158 滚动窗口列表
FACTOR_XT_ENABLED=true                     # 启用迅投因子看板
FACTOR_XT_CATEGORIES=factor_growth,factor_base_derivative,factor_metrics,factor_quality,factor_momentum,factor_risk
FACTOR_JQ_ENABLED=false                    # 启用聚宽因子 (可选, 需账号)
FACTOR_JQ_USERNAME=                        # 聚宽账号
FACTOR_JQ_PASSWORD=                        # 聚宽密码
FACTOR_SCREEN_IC_THRESHOLD=0.03            # IC 筛选阈值
FACTOR_SCREEN_ICIR_THRESHOLD=0.3           # ICIR 筛选阈值
FACTOR_SCREEN_IC_POSITIVE_RATIO=0.55       # IC 正比例阈值
FACTOR_SCREEN_CORR_THRESHOLD=0.7           # 相关性去重阈值
FACTOR_SCREEN_DECAY_HALFLIFE_MIN=20        # 因子衰减半衰期最低天数
```

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
| **skfolio** | >=0.15 | ✅ 2026最新0.15.7 | 基于 scikit-learn 的组合优化库，100+模型，支持 MVO/Risk Parity/HRP/Black-Litterman，内置 WalkForward CV |
| **cvxpy** | >=1.5 | ✅ | 凸优化求解器，skfolio 底层依赖 |
| **Riskfolio-Lib** | >=7.2 | ✅ | 另一选择，24+ 凸风险度量 |
| **riskparity.py** | >=0.1 | ✅ | 专用风险平价库 |
| numpy | >=2.0 | ✅ 2026最新2.4.4 | 协方差矩阵 + 向量化运算 |
| pandas | >=2.2 (兼容 3.0) | ✅ 2026最新3.0.2 | 动量计算 + 时间序列 |

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
| statsmodels | >=0.14 | ✅ 2026最新0.14.6 | 截面 OLS 回归 |
| numpy | >=2.0 | ✅ | 因子矩阵构建 |
| pandas | >=2.2 (兼容 3.0) | ✅ | 截面操作 |

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
4. **Regime-Aware 重训练 (架构审查新增)**:
   - 使用 Hidden Markov Model (HMM, 2-3 状态) 检测当前市场 regime (牛/熊/震荡)
   - **regime 切换时触发紧急重训练**, 而非等待固定 6 月窗口
   - 训练时加入 regime 标签作为特征, 使模型学会"在不同环境下使用不同因子权重"
   - 参考: [Regime Detection for Systematic Trading (Man AHL)](https://www.man.com/maninstitute/regime-based-asset-allocation)
   - 技术: `hmmlearn>=0.3` (scikit-learn 兼容 HMM) 或 `pomegranate>=1.1` (GPU 加速)

---

### P1-30: BaseFactor ABC + FactorRegistry (因子一等公民)

| 属性 | 内容 |
|------|------|
| **模块** | factor |
| **文件** | 新增 `src/factor/base.py`, 修改 `src/factor/factor_pool.py` |
| **工作量** | 1 天 |
| **优先级** | **中 — 架构审查新增, 建议在 P1-21 之前实施** |

**为什么要做:**

当前因子以 "函数" 形式散落在 `factor_calc.py` 中, 没有统一的抽象基类。这导致:
- 因子没有统一的元数据 (名称/类别/数据源/版本/计算窗口)
- 无法自动发现和注册因子
- P1-21 引入 Alpha158 + 迅投后, 因子数量从 11 个膨胀到 300+, 缺乏管理框架

**落地方案:**

```python
from abc import ABC, abstractmethod

class BaseFactor(ABC):
    """因子抽象基类 — 所有因子的一等公民"""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def category(self) -> str: ...

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def data_source(self) -> str:
        return "ohlcv"

    @property
    def lookback_days(self) -> int:
        return 60

    @abstractmethod
    def compute(self, df: pd.DataFrame) -> pd.Series:
        """计算单只标的的因子值"""
        ...

class FactorRegistry:
    """因子注册表 — 自动发现 + 元数据管理"""
    _factors: dict[str, BaseFactor] = {}

    @classmethod
    def register(cls, factor: BaseFactor):
        cls._factors[factor.name] = factor

    @classmethod
    def get(cls, name: str) -> BaseFactor:
        return cls._factors[name]

    @classmethod
    def list_by_category(cls, category: str) -> list[BaseFactor]:
        return [f for f in cls._factors.values() if f.category == category]
```

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

### P1-33: 北向资金流 Regime 信号

| 属性 | 内容 |
|------|------|
| **模块** | sentiment |
| **文件** | `src/sentiment/northbound_flow.py` (新增), 修改 `src/sentiment/composite_index.py` |
| **工作量** | 1.5 天 |
| **优先级** | **高 — 研究驱动, Quick Win, A 股特有 alpha 信号** |

**为什么要做:**

北向资金 (沪股通 + 深股通) 是 A 股最公开、最易获取的"聪明钱"代理变量:
- 学术: Pacific-Basin Finance Journal 等多篇论文实证北向净流入对 A 股次日/次周收益有显著预测力 (月度异常收益 0.54%-0.64%)
- 实务: 东方财富/同花顺等主流平台将北向资金作为核心情绪指标
- 数据源: AKShare `stock_hsgt_north_net_flow_in` 免费提供, 无需额外成本

**学术依据:**
- *Northbound Capital and A-Share Market Predictability*, Pacific-Basin Finance Journal (2025)
- *Foreign Investor Flows and Stock Returns in China*, Emerging Markets Finance and Trade (2025)
- 东方财富/富途北向资金数据文档

**落地方案:**

```python
class NorthboundFlowSignal:
    """北向资金流信号 — 情绪引擎增强"""

    def compute(self, flow_df: pd.DataFrame) -> dict:
        net_flow_5d = flow_df['net_flow'].rolling(5).sum()
        net_flow_20d = flow_df['net_flow'].rolling(20).sum()
        flow_momentum = net_flow_5d / (net_flow_20d.abs() + 1e-6)

        # Z-score 标准化
        z_score = (flow_momentum - flow_momentum.rolling(60).mean()) / \
                  (flow_momentum.rolling(60).std() + 1e-6)

        return {
            "nb_flow_5d": net_flow_5d.iloc[-1],
            "nb_flow_20d": net_flow_20d.iloc[-1],
            "nb_flow_z": z_score.iloc[-1],
            "nb_regime": "risk_on" if z_score.iloc[-1] > 0.5 else
                         "risk_off" if z_score.iloc[-1] < -0.5 else "neutral",
        }
```

集成至情绪合成指数 (P1-16) 作为第 7 维信号源。

**参考文档:**
- AKShare 北向资金: [akshare.akfamily.xyz](https://akshare.akfamily.xyz/data/stock/stock.html#id10)
- [北向资金与 A 股行情预测实证](https://finance.sina.com.cn/stock/)

---

### P1-34: alphalens 标准因子质量门控

| 属性 | 内容 |
|------|------|
| **模块** | factor |
| **文件** | `src/factor/quality_gate.py` (新增), 修改 `src/factor/auto_screen.py` (P1-21) |
| **工作量** | 1.5 天 |
| **优先级** | **中 — 研究驱动, 与 P1-21 协同** |

**为什么要做:**

当前因子筛选仅有自研 IC/ICIR 计算。alphalens (Quantopian, 4,216 stars) 是业界标准的因子分析工具, 提供:
- **IC 时序分析**: 滚动 IC、IC 热力图、IC 衰减曲线
- **分层回测**: 按因子分位数分组, 计算各组累计收益、Sharpe
- **换手率分析**: 每期因子排名变化导致的交易成本估算
- **事件分析**: 因子值变化后 N 日的平均收益

将 alphalens 集成为因子"入库前的质量门控", 可避免低质量因子进入 ML 训练, 直接提升模型性能。

**学术依据:**
- Quantopian alphalens (4,216 stars): https://github.com/quantopian/alphalens
- alphalens-reloaded (社区维护版): 兼容 pandas 2.x+

**落地方案:**

```python
from alphalens.utils import get_clean_factor_and_forward_returns
from alphalens.performance import factor_information_coefficient, mean_return_by_quantile

class AlphalensQualityGate:
    """基于 alphalens 的标准因子质量门控"""

    PASS_CRITERIA = {
        "ic_mean_abs": 0.025,       # |IC| > 2.5%
        "icir_abs": 0.3,            # |ICIR| > 0.3
        "quantile_spread": 0.005,   # Q5-Q1 日均收益差 > 0.5%
        "monotonicity": 0.6,        # 分位数收益单调性 > 60%
    }

    def evaluate(self, factor_data, prices) -> dict:
        merged = get_clean_factor_and_forward_returns(factor_data, prices)
        ic = factor_information_coefficient(merged)
        quantile_returns = mean_return_by_quantile(merged)

        result = {
            "ic_mean": ic.mean().values[0],
            "ic_std": ic.std().values[0],
            "icir": ic.mean().values[0] / (ic.std().values[0] + 1e-12),
            "quantile_spread": (quantile_returns.iloc[-1] - quantile_returns.iloc[0]).values[0],
            "passed": True,
        }
        # 门控检查
        if abs(result["ic_mean"]) < self.PASS_CRITERIA["ic_mean_abs"]:
            result["passed"] = False
        if abs(result["icir"]) < self.PASS_CRITERIA["icir_abs"]:
            result["passed"] = False
        return result
```

**技术选型:**

| 技术 | 版本 | 说明 |
|------|------|------|
| **alphalens-reloaded** | >=0.0.14 | pandas 2.x 兼容的社区维护版 |

**参考文档:**
- alphalens: [github.com/quantopian/alphalens](https://github.com/quantopian/alphalens)
- [因子评估实践指南 (Medium)](https://medium.com/@er.mananjain26/separating-signal-from-noise-a-practical-guide-to-evaluating-alpha-factors-with-alphalens-b883070aab14)

---

### P1-36: Riskfolio-Lib ETF 风险预算优化

| 属性 | 内容 |
|------|------|
| **模块** | strategy / portfolio |
| **文件** | `src/portfolio/riskfolio_optimizer.py` (新增), 修改 P1-20 的 `src/strategy/etf_rotation/rotator.py` |
| **工作量** | 2 天 |
| **优先级** | **中 — 研究驱动, 增强 P1-05 和 P1-20** |

**为什么要做:**

P1-05 设计了 CAAOptimizer (Keller 2015) 和 skfolio 两种组合优化方案。研究表明, **Riskfolio-Lib** (4,049 stars) 在以下场景比 skfolio 更实用:

1. **风险预算 (Risk Budgeting)**: 允许为不同资产类别设定风险贡献上限 (如 A 股 ETF 风险贡献 ≤40%, 黄金 ≤20%)
2. **多种风险度量**: CVaR, CDaR, EVaR 等 24+ 凸风险度量, 比 skfolio 更丰富
3. **战术资产配置**: 专为 TAA (P1-20 ETF 轮动) 设计的工作流

**学术依据:**
- Riskfolio-Lib: https://github.com/dcajasn/Riskfolio-Lib (4,049 stars)
- PyPortfolioOpt: https://github.com/robertmartin8/PyPortfolioOpt (5,632 stars)
- Maillard, Roncalli & Teiletche (2010): *The Properties of Equally Weighted Risk Contribution Portfolios*

**落地方案:**

```python
import riskfolio as rp

class RiskfolioETFOptimizer:
    """基于 Riskfolio-Lib 的 ETF 风险预算优化"""

    def optimize(self, returns: pd.DataFrame, risk_budget: dict = None) -> dict:
        port = rp.Portfolio(returns=returns)
        port.assets_stats(method_mu='hist', method_cov='hist')

        if risk_budget:
            # 风险预算模式: 每类资产的风险贡献约束
            w = port.rp_optimization(
                model='Classic',
                rm='CVaR',            # 条件风险价值
                rf=0.02,              # 无风险利率
                b=pd.Series(risk_budget),  # 风险预算向量
            )
        else:
            # 最大夏普模式
            w = port.optimization(
                model='Classic',
                rm='CVaR',
                obj='Sharpe',
                rf=0.02,
                hist=True,
            )
        return w.to_dict()
```

**技术选型:**

| 技术 | 版本 | 说明 |
|------|------|------|
| **Riskfolio-Lib** | >=7.2 | ✅ 2026 最新 | 24+ 凸风险度量, 战术配置 |
| **PyPortfolioOpt** | >=1.5 | ✅ | HRP / Black-Litterman (可选替代) |

**参考文档:**
- Riskfolio-Lib: [riskfolio-lib.readthedocs.io](https://riskfolio-lib.readthedocs.io/)
- PyPortfolioOpt: [pyportfolioopt.readthedocs.io](https://pyportfolioopt.readthedocs.io/)

---

### P1-37: 跨资产 Regime 上下文 (情绪引擎增强)

| 属性 | 内容 |
|------|------|
| **模块** | sentiment |
| **文件** | `src/sentiment/cross_asset_regime.py` (新增), 修改 `src/sentiment/macro_classifier.py` |
| **工作量** | 2 天 |
| **优先级** | **中 — 研究驱动, 增强 P1-17 宏观状态分类** |

**为什么要做:**

当前宏观状态分类器 (P1-17) 主要基于 A 股自身数据 (量价情绪、融资、期权等)。2025-2026 研究表明:

1. **跨资产动量信号** 可显著改善 A 股择时: 商品/利率/汇率信号领先于 A 股 (因 A 股散户反应滞后)
2. **波动率择时** (VIX/iVIX 类): 高波动环境下降低权益敞口, 可改善风险调整后收益
3. **相关性监控**: 跨资产相关性突增 → 系统性风险信号 (如 2020/2022 年)

**学术依据:**
- *Improved Cross-Asset Time-Series Momentum (I-XTSM)*, 学术期刊 2025
- Fleming, Kirby & Ostdiek (2001): *The Economic Value of Volatility Timing*
- SSRN 中国股债跨资产动量研究

**数据源 (免费):**
- AKShare: 黄金/原油/美元指数/VIX/10年国债收益率
- yfinance: 全球指数/商品/汇率 (已在 datacollect 中支持)

**落地方案:**

```python
class CrossAssetRegime:
    """跨资产 Regime 信号 — 商品/债券/汇率/波动率"""

    ASSETS = {
        "gold": "518880.SH",        # 黄金 ETF
        "usd_cny": "USD/CNY",       # 美元/人民币 (akshare)
        "us_10y": "^TNX",           # 美国 10 年国债收益率 (yfinance)
        "vix": "^VIX",              # VIX 恐慌指数 (yfinance)
        "copper": "HG=F",           # 铜期货 (经济先行指标)
    }

    def compute_regime_context(self, prices: dict[str, pd.Series]) -> dict:
        signals = {}
        for name, series in prices.items():
            mom_20d = series.iloc[-1] / series.iloc[-20] - 1
            signals[f"{name}_mom_20d"] = mom_20d

        # 综合判断
        risk_on_count = sum(1 for v in signals.values() if v > 0)
        total = len(signals)
        risk_score = risk_on_count / total  # 0=全面risk_off, 1=全面risk_on

        return {
            **signals,
            "cross_asset_risk_score": risk_score,
            "cross_asset_regime": "risk_on" if risk_score > 0.6
                                  else "risk_off" if risk_score < 0.4
                                  else "neutral",
        }
```

集成至 P1-17 宏观状态分类器, 作为额外输入维度。

**参考文档:**
- AKShare 全球市场数据: [akshare.akfamily.xyz](https://akshare.akfamily.xyz/)
- yfinance 全球数据: [github.com/ranaroussi/yfinance](https://github.com/ranaroussi/yfinance)
- [Cross-Asset Correlation Dashboard (AhaSignals)](https://ahasignals.com/)

---
