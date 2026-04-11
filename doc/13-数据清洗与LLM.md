# 数据清洗与 LLM 模块 (src/dataclean/)

## 概述

数据清洗模块是采集和分析之间的**桥梁**——它负责将多种格式的原始数据 (HTML、Markdown、自然语言、JSON) 统一清洗为标准结构化 JSON，供下游各分析引擎使用。

**核心能力**: 通过 DeepSeek/Qwen 等大模型 API 的结构化输出 (JSON Mode)，实现非结构化数据的语义提取。

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
├── llm_client.py                      # 统一 LLM 客户端 (DeepSeek/Qwen, 自动降级)
├── base.py                            # BaseCleaner 抽象基类 + CleanResult
├── registry.py                        # Schema + Prompt 注册表
├── schemas/                           # 各引擎的 Pydantic 输出 Schema
│   ├── __init__.py
│   ├── sentiment.py                   # SentimentExtraction (情绪引擎)
│   ├── stock_event.py                 # StockEventExtraction (个股事件)
│   ├── sector_signal.py               # SectorSignalExtraction (行业信号)
│   ├── risk_alert.py                  # RiskAlertExtraction (风险预警)
│   └── generic.py                     # GenericExtraction (通用/自定义)
├── prompts/                           # 各引擎的 System Prompt 模板
│   ├── sentiment_prompt.py
│   ├── stock_event_prompt.py
│   ├── sector_signal_prompt.py
│   ├── risk_alert_prompt.py
│   └── generic_prompt.py
├── cleaners/                          # 清洗器实现
│   ├── __init__.py
│   ├── sentiment_cleaner.py           # 情绪清洗 (LLM)
│   ├── stock_event_cleaner.py         # 个股事件清洗 (LLM)
│   ├── rule_cleaner.py                # 纯规则清洗 (不用 LLM)
│   └── passthrough_cleaner.py         # 直通 (已结构化数据)
└── models.py                          # 清洗日志 ORM (clean_log)
```

---

## LLM 客户端 (llm_client.py)

### DeepSeek / Qwen 统一封装

DeepSeek 和 Qwen 均兼容 OpenAI Python SDK，切换只需改 `base_url` 和 `api_key`:

```python
# src/dataclean/llm_client.py

from openai import OpenAI
import json, logging

logger = logging.getLogger(__name__)

class LLMClient:
    """DeepSeek (主) / Qwen (备) 统一客户端 — 全平台共享, 自动降级"""
    
    def __init__(self, settings):
        self.providers = {}
        if settings.deepseek_api_key:
            self.providers["deepseek"] = {
                "client": OpenAI(base_url=settings.deepseek_base_url,
                                 api_key=settings.deepseek_api_key),
                "model": settings.deepseek_model,
            }
        if settings.qwen_api_key:
            self.providers["qwen"] = {
                "client": OpenAI(base_url=settings.qwen_base_url,
                                 api_key=settings.qwen_api_key),
                "model": settings.qwen_model,
            }
        self.primary = settings.llm_provider  # "deepseek"
    
    def extract_json(self, system_prompt: str, user_content: str,
                     temperature: float = 0.1) -> tuple[dict, dict]:
        """
        调用 LLM 提取 JSON, 自动降级.
        返回: (result_dict, usage_meta)
        """
        order = [self.primary] + [p for p in self.providers if p != self.primary]
        
        for provider_name in order:
            if provider_name not in self.providers:
                continue
            p = self.providers[provider_name]
            try:
                resp = p["client"].chat.completions.create(
                    model=p["model"],
                    response_format={"type": "json_object"},
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content},
                    ],
                    temperature=temperature,
                    max_tokens=2000,
                )
                usage = {
                    "provider": provider_name,
                    "model": p["model"],
                    "tokens_in": resp.usage.prompt_tokens,
                    "tokens_out": resp.usage.completion_tokens,
                }
                return json.loads(resp.choices[0].message.content), usage
            except Exception as e:
                logger.warning(f"LLM [{provider_name}] 失败: {e}")
                continue
        
        raise AllProvidersFailedError("所有 LLM 提供商均失败")
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
| **Phase 1: 主力 API** | **DeepSeek V3** | 情绪打分 + 事件抽取 + 蒸馏标注 | ¥1/百万 token | ¥2/百万 token | 支持 `json_object` |
| Phase 1: 备选 API | Qwen3.5-Plus (百炼) | DeepSeek 不可用时降级 | ¥2/百万 token | ¥12/百万 token | 支持 |
| Phase 1: 复杂任务 | DeepSeek R1 | 研报精读, 长逻辑链, 蒸馏 Judge | ¥4/百万 token | ¥16/百万 token | 支持 |
| **Phase 2-3: 本地分类** | **FinBERT2-Base 125M (ONNX)** | 中文金融情绪分类 (-1/0/+1), 95% 流量 | 0 元 | 0 元 | — (encoder) |
| Phase 2-3: 本地抽取 | Qwen3-0.6B + LoRA (GGUF) | 结构化 JSON 抽取 (事件/风险/行业) | 0 元 | 0 元 | 支持 |

**为什么 DeepSeek 是主力而非百炼 Qwen**:
- DeepSeek V3 价格仅 Qwen-Plus 的 **1/6** (输出 ¥2 vs ¥12)
- DeepSeek 在逻辑推理和低幻觉方面更强, 适合金融结构化抽取
- Qwen 的优势 (函数调用、长上下文) 在情绪分析场景中不是刚需
- 两者均兼容 OpenAI SDK, 切换零成本

**每日成本估算 (Phase 1)**:

```
每次采集: ~5000 字原始文本 ≈ 3000 tokens
每日 4 次采集 = 12000 input tokens + 3000 output tokens
DeepSeek V3 费用 = 12000/1M × ¥1 + 3000/1M × ¥2 = ¥0.018/天
每月费用 ≈ ¥0.5 (基本免费)
```

### 降级策略

```
Phase 1 (API 清洗) 的降级路径:

DeepSeek V3 (首选)
    │ 失败/超时/限流
    ▼
Qwen3.5-Plus (备选, 百炼)
    │ 失败/超时
    ▼
RuleCleaner (规则清洗 — cleaners/rule_cleaner.py)
    │ 关键词匹配: 情绪正/负/中性 + 股票代码正则
    ▼
标记 is_fallback=True, status="partial"


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
    llm_usage: dict       # {"provider", "model", "tokens_in", "tokens_out"}
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

### 情绪清洗 Prompt

```python
# src/dataclean/prompts/sentiment_prompt.py

SENTIMENT_PROMPT = """你是A股市场数据分析师。将以下市场信息提取为标准JSON。

要求:
1. news_sentiment_score: 整体新闻情绪 -1.0(极度悲观)到+1.0(极度乐观)
2. hot_sectors: 被提及最多的行业板块, 最多5个
3. key_events: 重要事件, 含 event(描述), impact(positive/negative/neutral), magnitude(high/medium/low)
4. hot_stocks: 被频繁讨论的个股, 含 code(代码), reason(原因), sentiment(-1~1)
5. market_mood_text: 一句话市场总结
6. 过滤广告、不相关内容
7. 去重: 相同事件只保留一条

输出严格遵循以下JSON Schema, 不要添加额外字段:
{
  "news_sentiment_score": number,
  "hot_sectors": [string],
  "key_events": [{"event": string, "impact": string, "magnitude": string}],
  "hot_stocks": [{"code": string, "reason": string, "sentiment": number}],
  "gold_price_usd": number | null,
  "crude_oil_usd": number | null,
  "fx_usdcny": number | null,
  "market_mood_text": string
}"""
```

### 个股事件 Prompt

```python
# src/dataclean/prompts/stock_event_prompt.py

STOCK_EVENT_PROMPT = """你是A股个股分析师。从以下信息中提取与具体个股相关的事件。

要求:
1. 只提取明确提到具体股票代码或公司名的事件
2. 判断事件对该股票的影响方向和强度
3. 区分已证实事件和市场传闻
4. code 格式: 6位数字.交易所 (如 000001.SZ, 601398.SH)

输出 JSON 数组, 每个元素:
{"code": string, "event_type": string, "impact": string, "magnitude": string,
 "summary": string, "sentiment": number, "source": string, "is_confirmed": boolean}"""
```

---

## 清洗器实现

### SentimentCleaner

```python
# src/dataclean/cleaners/sentiment_cleaner.py

from src.dataclean.base import BaseCleaner, CleanResult
from src.dataclean.schemas.sentiment import SentimentExtraction
from src.dataclean.prompts.sentiment_prompt import SENTIMENT_PROMPT

class SentimentCleaner(BaseCleaner):
    
    def get_schema(self):
        return SentimentExtraction
    
    def clean(self, raw_data) -> CleanResult:
        if isinstance(raw_data, dict) and "news_sentiment_score" in raw_data:
            validated = self._validate(raw_data)
            return CleanResult(engine="sentiment", schema_name="SentimentExtraction",
                             cleaned_data=validated.model_dump(), raw_input=str(raw_data),
                             llm_usage={}, is_fallback=False)
        
        result, usage = self.llm.extract_json(SENTIMENT_PROMPT, str(raw_data))
        validated = self._validate(result)
        return CleanResult(engine="sentiment", schema_name="SentimentExtraction",
                         cleaned_data=validated.model_dump(), raw_input=str(raw_data),
                         llm_usage=usage, is_fallback=False)
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
from src.datacollect import DataCollectRouter
from src.dataclean import LLMClient
from src.dataclean.cleaners.sentiment_cleaner import SentimentCleaner
from src.dataclean.cleaners.stock_event_cleaner import StockEventCleaner

collector = DataCollectRouter(settings)
llm = LLMClient(settings)

raw_news = "央行降准50bp, 银行股集体涨停, 北向资金净流入120亿..."

# 同一条数据 → 不同清洗器 → 不同结构化输出
sentiment = SentimentCleaner(llm).clean(raw_news)
# → 情绪: 乐观(+0.7), 热门板块=["银行","券商"]

events = StockEventCleaner(llm).clean(raw_news)
# → 个股: 601398.SH 利好(降准), impact=positive, magnitude=high

risk = RiskAlertCleaner(llm).clean(raw_news)
# → 风险: 无风险信号 (利好新闻)
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

## .env 参数

```bash
# ================================================================
# 数据清洗与 LLM 模块 (src/dataclean/)
# ================================================================

# ── LLM 提供商 ──
SENTIMENT_LLM_PROVIDER=deepseek         # 首选: deepseek / qwen
DEEPSEEK_API_KEY=                       # https://platform.deepseek.com
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-chat            # DeepSeek V3
QWEN_API_KEY=                           # https://dashscope.console.aliyun.com
QWEN_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
QWEN_MODEL=qwen-plus                    # qwen-plus (备选) / qwen-max (复杂任务)

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

# ── LLM 调用参数 ──
LLM_TEMPERATURE=0.1                     # 低温度=高确定性
LLM_MAX_RETRIES=2                       # 失败重试次数
LLM_TIMEOUT=30                          # 超时 (秒)
```

### Python 依赖

```bash
# Phase 1 (API 清洗)
openai>=1.0             # DeepSeek/Qwen API (兼容 SDK)
pydantic>=2.0           # Schema 校验 (已有)

# Phase 2-3 (本地推理, 按需安装)
transformers>=4.40      # FinBERT2-Base tokenizer + model
onnxruntime>=1.17       # FinBERT2 ONNX 推理 (CPU, 无需 GPU 版)
llama-cpp-python>=0.3   # Qwen3-0.6B GGUF 本地推理 (可选, 也可用 ollama CLI)
```

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
三层保障: ① `response_format: json_object` 强制 JSON; ② Pydantic Schema 校验; ③ 失败自动重试+降级到 RuleCleaner。

### Q: OpenClaw 端清洗 vs qt-quant 端清洗?
OpenClaw 端 (C1) 优先: 它自带 LLM，收集完直接结构化推送。qt-quant 端 (C2) 兜底: OpenClaw 未部署时自己调 DeepSeek。

### Q: 6 个引擎全部要实现吗?
不需要。P0 只做情绪引擎。其他按优先级逐步添加。三层架构保证后续扩展零重构。

### Q: 家用硬件能跑本地 NLP 吗?
**FinBERT2-Base (125M)**: ONNX INT8 量化后 ~60MB, 纯 CPU 推理 ~5ms, 无需显卡。
**Qwen3-0.6B**: GGUF Q4 量化后 ~400MB, CPU 推理 ~50ms (llama.cpp / ollama), 无需显卡。
两个模型加起来 < 500MB 内存, 任何现代笔记本电脑都能运行。Phase 1 先用 DeepSeek API (¥0.5/月), Phase 2-3 切到本地推理后成本归零。

### Q: 为什么不用百炼作为主力 LLM?
DeepSeek V3 价格仅 Qwen-Plus 的 1/6 (输出 ¥2 vs ¥12/百万 token), 且在逻辑推理和低幻觉方面更强。头部量化机构 (九坤/幻方) 均不依赖云端 API, 自建模型+蒸馏是主线。百炼 Qwen 作为备选教师和降级方案保留, 但不建议作为主力。详见"LLM 选型策略"章节。

### Q: 本地推理模型什么时候可用?
P2-19~P2-21 覆盖完整蒸馏管线 (标注 → 训练 → 评估 → 部署 → 飞轮)。FinBERT2-Base 的 Sentiment 分类可以直接用预训练权重, 零样本即可工作; Qwen3-0.6B 需要用 DeepSeek 标注数据做 LoRA 微调。在此之前, Phase 1 的 DeepSeek API 清洗方案已经满足日频策略需要, 成本极低。

### Q: 为什么淘汰 TinyFinBERT?
TinyFinBERT 是基于英文 FinBERT 的知识蒸馏版本 (14.5M), **仅支持英文**。本项目的数据源 (36kr/东方财富/新浪) 全是中文, TinyFinBERT 在中文金融语料上准确率远低于 FinBERT2-Base, 不适用。

### Q: 为什么淘汰 DeepSeek-R1-Distill-Qwen-1.5B?
该模型定位是"推理蒸馏", 擅长长链逻辑推导, 而非分类/抽取。对于复杂推理任务, 项目已有 DeepSeek R1 API; 对于本地分类/抽取, FinBERT2 + Qwen3-0.6B 更高效。1.5B 参数在 CPU 上推理 ~100ms, 性价比不如 0.6B。
