"""dataclean E2E 测试 fixtures

真实调用 DeepSeek / Qwen API, 验证完整清洗链路。
不需要 DB, 仅测试 LLM 抽取 + Schema 校验 + 降级链。

运行方式:
  pytest tests/e2e/dataclean/ -v --timeout=120
"""
import pytest

from src.common.config import settings
from src.dataclean.exceptions import AllProvidersFailedError
from src.dataclean.llm_client import LLMClient


@pytest.fixture(scope="session")
def dataclean_settings():
    """返回真实 DatacleanConfig (从 env/.env.datacollect 加载)"""
    return settings.dataclean


@pytest.fixture(scope="session")
def llm_client(dataclean_settings):
    """构造真实 LLMClient — 需要 DEEPSEEK_API_KEY 或 QWEN_API_KEY 已配置"""
    if not dataclean_settings.deepseek_api_key and not dataclean_settings.qwen_api_key:
        pytest.skip("DEEPSEEK_API_KEY 和 QWEN_API_KEY 均未配置, 跳过 LLM E2E")
    return LLMClient(dataclean_settings)


def skip_on_auth_failure(func):
    """装饰器: API key 无效 (401) 或 LLM 服务不可用时 skip 而非 fail"""
    import functools

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except AllProvidersFailedError as e:
            msg = str(e).lower()
            auth_markers = ["401", "invalid_api_key", "authentication", "invalid_request_error"]
            if any(m in msg for m in auth_markers):
                pytest.skip(f"API key 无效或过期, 跳过: {str(e)[:150]}")
            pytest.skip(f"LLM 服务不可用, 跳过: {str(e)[:150]}")

    return wrapper


SAMPLE_NEWS_CN = (
    "央行宣布降准50个基点，释放约1.2万亿元长期资金。"
    "受此消息提振，银行股集体走强，工商银行(601398.SH)涨幅超3%。"
    "北向资金今日净流入超120亿元，创近三个月新高。"
    "白酒板块逆势走弱，贵州茅台(600519.SH)微跌1.2%。"
    "国际油价小幅回落至78美元/桶，黄金维持2350美元/盎司高位。"
)

SAMPLE_NEWS_NEUTRAL = "今日A股三大指数小幅震荡，成交量略有萎缩，市场观望情绪浓厚。"
