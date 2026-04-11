# 数据清洗与 LLM 模块 (src/dataclean/)

> 最后更新: 2026-04-11 | 状态: **✅ Phase 1 核心完成 (P0-12 ~ P0-20, 共 9 项)**

## 概述

数据清洗模块是采集和分析之间的**桥梁**——它负责将多种格式的原始数据 (HTML、Markdown、自然语言、JSON) 统一清洗为标准结构化 JSON，供下游各分析引擎使用。

**核心能力**: 通过 `instructor` + DeepSeek/Qwen 等大模型 API, 将非结构化数据直接抽取为 Pydantic 校验过的结构化对象, 自动重试 + 三级降级。

```
src/datacollect/  →  src/dataclean/  →  src/sentiment/
  "拿到数据"          "理解数据"         "分析数据"
                         │
                    同一条数据, 不同 Schema + Prompt
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
          情绪引擎    个股雷达    风险预警
          sentiment   stockradar  riskmonitor
```

**核心价值**: 同一条原始新闻，经过不同 Schema 和 Prompt 清洗，产出完全不同的结构化输出——情绪引擎看到"情绪乐观"，个股雷达看到"601398 利好"，风险预警看到"无风险信号"。

> 相关文档: [12-数据采集模块](12-数据采集模块.md) | [11-市场情绪引擎](11-市场情绪引擎.md)

---

## 为什么要独立出来

| 维度 | 嵌在 sentiment/ | 独立为 dataclean/ |
|------|----------------|------------------|
| 复用性 | 仅情绪引擎调用 | **所有分析引擎共享** |
| Schema 管理 | 只有 SentimentExtraction | **多套 Schema 按引擎分类** |
| Prompt 管理 | 硬编码一个 prompt | **Prompt 模板注册表** |
| LLM 客户端 | 每个引擎各写一遍 | **统一 LLM 客户端 + 降级** |
| 成本追踪 | 分散各处 | **集中统计 LLM token/费用** |

---

## 模块结构

```
src/dataclean/
├── __init__.py
├── llm_client.py                      # instructor 驱动的统一 LLM 客户端 (自动降级 + 重试)
├── exceptions.py                      # 错误层级: DatacleanError / AllProvidersFailedError / ...
├── base.py                            # BaseCleaner 抽象基类 + CleanResult
├── registry.py                        # Schema + Prompt 注册表
├── schemas/                           # 各引擎的 Pydantic 输出 Schema
│   ├── __init__.py
│   ├── sentiment.py                   # SentimentExtraction (情绪引擎)
│   ├── stock_event.py                 # StockEventExtraction (个股事件)
│   ├── sector_signal.py               # SectorSignalExtraction (行业信号)
│   ├── risk_alert.py                  # RiskAlertExtraction (风险预警)
│   └── generic.py                     # GenericExtraction (通用/自定义)
├── prompts/                           # 各引擎的 System Prompt 模板 (版本化)
│   ├── sentiment_prompt.py
│   ├── stock_event_prompt.py
│   ├── sector_signal_prompt.py
│   ├── risk_alert_prompt.py
│   └── generic_prompt.py
├── cleaners/                          # 清洗器实现
│   ├── __init__.py
│   ├── sentiment_cleaner.py           # 情绪清洗 (LLM / instructor)
│   ├── stock_event_cleaner.py         # 个股事件清洗 (LLM / instructor)
│   ├── rule_cleaner.py                # 纯规则清洗 (不用 LLM)
│   ├── passthrough_cleaner.py         # 直通 (已结构化数据)
│   └── distilled_cleaner.py           # 本地蒸馏推理 (Phase 2-3)
└── models.py                          # 清洗日志 ORM (clean_log)
```

---

## LLM 客户端 (llm_client.py)

### 基于 instructor 的结构化抽取

> **业界最佳实践 (2026)**: 不要手写 `json.loads(resp.choices[0].message.content)` —
> 使用 [`instructor`](https://python.useinstructor.com/) 库 (12.6k stars, 3M 下载/月) 获得:
> - Pydantic 模型直接作为 `response_model`, 返回已校验的对象
> - 校验失败自动重试 (将 Pydantic ValidationError 反馈给 LLM 自我修正)
> - DeepSeek / Qwen / 本地模型统一接口
> - Markdown 包裹 JSON、格式错误等自动修复

```python
# src/dataclean/llm_client.py

import instructor
from openai import OpenAI, AsyncOpenAI, RateLimitError, APITimeoutError, APIConnectionError, AuthenticationError
from pydantic import BaseModel
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import logging, time

logger = logging.getLogger(__name__)

TRANSIENT_ERRORS = (RateLimitError, APITimeoutError, APIConnectionError)
PERMANENT_ERRORS = (AuthenticationError,)

COST_PER_M_TOKENS = {
    "deepseek-chat":       {"input": 0.28,  "output": 0.42},   # USD
    "deepseek-reasoner":   {"input": 0.28,  "output": 0.42},
    "qwen3-max":           {"input": 1.22,  "output": 6.11},   # USD (按汇率折算)
}


class LLMClient:
    """DeepSeek (主) / Qwen3-Max (备) 统一客户端 — instructor 驱动, 自动降级"""

    def __init__(self, settings):
        self.settings = settings
        self.providers = {}

        if settings.deepseek_api_key:
            base = OpenAI(
                base_url=settings.deepseek_base_url,
                api_key=settings.deepseek_api_key,
                timeout=settings.llm_timeout,
            )
            self.providers["deepseek"] = {
                "client": instructor.from_openai(base),
                "model": settings.deepseek_model,            # deepseek-chat
            }
            self.providers["deepseek-reasoner"] = {
                "client": instructor.from_openai(base),
                "model": "deepseek-reasoner",                # 同价, 复杂任务
            }

        if settings.qwen_api_key:
            base = OpenAI(
                base_url=settings.qwen_base_url,
                api_key=settings.qwen_api_key,
                timeout=settings.llm_timeout,
            )
            self.providers["qwen"] = {
                "client": instructor.from_openai(base),
                "model": settings.qwen_model,                # qwen3-max
            }

        self.primary = settings.llm_provider                 # "deepseek"

    # ── 核心抽取方法 ──────────────────────────────────────

    def extract(
        self,
        response_model: type[BaseModel],
        system_prompt: str,
        user_content: str,
        *,
        use_reasoner: bool = False,
        temperature: float = 0.1,
        max_retries: int = 2,
    ) -> tuple[BaseModel, dict]:
        """
        调用 LLM 抽取结构化数据, 返回 (validated_model, usage_meta).

        - response_model: Pydantic Schema (如 SentimentExtraction)
        - use_reasoner: True 时使用 deepseek-reasoner (研报/蒸馏标注)
        - instructor 自动: Pydantic 校验失败 → 将错误反馈给 LLM → 重试

        降级链: deepseek-chat → qwen3-max → raise AllProvidersFailedError
        Reasoner: deepseek-reasoner → deepseek-chat → qwen3-max
        """
        if use_reasoner:
            order = ["deepseek-reasoner", "deepseek", "qwen"]
        else:
            order = [self.primary] + [p for p in ("deepseek", "qwen")
                                      if p != self.primary]

        last_error = None
        for provider_name in order:
            if provider_name not in self.providers:
                continue
            try:
                return self._call_with_retry(
                    provider_name, response_model, system_prompt,
                    user_content, temperature, max_retries,
                )
            except PERMANENT_ERRORS as e:
                logger.error(f"[{provider_name}] 永久错误, 跳过: {e}")
                last_error = e
                continue
            except Exception as e:
                logger.warning(f"[{provider_name}] 重试耗尽, 降级: {e}")
                last_error = e
                continue

        raise AllProvidersFailedError(f"所有 LLM 均失败: {last_error}")

    # ── 单 provider 重试 (指数退避) ──────────────────────

    def _call_with_retry(
        self, provider_name, response_model, system_prompt,
        user_content, temperature, max_retries,
    ) -> tuple[BaseModel, dict]:
        p = self.providers[provider_name]
        retries = self.settings.llm_max_retries

        @retry(
            stop=stop_after_attempt(retries),
            wait=wait_exponential(multiplier=1, min=1, max=10),
            retry=retry_if_exception_type(TRANSIENT_ERRORS),
            reraise=True,
        )
        def _do():
            t0 = time.monotonic()
            result = p["client"].chat.completions.create(
                model=p["model"],
                response_model=response_model,
                max_retries=max_retries,          # instructor 内部 Pydantic 校验重试
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_content},
                ],
                temperature=temperature,
            )
            elapsed_ms = (time.monotonic() - t0) * 1000

            raw = result._raw_response.usage
            tokens_in = raw.prompt_tokens
            tokens_out = raw.completion_tokens
            model_name = p["model"]
            rates = COST_PER_M_TOKENS.get(model_name, {"input": 0, "output": 0})

            usage = {
                "provider": provider_name,
                "model": model_name,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
                "tokens_cached": getattr(raw, "prompt_cache_hit_tokens", 0),
                "cost_usd": (tokens_in * rates["input"] + tokens_out * rates["output"]) / 1_000_000,
                "latency_ms": round(elapsed_ms),
            }
            return result, usage

        return _do()


class AllProvidersFailedError(Exception):
    """所有 LLM 提供商 (DeepSeek + Qwen) 均失败"""


class SchemaValidationError(Exception):
    """LLM 返回的 JSON 未通过 Pydantic Schema 校验"""
```

### instructor 的优势 (vs 手写 json.loads)

| 维度 | 手写 `json.loads` | `instructor` |
|------|------------------|-------------|
| 返回类型 | `dict` (无类型保障) | **Pydantic 对象** (IDE 提示, 类型安全) |
| 校验失败 | 直接抛异常, 数据丢失 | **自动将 ValidationError 反馈给 LLM, 重试修正** |
| Markdown 包裹 | 需手写 strip | **自动处理** |
| 多 provider | 需手写循环 | `from_openai()` 统一封装 |
| 代码量 | ~80 行 | **~30 行** |

### 错误分类与重试策略

```
单次调用流程:

deepseek-chat (主力)
    │
    ├─ 429 RateLimitError ──→ 指数退避重试 (1s, 2s, 4s)
    ├─ APITimeoutError ─────→ 指数退避重试
    ├─ APIConnectionError ──→ 指数退避重试
    │     └─ 重试 N 次仍失败 → 降级到下一个 provider
    │
    ├─ AuthenticationError ─→ 不重试, 直接跳过 (永久错误)
    ├─ BadRequestError ─────→ 不重试, 直接跳过
    │
    └─ Pydantic ValidationError ─→ instructor 自动重试
          (将错误信息发回 LLM: "field X failed: ...")
          └─ max_retries 次后仍失败 → 降级到下一个 provider

qwen3-max (降级)
    └─ 同样的重试逻辑
          └─ 全部失败 → RuleCleaner (rule_cleaner.py)
```

### deepseek-reasoner 任务路由 (非降级链)

`deepseek-reasoner` 不在降级链中 — 它是 V3.2 的思考模式, 由调用方按任务类型选择:

```python
# 日常情绪打分 — 用 chat (快, 直接输出)
result, usage = llm.extract(SentimentExtraction, prompt, text)

# 蒸馏标注 / 研报精读 — 用 reasoner (CoT 推理链, max_output=64K)
result, usage = llm.extract(SentimentExtraction, prompt, text, use_reasoner=True)
```

| 任务 | 选择 | 原因 |
|------|------|------|
| 情绪打分 | `deepseek-chat` | 简单分类, 不需要推理链 |
| 事件抽取 | `deepseek-chat` | schema 明确, 模式匹配型 |
| 风险预警 | `deepseek-chat` | 同上 |
| 研报精读 | `deepseek-reasoner` | 长文本, 需要多步推理 |
| 蒸馏标注 | `deepseek-reasoner` | 标注质量直接影响小模型, 值得用思考模式 |

### DeepSeek 上下文缓存 (自动, 90% 输入成本削减)

DeepSeek V3.2 **默认启用** Prefix Caching: 完全相同的 prompt 前缀在后续请求中命中缓存, 输入价格从 $0.28 → $0.028/M tokens (降 90%)。

**缓存命中条件**: 从第一个 token 开始的连续前缀必须 byte-for-byte 相同。

**最佳实践 — 消息结构**:

```
Message 1 (system) — 静态, 被缓存 ✅
  ┌────────────────────────────────────────────────┐
  │ 角色定义 + 规则 + Pydantic Schema (自动生成)    │
  │ 这部分每次调用完全相同, 触发缓存命中            │
  └────────────────────────────────────────────────┘

Message 2 (user) — 动态, 不缓存
  ┌────────────────────────────────────────────────┐
  │ 本次采集的实际新闻文本                          │
  │ 每次不同, 放在最后不破坏前缀匹配                │
  └────────────────────────────────────────────────┘
```

**禁忌**: 不要在 system prompt 中放动态内容 (时间戳、随机 ID 等), 否则破坏前缀匹配, 无法缓存。

`usage_meta` 中的 `tokens_cached` 字段可追踪每次调用的缓存命中量。

### Async 支持

调度器 (`APScheduler`) 和采集器均为 async, LLMClient 同时提供同步和异步接口:

```python
# src/dataclean/llm_client.py (异步版本)

class AsyncLLMClient(LLMClient):
    """异步版本 — 用于 APScheduler / FastAPI 协程环境"""

    def __init__(self, settings):
        super().__init__(settings)
        # 用 AsyncOpenAI 替换同步客户端
        if settings.deepseek_api_key:
            abase = AsyncOpenAI(
                base_url=settings.deepseek_base_url,
                api_key=settings.deepseek_api_key,
                timeout=settings.llm_timeout,
            )
            self.providers["deepseek"]["client"] = instructor.from_openai(abase)
            self.providers["deepseek-reasoner"]["client"] = instructor.from_openai(abase)
        if settings.qwen_api_key:
            abase = AsyncOpenAI(
                base_url=settings.qwen_base_url,
                api_key=settings.qwen_api_key,
                timeout=settings.llm_timeout,
            )
            self.providers["qwen"]["client"] = instructor.from_openai(abase)

    async def extract(self, response_model, system_prompt, user_content, **kwargs):
        """异步版 extract — 接口与同步版完全相同"""
        ...  # 同步版逻辑的 async/await 版本
```

### LLM 选型策略: 三层模型分工

> **机构实践**: 头部量化机构 (九坤/幻方/Two Sigma) 均不依赖云端 LLM API 做生产推理。
> 生产级情绪分类偏好 encoder 模型 (FinBERT/ModernBERT), 而非 decoder 模型 (Qwen-Max)。
> LLM 的定位是**标注教师**, 而非生产推理引擎。最终目标: 本地推理 95% + API 兜底 5%。

**三阶段演进路线**:

```
Phase 1 (当前)              Phase 2 (P2 阶段)           Phase 3 (P2-P3)
───────────────            ──────────────────          ──────────────────
DeepSeek API (主)          双教师标注                    全本地推理
Qwen API (备)       →      蒸馏 FinBERT2-Base   →      数据飞轮
规则清洗 (兜底)             ONNX 本地部署                API 仅兜底 5%
```

**模型选型对比 (2026 年 4 月最新价格)**:

| 层级 | 模型 | 用途 | 输入价格 | 输出价格 | JSON 模式 |
|------|------|------|---------|---------|----------|
| **Phase 1: 主力** | **`deepseek-chat`** (V3.2 非思考) | 情绪打分 + 事件抽取 + 风险预警 | $0.28/M token | $0.42/M token | 支持 `json_object` |
| Phase 1: 复杂任务 | **`deepseek-reasoner`** (V3.2 思考) | 研报精读 + 蒸馏标注 + 长逻辑链 | $0.28/M token | $0.42/M token | 支持 (同价, 有 CoT) |
| Phase 1: 降级兜底 | **Qwen3-Max** (百炼旗舰) | DeepSeek 不可用时降级 + 蒸馏教师 | ¥8.8/百万 token | ¥44/百万 token | 支持 |
| **Phase 2-3: 本地分类** | **FinBERT2-Base 125M (ONNX)** | 中文金融情绪分类 (-1/0/+1), 95% 流量 | 0 元 | 0 元 | — (encoder) |
| Phase 2-3: 本地抽取 | Qwen3-0.6B + LoRA (GGUF) | 结构化 JSON 抽取 (事件/风险/行业) | 0 元 | 0 元 | 支持 |

**为什么 DeepSeek 是主力, Qwen3-Max 作为备选**:
- DeepSeek V3 日常主力, 价格极低 (¥1+¥2/百万 token)
- **Qwen3-Max 是百炼最强旗舰**, 252K 上下文, 推理能力最强 — 用于降级兜底和蒸馏标注, 确保质量
- 每日 API 调用仅 ~30 次 (Phase 1) / ~1-2 次 (Phase 2+, 本地模型处理 95%+ 流量)
- 即使 Phase 1 全量降级到 Qwen3-Max, 月费也仅 ~¥53; Phase 2+ 降级几乎 0 费用
- 两者均兼容 OpenAI SDK, 切换零成本

**每日成本估算 (Phase 1)**:

```
每次采集: ~5000 字原始文本 ≈ 3000 tokens
每日 4 次采集 = 12000 input tokens + 3000 output tokens

DeepSeek V3 (正常):   12000/1M × ¥1 + 3000/1M × ¥2   = ¥0.018/天 ≈ ¥0.5/月
Qwen3-Max (降级时):   12000/1M × ¥8.8 + 3000/1M × ¥44 = ¥0.24/天  ≈ ¥7/月

Phase 2+ 本地推理后, API 仅兜底 ~1-2 次/天:
DeepSeek V3: ¥0.001/天 ≈ ¥0.03/月 (约等于免费)
```

### 降级策略

```
Phase 1 (API 清洗) 的降级路径:

deepseek-chat (V3.2 非思考, 首选, $0.28+$0.42/M token)
    │ 失败/超时/限流
    ▼
Qwen3-Max (百炼旗舰, 降级兜底, ¥8.8+¥44/M token)
    │ 失败/超时
    ▼
RuleCleaner (规则清洗 — cleaners/rule_cleaner.py)
    │ 关键词匹配: 情绪正/负/中性 + 股票代码正则
    ▼
标记 is_fallback=True, status="partial"

蒸馏标注 / 研报精读等复杂任务:
deepseek-reasoner (V3.2 思考模式, 同价但有 CoT 推理链, max_output=64K)


Phase 2-3 (本地推理 + API 兜底) 的降级路径:

情绪分类任务:
FinBERT2-Base 本地 ONNX (95% 流量, CPU ~5ms)
    │ 置信度 < 0.7 → 进入飞轮队列
    ▼
DeepSeek V3 API (低置信样本兜底)
    │ 失败 → RuleCleaner

结构化抽取任务 (事件/风险/行业):
Qwen3-0.6B + LoRA 本地 (CPU ~50ms)
    │ 输出校验失败 → API 兜底
    ▼
DeepSeek V3 API
    │ 失败 → RuleCleaner
```

### 本地蒸馏模型集成 (Phase 2-3)

蒸馏模型 (P2-19~P2-21) 训练完成后, 通过 `DistilledCleaner` 集成到清洗管线:

```python
# src/dataclean/cleaners/distilled_cleaner.py

class DistilledSentimentCleaner(BaseCleaner):
    """FinBERT2-Base 本地情绪分类 — Phase 2-3 的主力清洗器 (encoder, 判别式)"""

    def __init__(self):
        self.local_model = ORTModelForSequenceClassification.from_pretrained(
            settings.distill_model_path  # models/finbert2-base/onnx-int8/
        )
        self.tokenizer = AutoTokenizer.from_pretrained(settings.distill_model_path)
        self.llm_fallback = LLMClient(settings)

    def clean(self, raw_data: str) -> CleanResult:
        inputs = self.tokenizer(raw_data, return_tensors="np", truncation=True, max_length=512)
        logits = self.local_model(**inputs).logits
        probs = softmax(logits, axis=-1)
        max_prob = float(probs.max())

        if max_prob >= settings.distill_flywheel_low_conf_threshold:
            label = ["negative", "neutral", "positive"][probs.argmax()]
            score = [-0.8, 0.0, 0.8][probs.argmax()] * max_prob
            return CleanResult(
                engine="sentiment",
                schema_name="DistilledSentiment",
                cleaned_data={"news_sentiment_score": score, "label": label},
                raw_input=raw_data,
                llm_usage={"provider": "local_finbert2",
                           "model": "FinBERT2-Base",
                           "tokens_in": 0, "tokens_out": 0},
                is_fallback=False,
            )
        else:
            enqueue_flywheel(raw_data, probs)
            return self.llm_fallback_clean(raw_data)
```

**Phase 2-3 本地推理模型选型 (2026 Q2 调研结论)**:

本项目聚焦 **A 股中文金融数据**, 经全网调研后确定 "两模型分工" 方案:

| 模型 | 参数量 | 架构 | 推理速度 | 适用场景 | 中文金融支持 | 来源 |
|------|--------|------|---------|---------|------------|------|
| **FinBERT2-Base** | 125M | Encoder (RoBERTa) | ~5ms (CPU) / ~2ms (GPU) | 情绪分类 (-1/0/+1) | ✅ 原生中文金融预训练 | github.com/valuesimplex/FinBERT2 |
| **Qwen3-0.6B** | 600M | Decoder (GPT) | ~50ms (CPU) / ~15ms (GPU) | 结构化 JSON 抽取 (事件/风险/行业) | ✅ 中文原生, 可 LoRA 微调 | Qwen 官方 |

**为什么只需两个模型**:

| 淘汰模型 | 淘汰原因 |
|----------|---------|
| ~~TinyFinBERT 14.5M~~ | 英文预训练, 不支持中文; 在中文金融语料上准确率不可接受 |
| ~~DeepSeek-R1-Distill-Qwen-1.5B~~ | 定位推理而非分类/抽取, 本地推理慢且参数冗余; 复杂推理已有 DeepSeek R1 API 兜底 |
| ~~Qwen3.5-0.8B~~ | 该型号实际不存在, 正确型号为 Qwen3-0.6B |

**两模型分工 — Encoder 判别 + Decoder 生成**:

```
                      原始新闻文本
                          │
              ┌───────────┴───────────┐
              ▼                       ▼
     FinBERT2-Base (125M)      Qwen3-0.6B + LoRA (600M)
     [Encoder / 判别式]         [Decoder / 生成式]
              │                       │
     情绪三分类 (-1/0/+1)       JSON 结构化抽取
     置信度 + softmax           事件 / 风险 / 行业信号
              │                       │
     ~5ms / CPU 可部署          ~50ms / CPU 可部署
     ONNX INT8 量化             GGUF 4-bit 量化
              │                       │
     置信度 < 0.7               Schema 校验失败
         → 飞轮队列 + API 兜底      → API 兜底
```

**FinBERT2-Base 的优势 (情绪分类)**:
- 基于 **中文金融语料** (财报/公告/新闻) 继续预训练的 RoBERTa
- Encoder 架构天然适合分类任务, 延迟极低
- 可直接对接 HuggingFace `transformers` + ONNX Runtime, 零额外依赖
- ONNX INT8 量化后模型体积 ~60MB, 纯 CPU 即可生产部署

**Qwen3-0.6B 的优势 (结构化抽取)**:
- 600M 参数, 支持 32K 上下文, 能直接生成 JSON
- 中文原生训练, 金融术语覆盖好
- 支持 LoRA 微调 (用 DeepSeek 标注数据做教师), 成本低
- GGUF 4-bit 量化后 ~400MB, 家用 CPU 可运行 (llama.cpp / ollama)

> ⚠️ 网络上流传的 "Qwen3.5-Distill-8B" "FinQwen-Distill-2B" "NewsDistill-3B" "Qwen3.5-0.8B" 等型号经核实**不存在**, 不可作为选型依据。

### 硬件灵活部署 (同一代码, 多硬件适配)

本地推理模型支持从家用 CPU 到 A800 服务器的全场景部署, **代码零修改, 仅改 `.env` 配置**:

| 硬件 | FinBERT2 后端 | Qwen3 后端 | batch size | 延迟 |
|------|--------------|-----------|------------|------|
| 家用 CPU | ONNX Runtime CPU | llama-cpp CPU | 4 / 1 | ~5ms / ~50ms |
| RTX 4060 Ti | ONNX Runtime GPU | llama-cpp GPU | 32 / 4 | ~2ms / ~15ms |
| RTX 4090 | ONNX Runtime GPU | llama-cpp GPU | 64 / 8 | ~1ms / ~10ms |
| A800 / A100 80GB | ONNX Runtime GPU | **vLLM** BF16 | 256 / 32 | <1ms / ~5ms |

通过 `src/common/device_config.py` 运行时自动探测 GPU 型号, 自动选择最优 profile (precision / batch size / backend)。
也可通过 `DEVICE_PROFILE=a800` 手动指定。详见 [15-硬件配置指南 § 九](15-硬件配置指南.md)。

---

## 错误层级 (exceptions.py)

```python
# src/dataclean/exceptions.py

class DatacleanError(Exception):
    """dataclean 模块所有错误的基类"""

class AllProvidersFailedError(DatacleanError):
    """所有 LLM 提供商 (DeepSeek + Qwen) 重试耗尽后均失败"""

class SchemaValidationError(DatacleanError):
    """LLM 返回的 JSON 未通过 Pydantic Schema 校验 (instructor 重试后仍失败)"""

class LLMTimeoutError(DatacleanError):
    """LLM 调用超时 (超过 LLM_TIMEOUT 秒)"""
```

上游调用方统一 `except DatacleanError` 即可捕获所有清洗错误, 也可按子类精细处理:

```python
from src.dataclean.exceptions import DatacleanError, AllProvidersFailedError

try:
    result = sentiment_cleaner.clean(raw_news)
except AllProvidersFailedError:
    result = rule_cleaner.clean(raw_news)   # 最终降级到规则
except DatacleanError as e:
    logger.error(f"清洗异常: {e}")
```

---

## 清洗器基类 (base.py)

```python
# src/dataclean/base.py

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pydantic import BaseModel
from typing import Any

@dataclass
class CleanResult:
    """清洗结果标准格式"""
    engine: str           # "sentiment" / "stock_event" / "sector_signal"
    schema_name: str      # "SentimentExtraction" / "StockEventExtraction"
    cleaned_data: dict    # 校验通过的结构化数据
    raw_input: str        # 原始输入文本
    llm_usage: dict       # {"provider", "model", "tokens_in/out", "tokens_cached", "cost_usd", "latency_ms"}
    is_fallback: bool     # 是否用了降级方案

class BaseCleaner(ABC):
    """所有清洗器的基类"""
    
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client
    
    @abstractmethod
    def clean(self, raw_data: Any) -> CleanResult:
        """将原始数据清洗为结构化输出"""
        ...
    
    @abstractmethod
    def get_schema(self) -> type[BaseModel]:
        """返回该清洗器的 Pydantic Schema"""
        ...
    
    def _validate(self, data: dict) -> BaseModel:
        """Pydantic 双重校验"""
        schema = self.get_schema()
        return schema(**data)
```

---

## Schema 定义

### SentimentExtraction (情绪引擎)

```python
# src/dataclean/schemas/sentiment.py

from pydantic import BaseModel, Field
from typing import List, Optional

class KeyEvent(BaseModel):
    event: str = Field(description="事件描述")
    impact: str = Field(description="positive/negative/neutral")
    magnitude: str = Field(description="high/medium/low")

class HotStock(BaseModel):
    code: str = Field(description="股票代码, QMT格式如000001.SZ")
    reason: str = Field(description="被关注的原因")
    sentiment: float = Field(ge=-1, le=1, description="情绪评分")

class SentimentExtraction(BaseModel):
    news_sentiment_score: float = Field(ge=-1, le=1)
    hot_sectors: List[str] = Field(max_length=5)
    key_events: List[KeyEvent] = Field(max_length=10)
    hot_stocks: List[HotStock] = Field(max_length=10)
    gold_price_usd: Optional[float] = None
    crude_oil_usd: Optional[float] = None
    fx_usdcny: Optional[float] = None
    market_mood_text: str = Field(max_length=100)
```

### StockEventExtraction (个股雷达)

```python
# src/dataclean/schemas/stock_event.py

class StockEventExtraction(BaseModel):
    code: str                    # "000001.SZ"
    event_type: str              # "earnings_warn" / "insider_buy" / "rumor"
    impact: str                  # "positive" / "negative" / "neutral"
    magnitude: str               # "high" / "medium" / "low"
    summary: str
    sentiment: float             # -1 ~ +1
    source: str                  # "cls" / "xueqiu" / "eastmoney"
    is_confirmed: bool
```

### FundFlowExtraction (资金流向)

```python
# src/dataclean/schemas/fund_flow.py

class FundFlowExtraction(BaseModel):
    trade_date: str
    north_net_flow: float
    north_top_buys: list[dict]
    north_top_sells: list[dict]
    margin_balance: float
    margin_buy: float
    big_order_net: float
    sector_inflow_top: list[dict]
```

### RiskAlertExtraction (风险预警)

```python
# src/dataclean/schemas/risk_alert.py

class RiskAlertExtraction(BaseModel):
    alert_level: str              # "critical" / "warning" / "info"
    alert_type: str               # "black_swan" / "policy_shock" / "flash_crash"
    description: str
    affected_sectors: list[str]
    affected_stocks: list[str]
    recommended_action: str       # "reduce_position" / "stop_trading" / "monitor"
    urgency_hours: int
```

### SectorSignalExtraction (行业轮动)

```python
# src/dataclean/schemas/sector_signal.py

class SectorSignalExtraction(BaseModel):
    sector: str
    phase: str                    # "leading" / "rising" / "weakening" / "bottom"
    momentum_score: float
    policy_catalyst: str
    rotation_signal: str          # "enter" / "hold" / "exit"
    related_etfs: list[str]
```

### MacroIndicatorExtraction (宏观经济)

```python
# src/dataclean/schemas/macro_indicator.py

class MacroIndicatorExtraction(BaseModel):
    indicator: str                # "PMI" / "CPI" / "M2"
    value: float
    previous: float
    consensus: float
    surprise: float
    trend: str                    # "improving" / "stable" / "deteriorating"
    impact_on_market: str
```

---

## Prompt 模板

### Prompt 工程最佳实践

> **2026 业界共识**: Prompt 质量直接决定 LLM 抽取质量。以下原则经头部量化团队验证:

| 原则 | 做法 | 收益 |
|------|------|------|
| **Schema 自动注入** | 用 `Model.model_json_schema()` 生成, 不手写 | 避免 prompt 与 Pydantic 定义不一致 |
| **Few-shot 示例** | 1-2 个典型输入/输出对 | 大幅提升边界 case 质量 (混合情绪、多事件) |
| **负约束** | 明确 "不要做什么" | 减少幻觉 (编造股票代码、混入广告) |
| **静态前缀** | system prompt 100% 静态, 无时间戳/随机 ID | 触发 DeepSeek 缓存, 降 90% 输入成本 |
| **版本标签** | 每个 prompt 带 `PROMPT_VERSION` | 可追溯, 配合 Langfuse A/B 测试 |

### 情绪清洗 Prompt (v2 — few-shot + auto-schema)

```python
# src/dataclean/prompts/sentiment_prompt.py

from src.dataclean.schemas.sentiment import SentimentExtraction

PROMPT_VERSION = "sentiment-v2"

# Schema 由 Pydantic 自动生成, 确保 prompt 与代码永远一致
_SCHEMA_JSON = SentimentExtraction.model_json_schema()

SENTIMENT_PROMPT = f"""你是A股市场数据分析师。将以下市场信息提取为标准JSON。

## 规则
1. news_sentiment_score: 整体新闻情绪 -1.0(极度悲观)到+1.0(极度乐观)
2. hot_sectors: 被提及最多的行业板块, 最多5个
3. key_events: 重要事件, 含 event(描述), impact(positive/negative/neutral), magnitude(high/medium/low)
4. hot_stocks: 被频繁讨论的个股, 含 code(QMT格式如000001.SZ), reason(原因), sentiment(-1~1)
5. market_mood_text: 一句话市场总结, 最多100字
6. 过滤广告、营销推广、不相关内容
7. 去重: 相同事件只保留一条

## 禁止
- 不要编造不存在的股票代码
- 不要包含广告或营销推广内容
- 不要在 hot_stocks 中包含未在原文中提及的股票
- 不要输出 JSON 以外的任何文本

## JSON Schema
{_SCHEMA_JSON}

## 示例

输入: "央行降准50bp, 银行股集体涨停, 北向资金净流入120亿, 贵州茅台跌2%受白酒板块拖累"

输出:
{{
  "news_sentiment_score": 0.5,
  "hot_sectors": ["银行", "券商", "白酒"],
  "key_events": [
    {{"event": "央行降准50bp", "impact": "positive", "magnitude": "high"}},
    {{"event": "北向资金净流入120亿", "impact": "positive", "magnitude": "medium"}},
    {{"event": "白酒板块整体下跌", "impact": "negative", "magnitude": "low"}}
  ],
  "hot_stocks": [
    {{"code": "600519.SH", "reason": "白酒板块拖累下跌2%", "sentiment": -0.3}}
  ],
  "gold_price_usd": null,
  "crude_oil_usd": null,
  "fx_usdcny": null,
  "market_mood_text": "央行降准提振银行股, 整体偏乐观但白酒板块承压"
}}"""
```

**关键改进 vs v1**:

| 改进 | v1 | v2 |
|------|-----|-----|
| Schema 来源 | 手写 JSON (容易与 Pydantic 不一致) | `model_json_schema()` 自动生成 |
| Few-shot | 无 | 1 个混合情绪示例 (覆盖正+负共存场景) |
| 负约束 | 仅 "过滤广告" | 4 条明确 "不要做什么" |
| 版本标签 | 无 | `PROMPT_VERSION = "sentiment-v2"` |
| 缓存友好 | 部分 | 100% 静态 (无动态内容, 触发 DeepSeek 缓存) |

### 个股事件 Prompt (v2 — few-shot + 负约束)

```python
# src/dataclean/prompts/stock_event_prompt.py

from src.dataclean.schemas.stock_event import StockEventExtraction

PROMPT_VERSION = "stock_event-v2"

_SCHEMA_JSON = StockEventExtraction.model_json_schema()

STOCK_EVENT_PROMPT = f"""你是A股个股分析师。从以下信息中提取与具体个股相关的事件。

## 规则
1. 只提取明确提到具体股票代码或公司名的事件
2. 判断事件对该股票的影响方向和强度
3. 区分已证实事件和市场传闻
4. code 格式: 6位数字.交易所 (如 000001.SZ, 601398.SH, 00700.HK)

## 禁止
- 不要编造原文未提及的股票代码或公司名
- 不要将行业/板块级别的事件归因到具体个股 (除非原文明确提及该个股)
- 不要将广告、软文中的公司名作为事件提取
- 如果原文中无任何个股相关事件, 返回空数组 []

## JSON Schema
{_SCHEMA_JSON}

## 示例

输入: "贵州茅台发布2025年报, 净利润同比增长15%, 超市场预期。另有传闻称比亚迪将收购某芯片公司, 未经证实。"

输出:
[
  {{"code": "600519.SH", "event_type": "earnings", "impact": "positive", "magnitude": "high",
   "summary": "2025年报净利润同比增长15%, 超市场预期", "sentiment": 0.7, "source": "公告", "is_confirmed": true}},
  {{"code": "002594.SZ", "event_type": "rumor", "impact": "positive", "magnitude": "medium",
   "summary": "传闻将收购某芯片公司", "sentiment": 0.3, "source": "传闻", "is_confirmed": false}}
]"""
```

### Prompt 缓存优化 (DeepSeek Context Caching)

所有 prompt 模板设计为 **100% 静态** — 不包含任何动态内容 (时间戳、用户 ID、随机种子等)。这确保 DeepSeek 的 Prefix Caching 机制每次都能命中:

```
调用方式 (instructor 内部):

messages = [
    {"role": "system", "content": SENTIMENT_PROMPT},     # ← 静态, 被缓存
    {"role": "user",   "content": raw_news_text},         # ← 动态, 每次不同
]

首次调用: 缓存 MISS → $0.28/M input tokens
后续调用: 缓存 HIT  → $0.028/M input tokens (降 90%)
```

**实现约束**:
- prompt 字符串在进程生命周期内不可变 (f-string 在 import 时求值)
- 行尾统一 `\n` (不要 `\r\n`)
- 不要在 prompt 中插入 `datetime.now()` 或 `uuid4()`

### Prompt 版本管理

每个 prompt 文件导出 `PROMPT_VERSION` 常量, 格式为 `{engine}-v{N}`:

```python
PROMPT_VERSION = "sentiment-v2"    # sentiment_prompt.py
PROMPT_VERSION = "stock_event-v2"  # stock_event_prompt.py
```

`LLMClient.extract()` 将 `PROMPT_VERSION` 附加到 `usage_meta`, 供 Langfuse 追踪和 A/B 测试:

```python
usage = {
    "provider": "deepseek",
    "model": "deepseek-chat",
    "prompt_version": "sentiment-v2",   # ← 可按版本分析质量
    "tokens_in": 1200,
    ...
}
```

---

## 清洗器实现

### SentimentCleaner (instructor 版)

```python
# src/dataclean/cleaners/sentiment_cleaner.py

from src.dataclean.base import BaseCleaner, CleanResult
from src.dataclean.schemas.sentiment import SentimentExtraction
from src.dataclean.prompts.sentiment_prompt import SENTIMENT_PROMPT
from src.dataclean.exceptions import AllProvidersFailedError

class SentimentCleaner(BaseCleaner):

    def get_schema(self):
        return SentimentExtraction

    def clean(self, raw_data) -> CleanResult:
        if isinstance(raw_data, dict) and "news_sentiment_score" in raw_data:
            validated = self._validate(raw_data)
            return CleanResult(engine="sentiment", schema_name="SentimentExtraction",
                             cleaned_data=validated.model_dump(), raw_input=str(raw_data),
                             llm_usage={}, is_fallback=False)

        try:
            # instructor 直接返回 SentimentExtraction 对象 (已校验)
            result, usage = self.llm.extract(
                response_model=SentimentExtraction,
                system_prompt=SENTIMENT_PROMPT,
                user_content=str(raw_data),
            )
            return CleanResult(engine="sentiment", schema_name="SentimentExtraction",
                             cleaned_data=result.model_dump(), raw_input=str(raw_data),
                             llm_usage=usage, is_fallback=False)
        except AllProvidersFailedError:
            return self._rule_fallback(raw_data)
```

### PassthroughCleaner (已结构化数据直通)

```python
# src/dataclean/cleaners/passthrough_cleaner.py

class PassthroughCleaner(BaseCleaner):
    """已结构化数据 (akshare DataFrame) 直接映射, 不调 LLM"""
    
    def get_schema(self):
        return None
    
    def clean(self, raw_data) -> CleanResult:
        if isinstance(raw_data, pd.DataFrame):
            data = raw_data.to_dict(orient="records")
        elif isinstance(raw_data, dict):
            data = raw_data
        else:
            data = {"raw": str(raw_data)}
        
        return CleanResult(
            engine="passthrough", schema_name="raw",
            cleaned_data=data, raw_input=str(raw_data)[:500],
            llm_usage={}, is_fallback=False,
        )
```

### RuleCleaner (降级方案, 不用 LLM)

```python
# src/dataclean/cleaners/rule_cleaner.py

import re

class RuleCleaner(BaseCleaner):
    """纯规则清洗 — LLM 全部失败时的最后防线"""
    
    POSITIVE_KEYWORDS = ["涨停", "利好", "上涨", "突破", "降准", "放量"]
    NEGATIVE_KEYWORDS = ["跌停", "利空", "下跌", "暴跌", "加息", "制裁"]
    STOCK_CODE_PATTERN = re.compile(r'[036]\d{5}\.[SZ]{2}')
    
    def get_schema(self):
        return None
    
    def clean(self, raw_data) -> CleanResult:
        text = str(raw_data)
        
        pos = sum(1 for kw in self.POSITIVE_KEYWORDS if kw in text)
        neg = sum(1 for kw in self.NEGATIVE_KEYWORDS if kw in text)
        score = (pos - neg) / max(pos + neg, 1)
        
        codes = self.STOCK_CODE_PATTERN.findall(text)
        
        return CleanResult(
            engine="rule_fallback",
            schema_name="partial",
            cleaned_data={
                "news_sentiment_score": round(score, 2),
                "hot_stocks": [{"code": c, "reason": "关键词匹配", "sentiment": score} for c in codes[:5]],
                "market_mood_text": "规则提取(LLM不可用)",
            },
            raw_input=text[:500],
            llm_usage={},
            is_fallback=True,
        )
```

---

## 一份数据, 多引擎清洗

```python
from src.dataclean.llm_client import LLMClient
from src.dataclean.cleaners.sentiment_cleaner import SentimentCleaner
from src.dataclean.cleaners.stock_event_cleaner import StockEventCleaner

llm = LLMClient(settings)

raw_news = "央行降准50bp, 银行股集体涨停, 北向资金净流入120亿..."

# 同一条数据 → 不同清洗器 → 不同 Pydantic 模型输出 (instructor 自动校验)
sentiment = SentimentCleaner(llm).clean(raw_news)
# → SentimentExtraction(news_sentiment_score=0.7, hot_sectors=["银行","券商"], ...)

events = StockEventCleaner(llm).clean(raw_news)
# → StockEventExtraction(code="601398.SH", event_type="policy", impact="positive", ...)

risk = RiskAlertCleaner(llm).clean(raw_news)
# → RiskAlertExtraction(risk_level="none", ...)
```

---

## 数据采集 → 数据清洗 对接规范

### 采集模块落盘格式

数据采集模块 (`src/datacollect/`) 通过 `CollectResult` 统一返回, `data` 字段为 `list[dict]`。落盘到 PostgreSQL 后形成以下表结构:

| DB 表 | 采集器来源 | 关键字段 | dataclean 消费方式 |
|--------|-----------|---------|-------------------|
| `global_market_snapshot` | yfinance / sina_global | `symbol`, `close_price`, `change_pct`, `trade_date`, `raw_data`, `source` | **PassthroughCleaner** — 结构化数值, 直接映射 |
| `watchlist_intel` | WatchlistIntelCollector (akshare) | `code`, `intel_type`, `title`, `content`, `source`, `url`, `published_at` | **SentimentCleaner / StockEventCleaner** — `title + content` 拼接后送 LLM |
| `collect_log` | 所有采集器 | `task_id`, `source`, `status`, `records_count`, `elapsed_ms` | 不参与清洗, 仅运维 |

### RSS 新闻 → 清洗器映射

RSS 采集器 (`NewsRssCollector`) 返回的 `list[dict]` 字段为:

```
title, summary, link, source, source_key, published_at (datetime | None)
```

与 `WatchlistIntel` 表字段名不完全一致, 对接时需要字段映射:

| RSS 字段 | WatchlistIntel 字段 | 清洗器入参 |
|----------|-------------------|-----------|
| `title` | `title` | 直接使用 |
| `summary` | `content` | 映射 |
| `link` | `url` | 映射 |
| `source` | `source` | 直接使用 |
| `published_at` (datetime) | `published_at` (str) | **需统一为 datetime** |

### 全球行情 → 清洗器映射

yfinance / sina_global 返回结构一致:

```python
{"symbol": "SPX", "close_price": 5200.0, "change_pct": 0.35, "trade_date": date, "raw": {...}}
```

落盘到 `global_market_snapshot` 后, `SentimentBridge` 直接从 DB 读取计算全局情绪字段 (`fx_usdcny`, `gold_price_usd` 等), 不经过 LLM 清洗。

### 数据流全景

```
[采集层 datacollect]                    [清洗层 dataclean]                 [分析层]
─────────────────                      ─────────────────                 ──────────
NewsRssCollector                                                        sentiment/
  → list[dict]  ─── 落盘 ──→ watchlist_intel ─── title+content ──→ SentimentCleaner
  (title,summary,link)                           (中文新闻)          StockEventCleaner
                                                                    RiskAlertCleaner

WatchlistIntelCollector                                             stockradar/
  → list[dict]  ─── 落盘 ──→ watchlist_intel ─── title+content ──→ StockEventCleaner
  (title,content,url)                            (个股情报)

YfinanceCollector                                                   sentiment/
SinaGlobalCollector    ─── 落盘 ──→ global_market_snapshot ────────→ SentimentBridge
  → list[dict]                      (symbol,close,change_pct)       (直接数值计算)
  (symbol,close_price)

EastmoneyCollector                                                  fundflow/
TushareCollector       ─── 落盘 ──→ 对应业务表 ──→ PassthroughCleaner / FundFlowCleaner
AdataCollector                      (结构化数据)
```

### 已知对接差异 & 解决方案

| # | 差异 | 影响 | 解决方案 |
|---|------|------|---------|
| 1 | RSS `published_at` 为 `datetime`, WatchlistIntel 为 `str` | 时间过滤逻辑不一致 | **Phase 1 实现**: 入库前统一转 `datetime`, 字段类型改为 `TIMESTAMP` |
| 2 | RSS 的 `summary` 对应 WatchlistIntel 的 `content` | 字段名不一致 | **映射层**: `NewsRssCollector.collect()` 或入库函数中做 rename |
| 3 | WatchlistIntelCollector `metadata` 缺 `task_id`/`elapsed_ms` | 日志追踪不完整 | **增强**: 补齐 `metadata` 字段 |
| 4 | yfinance `raw` 为 OHLCV dict, sina_global `raw` 为 `parts` list | `raw_data` 结构不统一 | **不影响清洗**: `raw_data` 仅存档, 清洗器不依赖此字段 |
| 5 | `base.py` 文档写 "data 通常为 DataFrame" 但实际为 `list[dict]` | 文档误导 | **已确认**: 所有采集器均返回 `list[dict]`, 文档需同步更新 |

---

## 可扩展的分析引擎

| # | 引擎 | 分析内容 | Schema | 对策略的价值 | 优先级 |
|---|------|---------|--------|------------|--------|
| 1 | **sentiment** 情绪引擎 | 整体市场情绪 | SentimentExtraction | 决定策略和参数 | P0 已设计 |
| 2 | **stockradar** 个股雷达 | 个股舆情/事件 | StockEventExtraction | 过滤利空+增强利好 | P1 |
| 3 | **fundflow** 资金流向 | 北向/融资/大单 | FundFlowExtraction | 跟随聪明钱 | P1 |
| 4 | **riskmonitor** 风险预警 | 黑天鹅/突发 | RiskAlertExtraction | 紧急止损 | P1 |
| 5 | **sectorwatch** 行业轮动 | 板块强弱 | SectorSignalExtraction | 行业配置 | P2 |
| 6 | **macrotrack** 宏观经济 | GDP/CPI/PMI | MacroIndicatorExtraction | 长期趋势 | P2 |

新增引擎只需: ① `schemas/` 加 Pydantic Schema; ② `prompts/` 加 System Prompt; ③ `cleaners/` 加清洗器。datacollect 和 dataclean 核心代码**不动**。

---

## 成本追踪与 LLM 可观测性

### 内置成本计算

每次 `LLMClient.extract()` 调用自动计算费用并写入 `usage_meta`:

```python
COST_PER_M_TOKENS = {
    "deepseek-chat":       {"input": 0.28,  "output": 0.42},   # USD/M tokens
    "deepseek-reasoner":   {"input": 0.28,  "output": 0.42},
    "qwen3-max":           {"input": 1.22,  "output": 6.11},   # USD (按汇率折算)
}

# usage_meta 示例:
{
    "provider": "deepseek",
    "model": "deepseek-chat",
    "prompt_version": "sentiment-v2",
    "tokens_in": 1200,
    "tokens_out": 300,
    "tokens_cached": 800,           # DeepSeek Prefix Caching 命中
    "cost_usd": 0.000462,           # (1200 * 0.28 + 300 * 0.42) / 1M
    "latency_ms": 1850,
}
```

成本数据随 `CleanResult` 一起写入 `clean_log` 表, 可按天/周/月聚合分析。

### Langfuse LLM 可观测性 (→ P4)

> Langfuse (开源 LLM 可观测性) 已移至 [TODO-P4.md § P4-08](TODO-P4.md) 与全栈可观测性一起实施。
> Phase 1 使用 `clean_log` 表 + 内置 `cost_usd` 字段即可满足成本追踪需求。

---

## .env 参数

```bash
# ================================================================
# 数据清洗与 LLM 模块 (src/dataclean/)
# ================================================================

# ── LLM 提供商 (模块无关, 所有引擎共享) ──
LLM_PROVIDER=deepseek                  # 首选: deepseek / qwen
DEEPSEEK_API_KEY=                       # https://platform.deepseek.com
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat            # V3.2 非思考模式 (日常结构化抽取)
# 复杂任务自动切换 deepseek-reasoner (V3.2 思考模式, 同价, 研报/蒸馏标注)
QWEN_API_KEY=                           # https://dashscope.console.aliyun.com
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen3-max                    # 百炼旗舰 (备选+蒸馏教师, 调用极少质量最高)

# ── LLM 调用参数 ──
LLM_TEMPERATURE=0.1                     # 低温度=高确定性
LLM_MAX_RETRIES=2                       # 每个 provider 重试次数 (指数退避)
LLM_TIMEOUT=30                          # API 超时 (秒), 传入 OpenAI() 构造函数

# ── 本地推理模型 (Phase 2-3) ──
DISTILL_ENABLED=false                   # Phase 2 启用后改为 true
DISTILL_FLYWHEEL_LOW_CONF_THRESHOLD=0.7 # 低于此置信度 → 飞轮队列 + API 兜底
# 情绪分类 (FinBERT2-Base, encoder, ONNX)
FINBERT2_MODEL_PATH=models/finbert2-base/onnx-int8/
# 结构化抽取 (Qwen3-0.6B, decoder, GGUF/vLLM)
QWEN3_LOCAL_MODEL_PATH=models/qwen3-0.6b/gguf-q4/
QWEN3_LOCAL_CONTEXT_LENGTH=4096         # 本地推理上下文长度

# ── 硬件适配 (详见 15-硬件配置指南.md § 九) ──
# 留空则自动探测 GPU; 可选: cpu / rtx4060ti / rtx4090 / a10 / a800 / a100
DEVICE_PROFILE=
# QWEN3_BACKEND=vllm              # 手动覆盖推理后端 (仅 A800/A100)
# QWEN3_GPU_MEM_UTIL=0.3          # vLLM 显存占用比例

# ── Langfuse 可观测性 → 详见 TODO-P4.md § P4-08 ──
# LANGFUSE_ENABLED=false              # Phase 2 与全栈可观测性一起启用
```

### Python 依赖

```bash
# Phase 1 (API 清洗)
openai>=1.0             # DeepSeek/Qwen API (兼容 SDK)
instructor>=1.14        # 结构化 LLM 输出 (Pydantic + auto-retry + JSON recovery)
pydantic>=2.0           # Schema 校验 (已有)
tenacity>=8.0           # 指数退避重试 (instructor 依赖, 也直接使用)

# Phase 2-3 (本地推理, 按需安装)
transformers>=4.40      # FinBERT2-Base tokenizer + model
onnxruntime>=1.17       # FinBERT2 ONNX 推理 (CPU, 无需 GPU 版)
llama-cpp-python>=0.3   # Qwen3-0.6B GGUF 本地推理 (可选, 也可用 ollama CLI)
```

---

## 实现完成总览 (P0-12 ~ P0-20, 全部 ✅)

> 原 TODO-P02.md 任务清单, 已全部完成并合并至本文档。

| # | 描述 | 文件 | 状态 |
|---|------|------|------|
| P0-12 | LLMClient 统一客户端 (instructor + 自动降级 + 指数退避 + 成本追踪) | `src/dataclean/llm_client.py` | ✅ |
| P0-13 | BaseCleaner + CleanResult 抽象基类 | `src/dataclean/base.py` | ✅ |
| P0-14 | SentimentExtraction Pydantic Schema (情绪分/实体/事件) | `src/dataclean/schemas/sentiment.py` | ✅ |
| P0-15 | SentimentCleaner LLM 清洗器 (instructor 版) | `src/dataclean/cleaners/sentiment_cleaner.py` | ✅ |
| P0-16 | PassthroughCleaner 直通清洗器 | `src/dataclean/cleaners/passthrough_cleaner.py` | ✅ |
| P0-17 | RuleCleaner 规则降级清洗 (关键词+正则) | `src/dataclean/cleaners/rule_cleaner.py` | ✅ |
| P0-18 | 情绪清洗 Prompt v2 (few-shot + auto-schema + 负约束) | `src/dataclean/prompts/sentiment_prompt.py` | ✅ |
| P0-19 | 错误层级 + 模块初始化 | `src/dataclean/exceptions.py` + `__init__.py` | ✅ |
| P0-20 | DatacleanConfig + .env LLM 参数 | `src/common/config.py` + `env/.env.datacollect` | ✅ |

**测试覆盖**: 98 个单元测试 + 13 个 E2E 测试, 单元测试覆盖率 100%。

**新增依赖**: `openai>=1.0`, `instructor>=1.7.0` (已声明在 pyproject.toml)。

**后续扩展 (P1)**: StockEvent Schema + Cleaner (P1-12), RiskAlert Schema (P1-13), Schema+Prompt 注册表 (P1-14), 清洗日志 ORM (P1-15)。

---

## 常见问题

### Q: dataclean 和 sentiment 的边界在哪里?
`dataclean` 负责 "将原始数据转为结构化 JSON" (LLM 调用、Schema 校验、降级)。`sentiment` 负责 "用结构化数据做分析" (特征工程、合成指数、宏观分类)。

### Q: 新增一个分析引擎需要改几个地方?
三步: ① `schemas/` 加 Pydantic Schema; ② `prompts/` 加 System Prompt; ③ 新建 `src/新引擎/`。dataclean 核心代码不动。

### Q: LLM 清洗会不会太慢?
DeepSeek V3 处理 5000 字约 1-3 秒。每日 4 次采集，总 LLM 调用时间 < 15 秒。日频策略完全足够。

### Q: LLM 清洗会不会太贵?
DeepSeek V3 每日 4 次采集约 ¥0.018/天，**每月约 ¥0.5**。Phase 2-3 蒸馏模型本地推理成本降至 0。通过 clean_log 表可精确追踪。

### Q: LLM 返回的 JSON 格式不对怎么办?
四层保障: ① `instructor` 自动将 Pydantic Schema 注入 prompt; ② `response_format: json_object` 强制 JSON; ③ Pydantic 校验失败时 `instructor` 自动将 ValidationError 反馈给 LLM 重试; ④ 所有 provider 失败后降级到 RuleCleaner。Markdown 包裹 JSON、格式错误等由 `instructor` 自动修复。

### Q: 为什么用 instructor 而不是手写 json.loads?
`instructor` (12.6k stars) 是 OpenAI SDK 的轻量包装 (~200 行), 提供: Pydantic 直接作为 `response_model` → 返回已校验对象; 校验失败自动重试 (将错误反馈给 LLM 自我修正); 兼容 DeepSeek / Qwen / 本地模型。消除 ~40% LLMClient 样板代码, 获得生产级校验+重试能力。

### Q: OpenClaw 端清洗 vs qt-quant 端清洗?
OpenClaw 端 (C1) 优先: 它自带 LLM，收集完直接结构化推送。qt-quant 端 (C2) 兜底: OpenClaw 未部署时自己调 DeepSeek。

### Q: 6 个引擎全部要实现吗?
不需要。P0 只做情绪引擎。其他按优先级逐步添加。三层架构保证后续扩展零重构。

### Q: 家用硬件能跑本地 NLP 吗?
**FinBERT2-Base (125M)**: ONNX INT8 量化后 ~60MB, 纯 CPU 推理 ~5ms, 无需显卡。
**Qwen3-0.6B**: GGUF Q4 量化后 ~400MB, CPU 推理 ~50ms (llama.cpp / ollama), 无需显卡。
两个模型加起来 < 500MB 内存, 任何现代笔记本电脑都能运行。Phase 1 先用 DeepSeek API (¥0.5/月), Phase 2-3 切到本地推理后成本归零。

### Q: 为什么不用 Qwen3-Max 作为主力 LLM?
DeepSeek V3 日常主力, 价格极低 (¥1+¥2/M token)。Qwen3-Max 作为**备选教师 + 降级兜底**, 调用极少但质量最高 (252K 上下文, 百炼最强旗舰)。Phase 1 全量降级月费 ~¥53; Phase 2+ 本地模型处理 95%+ 流量后, API 几乎 0 费用。头部量化机构 (九坤/幻方) 均不依赖云端 API, 自建模型+蒸馏是主线。

### Q: LLM API 每天调用多少次?
Phase 1 (纯 API): ~30 次/天 — 仅文本类数据 (新闻/公告) 需要 LLM, 结构化数值 (行情/资金) 直通入库不调 LLM。
Phase 2+ (本地推理): ~1-2 次/天 — FinBERT2/Qwen3-0.6B 处理 95%+ 流量, 仅低置信样本调 API 兜底。
Phase 3 (飞轮成熟): 每周几次 — API 几乎仅用于新类型样本和蒸馏标注。

### Q: 本地推理模型什么时候可用?
P2-19~P2-21 覆盖完整蒸馏管线 (标注 → 训练 → 评估 → 部署 → 飞轮)。FinBERT2-Base 的 Sentiment 分类可以直接用预训练权重, 零样本即可工作; Qwen3-0.6B 需要用 DeepSeek 标注数据做 LoRA 微调。在此之前, Phase 1 的 DeepSeek API 清洗方案已经满足日频策略需要, 成本极低。

### Q: 为什么淘汰 TinyFinBERT?
TinyFinBERT 是基于英文 FinBERT 的知识蒸馏版本 (14.5M), **仅支持英文**。本项目的数据源 (36kr/东方财富/新浪) 全是中文, TinyFinBERT 在中文金融语料上准确率远低于 FinBERT2-Base, 不适用。

### Q: 为什么淘汰 DeepSeek-R1-Distill-Qwen-1.5B?
该模型定位是"推理蒸馏", 擅长长链逻辑推导, 而非分类/抽取。对于复杂推理任务, 项目已有 DeepSeek R1 API; 对于本地分类/抽取, FinBERT2 + Qwen3-0.6B 更高效。1.5B 参数在 CPU 上推理 ~100ms, 性价比不如 0.6B。
