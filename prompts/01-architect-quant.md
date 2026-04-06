# 系统架构师 + 量化分析师 — 补充参考

> 精简版 (自动加载): `.cursor/agents/architect-quant.md`
> 本文档是补充参考, 包含精简版中没有的详细信息, Agent 按需 `Read` 查阅

---

## 一、详细模块清单

### 已实现模块 (8 个, 代码在 `src/`)

| 模块 | 路径 | 核心文件 | 说明 |
|------|------|---------|------|
| 公共基础 | `src/common/` | `config.py`, `db.py`, `logger.py` | pydantic-settings 配置 / SQLAlchemy / 日志 |
| 数据下载 | `src/data/` | `models.py`, `qmt_client.py`, `download_engine.py`, `sync.py`, `market_data.py`, `factor_data.py`, `financial_data.py`, `cb_data.py` | QMT 引擎 + ORM (Stock, StockDaily, MarketIndex 等) |
| 因子工程 | `src/factor/` | `factor_calc.py`, `factor_preprocess.py`, `factor_analysis.py`, `factor_pool.py` | 11 手工因子 + MAD/中性化/Z-score + IC 分析 |
| 机器学习 | `src/ml/` | `lgb_model.py`, `dataset.py`, `auto_iterate.py`, `feature_selection.py`, `model_evaluation.py`, `strategy_builder.py` | LightGBM 训练 + 自动迭代 + 评估 |
| 策略引擎 | `src/strategy/` | `base.py`, `orchestrator.py`, `position_monitor.py`, `signal_arbiter.py`, `position_sizer.py`, `scoring.py`, `ml_strategy.py`, `rules/*.py` | 10 策略 + Orchestrator + Monitor + Arbiter + Sizer |
| 回测引擎 | `src/backtest/` | `engine.py`, `engine_minute.py`, `strategy_runner.py`, `data_loader.py`, `performance.py`, `fees.py` | 日线/分钟线回测 + 绩效 |
| 交易模块 | `src/trading/` | `qmt_trader.py`, `live_trading.py`, `paper_trading.py`, `order_manager.py`, `position_manager.py`, `risk_control.py`, `trade_log.py` | QMT 交易 + 风控 + 模拟盘 + 实盘 |
| API 服务 | `src/api/` | `main.py`, `scheduler.py`, `routers/` (8 个 router) | FastAPI 路由 |

### 设计完成待实现模块 (7 个, 有文档无代码)

| 模块 | 路径 | 设计文档 | 说明 |
|------|------|---------|------|
| 数据采集 | `src/datacollect/` | `doc/12-数据采集模块.md` | 五层反爬 + 令牌桶限流 + 幂等采集 |
| 数据清洗 | `src/dataclean/` | `doc/13-数据清洗与LLM.md` | LLM 清洗 + Schema 注册表 + 三级降级 |
| 情绪引擎 | `src/sentiment/` | `doc/11-市场情绪引擎.md` | 6 维合成情绪指数 + 宏观状态分类 |
| ETF 轮动 | `src/strategy/etf_rotation/` | `doc/14-ETF资产配置轮动.md` | VAA/DAA/CAA + 崩盘保护 + 全球配置 |
| 知识蒸馏 | `src/distill/` | `doc/TODO-P2.md` P2-19~21 | 多教师共识 + LoRA/DPO + 数据飞轮 |
| 组合优化 | `src/portfolio/` | `doc/TODO-P1.md` | CAA/MVO + skfolio + Barra 风险归因 |
| 系统监控 | `src/monitoring/` | `doc/TODO-P1.md` P1-26 | 因子衰减 + 模型漂移 + 拥挤度 + 飞书告警 |

---

## 二、完整技术栈版本

| 类别 | 技术 | 版本 | 用途 |
|------|------|------|------|
| ML | LightGBM | >=4.6 | 主模型 (GBDT) |
| | XGBoost | >=3.0 | Ensemble |
| | CatBoost | >=1.2.10 | Ensemble |
| | scikit-learn | >=1.7 | CV / Pipeline |
| 因子 | Qlib Alpha158 | 自算 | 158 量价因子 |
| | xtquant | 迅投 | 基本面因子 |
| 组合 | skfolio | >=0.15 | 100+ 组合模型 |
| | cvxpy | >=1.5 | 凸优化 |
| 采集 | curl_cffi | >=0.14 | TLS 指纹伪装 |
| | Playwright | >=1.59 | 浏览器级采集 |
| | akshare | >=1.18 | A 股免费数据 |
| LLM | openai SDK | >=2.0 | DeepSeek/Qwen 客户端 |
| | transformers | >=5.0 | HuggingFace 推理 |
| 蒸馏 | peft (LoRA) | >=0.18 | 参数高效微调 |
| | trl (DPO) | >=1.0 | 偏好对齐 |
| | ONNX Runtime | >=1.21 | 生产推理 (INT8) |
| DB | PostgreSQL | >=16 | JSONB + GIN 索引 |
| | SQLAlchemy | >=2.0 | ORM |
| | Alembic | >=1.15 | Schema 迁移 |
| 基础 | FastAPI | >=0.115 | Web API |
| | APScheduler | >=3.11 | 定时调度 |
| | blinker | >=1.9 | 事件总线 |
| | tenacity | >=9.0 | 重试 + 熔断 |
| | structlog | >=25.1 | 结构化日志 |
| | pandera | >=0.23 | 数据质量校验 |
| 统计 | statsmodels | >=0.14 | OLS 中性化 |
| | scipy | >=1.15 | 统计检验 |
| 基础 | pandas | >=2.2 | 数据处理 |
| | numpy | >=2.0 | 向量化运算 |
| | torch | >=2.8 | 深度学习训练 |

---

## 三、三档策略 + ETF 轮动

| 档位 | 类型 | 策略 | 卖出逻辑 |
|------|------|------|----------|
| Tier 1 | 规则 | 动量突破 / 均值反转 / 行业轮动 / 均线突破 / T+1 宽网格 / 低波红利 / 双低可转债 | 各策略独立逻辑 |
| Tier 2 | 打分 | 多因子等权/IC 加权 | 排名跌出后 30% |
| Tier 3 | ML | LightGBM / XGBoost / CatBoost | 模型预测收益低于阈值 |
| **ETF** | **TAA** | **VAA / DAA / R²×Return / CAA** | **动量翻负 → 切至债券/货币** |

---

## 四、代码规范 (架构层面)

### 模块组织
- 每个模块必须有 `__init__.py` 声明公开接口
- 模块间通过接口 (Protocol / ABC) 交互, 不直接 import 内部实现
- 配置统一通过 `src/common/config.py` 的 `settings` 单例管理
- 数据库操作统一通过 `src/common/db.py` 的 `get_session()` 上下文管理器

### 数据模型
- ORM 模型定义在各模块的 `models.py`, 统一继承 `Base`
- API 请求/响应模型用 Pydantic `BaseModel`
- 配置模型用 pydantic-settings `BaseSettings`

### 依赖管理
- 所有依赖声明在 `pyproject.toml` 的 `[project.dependencies]`
- 开发依赖声明在 `[project.optional-dependencies.dev]`
- 版本约束使用 `>=` 最低版本, 不锁定上限

---

## 五、协作协议 (详细)

### 设计交接模板 (发给 Developer)
```
### 设计交接
- TODO 编号: P0-XX
- 涉及模块: [模块列表]
- 接口定义: [函数签名和数据模型]
- 配置参数: [.env 新增项]
- 验收标准: [量化指标, 如 IC > 0.03, Sharpe > 0.5]
- 注意事项: [A 股规则、性能约束等]
```

### 接收来自 Developer 的反馈
- **技术可行性反馈**: 某些设计在工程上不可行, 需要调整
- **性能瓶颈报告**: 实际运行中发现的架构瓶颈
- **依赖冲突**: 新依赖与现有技术栈的兼容性问题
- **文档不一致报告**: 设计文档与实际代码行为不符

### 接收来自 QA 的反馈
- **可测试性问题**: 模块耦合导致难以测试, 需要重新设计
- **文档不一致报告**: 设计文档与代码行为不符
- **覆盖率差距**: 关键模块测试覆盖不足的风险提示

---

## 六、监督清单

### 审查 Developer 代码时
- [ ] 是否遵循模块分层, 无跨层直接调用
- [ ] 数据库操作是否通过 `get_session()`, 无裸 SQL 拼接
- [ ] 配置参数是否通过 `settings` 读取, 无硬编码魔法数字
- [ ] A 股规则是否正确: T+1, 100 股整手, 涨跌停 10%/20% (创业板/科创板)
- [ ] 因子计算是否使用 Point-in-Time 数据, 无前视偏差
- [ ] ML 训练是否使用 Purged Walk-Forward CV, 无数据泄漏
- [ ] 新依赖是否已声明在 `pyproject.toml`

### 审查 QA 测试时
- [ ] 关键业务路径是否有 E2E 测试覆盖
- [ ] 边界条件是否覆盖: 空数据、极端价格、涨跌停、停牌
- [ ] Mock 范围是否合理: 只 mock 外部依赖, 不 mock 核心逻辑
- [ ] 测试数据是否确定性 (固定随机种子), 可复现
- [ ] 是否有回归测试防止已修复 bug 复现

---

## 七、参考资源

### 项目文件
| 文件 | 用途 |
|------|------|
| `README.md` | 架构图 + 模块清单 + 技术栈 + 参考文献 |
| `doc/TODO.md` | 82 项待办总索引 |
| `doc/TODO-P0.md` ~ `doc/TODO-P3.md` | 各优先级任务细节 |
| `doc/TODO-P01.md` | P0.1 数据采集/清洗 (暂缓) |
| `doc/00-总体设计.md` | 架构总览 |
| `doc/02-因子工程.md` | 因子分类 + 预处理 |
| `doc/05-回测引擎.md` | 回测方法论 |
| `doc/11-市场情绪引擎.md` | 情绪特征 + 合成指数 |
| `doc/14-ETF资产配置轮动.md` | VAA/DAA/CAA 策略族 |
| `doc/15-硬件配置指南.md` | 三档硬件方案 |
| `tests/e2e/TODO-E2E.md` | E2E 测试设计 |
| `src/common/config.py` | 全局配置结构 |

### 量化参考文献
- *Advances in Financial Machine Learning* — Marcos López de Prado (Purged CV, 因子预处理)
- *Momentum and Markowitz: A Golden Combination* — Keller, Butler & Kipnis (CAA)
- Deflated Sharpe Ratio — Bailey & López de Prado (多重检验修正)
- Critical Line Algorithm — Bailey & López de Prado (MVO 精确解)
- Barra CNE5/CNE6 — MSCI / 中信建投 (A 股风险模型)
- 《因子投资：方法与实践》 — 石川 (A 股因子实操)
- RD-Agent — Microsoft (LLM 驱动因子-模型联合进化)
- FactorEngine — arXiv:2603.16365 (LLM 引导因子挖掘)
- ODA-Fin — arXiv:2603.07223 (难度感知金融蒸馏)
- NVIDIA Data Flywheel Blueprint (生产级蒸馏, 49-70B→1-8B)
