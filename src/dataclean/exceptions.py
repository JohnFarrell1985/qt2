"""dataclean 模块错误层级

上游统一 ``except DatacleanError`` 捕获所有清洗错误, 也可按子类精细处理。
"""


class DatacleanError(Exception):
    """dataclean 模块所有错误的基类"""


class AllProvidersFailedError(DatacleanError):
    """所有 LLM 提供商 (DeepSeek + Qwen) 重试耗尽后均失败"""


class SchemaValidationError(DatacleanError):
    """LLM 返回的 JSON 未通过 Pydantic Schema 校验 (instructor 重试后仍失败)"""


class LLMTimeoutError(DatacleanError):
    """LLM 调用超时 (超过 LLM_TIMEOUT 秒)"""
