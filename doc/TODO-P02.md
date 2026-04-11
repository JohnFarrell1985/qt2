# P0.1: 数据采集 + 数据清洗

> 最后更新: 2026-04-11
>
> 分两大阶段:
> - **Phase A — 数据采集基础设施 + 结构化行情数据**: 反爬/限流客户端 + 日线/ETF/财务/基本面/板块等核心数据，**优先完成**
> - **Phase B — LLM 数据清洗 (暂缓)**: 新闻/情绪/舆情的 LLM 结构化抽取，待 Phase A 完成后启动
>
> 返回总览: [TODO.md](TODO.md) | P0 已全部完成

---

## LLM 数据清洗 (暂缓)

> Phase A 完成后再启动。LLM 清洗依赖采集数据，无数据无法端到端验证。
> datacollect 基础设施 (反爬/限流) 已提前到 Phase A。

### P0-12: LLMClient 统一客户端

| 属性 | 内容 |
|------|------|
| **模块** | dataclean |
| **文件** | `src/dataclean/llm_client.py` |
| **工作量** | 1 天 |

**为什么要做:**
数据清洗 (非结构化新闻 → 结构化情绪分数) 依赖 LLM 做结构化抽取。需要支持 DeepSeek 和 Qwen 两个模型的自动降级 — 主模型超时/限流时自动切换到备用模型。

**业界最佳实践 (2026):**
- DeepSeek 和 Qwen 均兼容 OpenAI SDK 协议，使用 `response_format={"type": "json_object"}` 输出 JSON
- **Prompt 中必须显式提及 "json"**: DeepSeek/Qwen 不支持 OpenAI 的 `json_schema` 模式，需要将 Pydantic Schema 嵌入 System Prompt
- **成本**: DeepSeek V3 约 ¥2/百万 token (输入)，Qwen-Max 约 ¥20/百万 token — DeepSeek 作为主模型，Qwen 作为降级备选

**技术选型:**

| 技术 | 版本 | 是否最新 | 说明 |
|------|------|---------|------|
| **openai** SDK | >=2.0 | ✅ 2026最新2.30.0 | DeepSeek/Qwen 均兼容此 SDK |
| **pydantic** | >=2.6 | ✅ | Schema 定义 + `.model_json_schema()` 导出 |
| tenacity | >=9.0 | ✅ | 重试 + 降级逻辑 |

**参考文档:**
- DeepSeek API 文档: [platform.deepseek.com/api-docs](https://platform.deepseek.com/api-docs)
- Qwen API 文档: [dashscope.aliyuncs.com](https://dashscope.aliyuncs.com/)
- [Enabling Qwen and DeepSeek for Structured Output](https://www.oreateai.com/blog/bridging-the-gap-enabling-qwen-and-deepseek-for-structured-output-in-microsofts-agent-framework/)
- [DeepSeek AI for Finance – Workflows & Prompts](https://deepseeksai.com/for-finance/)

**落地方案:**
```python
class LLMClient:
    PROVIDERS = [
        {"name": "deepseek", "base_url": "https://api.deepseek.com", "model": "deepseek-chat"},
        {"name": "qwen",     "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-max"},
    ]

    def extract(self, text: str, schema: type[BaseModel]) -> BaseModel:
        schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        system_prompt = f"Extract structured info as JSON matching this schema:\n{schema_json}"
        for provider in self.PROVIDERS:
            try:
                return self._call(provider, system_prompt, text, schema)
            except (Timeout, RateLimitError):
                continue
        return self._rule_fallback(text, schema)  # 全部失败时用 RuleCleaner
```

---

### P0-13 ~ P0-19: dataclean 模块其余组件

| # | 描述 | 文件 | 工作量 |
|---|------|------|--------|
| P0-13 | `BaseCleaner` + `CleanResult` 抽象基类 | `src/dataclean/base.py` | 0.5 天 |
| P0-14 | `SentimentExtraction` Pydantic Schema (情绪分/实体/事件类型) | `src/dataclean/schemas/sentiment.py` | 0.5 天 |
| P0-15 | `SentimentCleaner` LLM 清洗器 | `src/dataclean/cleaners/sentiment_cleaner.py` | 1 天 |
| P0-16 | `PassthroughCleaner` 直通清洗器 (已结构化 list[dict]) | `src/dataclean/cleaners/passthrough_cleaner.py` | 0.5 天 |
| P0-17 | `RuleCleaner` 规则降级清洗 (关键词+正则) | `src/dataclean/cleaners/rule_cleaner.py` | 0.5 天 |
| P0-18 | 情绪清洗 System Prompt 模板 | `src/dataclean/prompts/sentiment_prompt.py` | 0.5 天 |
| P0-19 | 模块初始化 + `.env` 参数 | `src/dataclean/__init__.py` + config | 0.5 天 |

**为什么要做:**
原始数据格式混杂 (HTML、JSON、纯文本)，需要经过清洗转换为标准 Pydantic Schema 后才能入库。三层清洗器 (LLM → 规则 → 直通) 形成降级链:
- **SentimentCleaner**: LLM 做精准情绪抽取 (成本 ~¥0.002/条，精度高)
- **RuleCleaner**: LLM 不可用时的正则/关键词兜底 (免费，精度一般)
- **PassthroughCleaner**: 采集器返回的已结构化 `list[dict]` 直接入库

> **本地推理模型选型 (2026 Q2 结论)**: FinBERT2-Base (125M, 情绪分类) + Qwen3-0.6B (600M, 结构化抽取)。
> TinyFinBERT 已淘汰 (英文专用)。详见 [13-数据清洗与LLM.md § 模型选型](13-数据清洗与LLM.md)。

**参考文档:** 详见 [doc/13-数据清洗与LLM.md](13-数据清洗与LLM.md)

---
