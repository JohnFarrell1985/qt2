# P0.1: 数据采集 + 数据清洗

> 最后更新: 2026-04-12
>
> 返回总览: [TODO.md](TODO.md) | P0 已全部完成

---

### P0-12: LLMClient 统一客户端

| 属性 | 内容 |
|------|------|
| **模块** | dataclean |
| **文件** | `src/dataclean/llm_client.py` |
| **工作量** | 1 天 |

**为什么要做:**
LLMClient 在架构中承担**三个长期角色** (不仅是临时过渡):

1. **Phase 1 生产推理**: 本地模型尚未训练部署前, 用 DeepSeek API 做结构化抽取 (成本 ~¥0.5/月)
2. **Phase 2 蒸馏教师**: 用 DeepSeek/Qwen 标注大量新闻的情绪/事件, 生成训练数据蒸馏到本地 FinBERT2/Qwen3-0.6B — **这是知识蒸馏的核心, 大模型当老师**
3. **Phase 3 低置信兜底**: 本地模型处理 95% 流量后, 置信度 < 0.7 的 "难样本" 仍需 API 兜底 + 数据飞轮持续迭代

需要支持 DeepSeek 和 Qwen 两个模型的自动降级 — 主模型超时/限流时自动切换到备用模型。

**业界最佳实践 (2026):**
- 使用 `instructor` 库 (12.6k stars) 替代手写 `json.loads` — Pydantic 直接作为 `response_model`, 校验失败自动重试
- DeepSeek Prefix Caching: 静态 system prompt 缓存后输入成本降 90% ($0.28 → $0.028/M tokens)
- 分层重试: 每个 provider 内指数退避重试 (瞬态错误), 再降级到下一 provider (持久错误)
- `deepseek-reasoner` 按任务类型路由 (非降级链): 蒸馏标注/研报用 reasoner, 日常抽取用 chat
- **成本**: DeepSeek V3 约 ¥1/百万 token (输入); Qwen3-Max 约 ¥8.8/百万 token (输入) — 每日 API 调用仅 ~30 次 (Phase 1) / ~1-2 次 (Phase 2+), 月费 ¥0.5~¥53

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| **openai** SDK | >=2.0 | ✅ 2026最新 | DeepSeek/Qwen 均兼容此 SDK |
| **instructor** | >=1.14 | ✅ 2026最新 | 结构化 LLM 输出 (Pydantic + auto-retry + JSON recovery) |
| **pydantic** | >=2.6 | ✅ | Schema 定义 + `.model_json_schema()` 导出 |
| **tenacity** | >=8.0 | ✅ | 指数退避重试 (instructor 依赖, 也直接使用) |

**参考文档:**
- DeepSeek API 文档: [platform.deepseek.com/api-docs](https://platform.deepseek.com/api-docs)
- instructor 文档: [python.useinstructor.com](https://python.useinstructor.com/)
- Qwen API 文档: [dashscope.aliyuncs.com](https://dashscope.aliyuncs.com/)
- Langfuse (LLM 可观测性): 已移至 [TODO-P4.md § P4-08](TODO-P4.md)

**落地方案:**
```python
import instructor
from openai import OpenAI, RateLimitError, APITimeoutError, APIConnectionError, AuthenticationError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

class LLMClient:
    """instructor 驱动的统一客户端 — 自动降级 + 指数退避重试 + 成本追踪"""

    def __init__(self, settings):
        self.providers = {}
        if settings.deepseek_api_key:
            base = OpenAI(base_url=settings.deepseek_base_url,
                          api_key=settings.deepseek_api_key,
                          timeout=settings.llm_timeout)
            self.providers["deepseek"] = {
                "client": instructor.from_openai(base),
                "model": "deepseek-chat",
            }
            self.providers["deepseek-reasoner"] = {
                "client": instructor.from_openai(base),
                "model": "deepseek-reasoner",
            }
        if settings.qwen_api_key:
            base = OpenAI(base_url=settings.qwen_base_url,
                          api_key=settings.qwen_api_key,
                          timeout=settings.llm_timeout)
            self.providers["qwen"] = {
                "client": instructor.from_openai(base),
                "model": "qwen3-max",
            }

    def extract(self, response_model: type[BaseModel], system_prompt: str,
                user_content: str, *, use_reasoner: bool = False) -> tuple[BaseModel, dict]:
        """instructor 直接返回已校验的 Pydantic 对象 + usage_meta (含 cost_usd)"""
        order = (["deepseek-reasoner", "deepseek", "qwen"] if use_reasoner
                 else [self.primary, *(p for p in ("deepseek", "qwen") if p != self.primary)])
        for provider_name in order:
            if provider_name not in self.providers:
                continue
            try:
                return self._call_with_retry(provider_name, response_model,
                                             system_prompt, user_content)
            except AuthenticationError:
                continue   # 永久错误, 直接跳过
            except Exception:
                continue   # 重试耗尽, 降级
        raise AllProvidersFailedError("所有 LLM 均失败")
```

---

### P0-13 ~ P0-20: dataclean 模块其余组件

| # | 描述 | 文件 | 工作量 |
|---|------|------|--------|
| P0-13 | `BaseCleaner` + `CleanResult` 抽象基类 | `src/dataclean/base.py` | 0.5 天 |
| P0-14 | `SentimentExtraction` Pydantic Schema (情绪分/实体/事件类型) | `src/dataclean/schemas/sentiment.py` | 0.5 天 |
| P0-15 | `SentimentCleaner` LLM 清洗器 (instructor 版) | `src/dataclean/cleaners/sentiment_cleaner.py` | 1 天 |
| P0-16 | `PassthroughCleaner` 直通清洗器 (已结构化 list[dict]) | `src/dataclean/cleaners/passthrough_cleaner.py` | 0.5 天 |
| P0-17 | `RuleCleaner` 规则降级清洗 (关键词+正则) | `src/dataclean/cleaners/rule_cleaner.py` | 0.5 天 |
| P0-18 | 情绪清洗 Prompt 模板 (v2: few-shot + auto-schema + 负约束) | `src/dataclean/prompts/sentiment_prompt.py` | 0.5 天 |
| P0-19 | 错误层级 + 模块初始化 | `src/dataclean/exceptions.py` + `__init__.py` | 0.5 天 |
| P0-20 | `.env` 参数 + `LLMConfig` dataclass | `src/common/config.py` + `.env` | 0.5 天 |

**为什么要做:**
原始数据格式混杂 (HTML、JSON、纯文本)，需要经过清洗转换为标准 Pydantic Schema 后才能入库。三层清洗器 (LLM → 规则 → 直通) 形成降级链:
- **SentimentCleaner**: `instructor` + LLM 做精准情绪抽取 (成本 ~¥0.002/条，Pydantic 自动校验)
- **RuleCleaner**: LLM 不可用时的正则/关键词兜底 (免费，精度一般)
- **PassthroughCleaner**: 采集器返回的已结构化 `list[dict]` 直接入库

> **本地推理模型选型 (2026 Q2 结论)**: FinBERT2-Base (125M, 情绪分类) + Qwen3-0.6B (600M, 结构化抽取)。
> TinyFinBERT 已淘汰 (英文专用)。详见 [13-数据清洗与LLM.md § 模型选型](13-数据清洗与LLM.md)。
>
> **关键设计改进 (2026 Q2)**:
> - `instructor` 替代手写 `json.loads` (Pydantic 自动校验 + 重试)
> - 每个 provider 内指数退避重试, 错误分类 (瞬态/永久)
> - Prompt v2: few-shot 示例 + `model_json_schema()` 自动注入 + 负约束
> - DeepSeek Prefix Caching 优化 (静态 prompt, 输入成本降 90%)
> - `deepseek-reasoner` 按任务路由 (非降级链)
> - Langfuse 可观测性 → 已移至 [TODO-P4.md § P4-08](TODO-P4.md)

**参考文档:** 详见 [doc/13-数据清洗与LLM.md](13-数据清洗与LLM.md)

---
