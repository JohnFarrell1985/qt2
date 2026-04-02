"""
选股接口 — DeepSeek / LLM 选股的抽象层

设计:
- StockPicker 是抽象基类，定义选股接口
- DeepSeekPicker 将来对接真实 DeepSeek API（目前 NotImplemented）
- MockPicker 使用预设选股结果进行回测
- RandomPicker 随机从股票池选股（基线对照组）
- load_prompt() 加载 prompts/ 目录下的提示词模板并填充日期等参数

对接 DeepSeek 时只需实现 DeepSeekPicker.pick()，其余不变。
"""
import random
import json
import os
from abc import ABC, abstractmethod
from datetime import date
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any

PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")


def load_prompt(name: str = "prompt1.txt", trade_date: date = None, **kwargs) -> str:
    """
    加载 prompts/ 目录下的提示词模板，替换占位符。

    支持的占位符:
        {TRADE_DATE}  — 替换为 "2025年3月24日" 格式的中文日期
        {TRADE_DATE_ISO} — 替换为 "2025-03-24" ISO格式
        自定义 **kwargs 中的键也会被替换

    Args:
        name: 提示词文件名 (位于 prompts/ 目录下)
        trade_date: 交易日期，None 则使用今天
        **kwargs: 额外的占位符替换，如 stock_pool="沪深300成分股"

    Returns:
        替换后的提示词字符串
    """
    if trade_date is None:
        trade_date = date.today()

    path = os.path.join(PROMPTS_DIR, name)
    with open(path, "r", encoding="utf-8") as f:
        template = f.read()

    cn_date = f"{trade_date.year}年{trade_date.month}月{trade_date.day}日"

    replacements = {
        "TRADE_DATE": cn_date,
        "TRADE_DATE_ISO": trade_date.isoformat(),
    }
    replacements.update(kwargs)

    for key, value in replacements.items():
        template = template.replace(f"{{{key}}}", str(value))

    return template


@dataclass
class PickResult:
    """选股结果"""
    trade_date: date          # 选股日期（收盘后运行，用于次日开盘买入）
    codes: List[str]          # 推荐的股票代码列表
    confidence: Dict[str, float] = field(default_factory=dict)  # 各股信心分 0-100
    reason: Dict[str, str] = field(default_factory=dict)        # 各股推荐理由
    raw_response: Optional[str] = None  # LLM原始返回（调试用）


class StockPicker(ABC):
    """选股抽象接口"""

    @abstractmethod
    def pick(self, trade_date: date, prompt: str = "") -> PickResult:
        """
        给定日期（当日收盘后），输出推荐股票列表。

        Args:
            trade_date: 选股参考日期（用收盘数据分析，次日开盘买入）
            prompt: 提示词内容

        Returns:
            PickResult
        """
        ...


class DeepSeekPicker(StockPicker):
    """
    DeepSeek API 选股 — 预留接口

    TODO: 对接 DeepSeek API
    1. 将 prompt + 当日行情数据组装为请求
    2. 调用 DeepSeek chat completion
    3. 解析返回的股票代码列表
    """

    def __init__(self, api_key: str = "", base_url: str = "", model: str = "deepseek-chat"):
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY", "")
        self.base_url = base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self.model = model

    def pick(self, trade_date: date, prompt: str = "") -> PickResult:
        raise NotImplementedError(
            "DeepSeek 选股尚未实现。请使用 MockPicker 进行回测，"
            "或实现此方法对接 DeepSeek API。"
        )


class MockPicker(StockPicker):
    """
    预设选股结果 — 用于回测验证策略框架

    支持两种模式:
    1. 从字典传入: {date: [codes]}
    2. 从JSON文件加载
    """

    def __init__(self, schedule: Dict[date, List[str]] = None,
                 schedule_file: str = None):
        self.schedule: Dict[date, List[str]] = {}

        if schedule:
            self.schedule = schedule
        elif schedule_file:
            self._load_from_file(schedule_file)

    def _load_from_file(self, path: str):
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        for date_str, codes in raw.items():
            self.schedule[date.fromisoformat(date_str)] = codes

    def pick(self, trade_date: date, prompt: str = "") -> PickResult:
        codes = self.schedule.get(trade_date, [])
        return PickResult(
            trade_date=trade_date,
            codes=codes,
            confidence={c: 80.0 for c in codes},
            reason={c: "MockPicker 预设选股" for c in codes},
        )


class RandomPicker(StockPicker):
    """
    随机选股 — 基线对照组

    从给定股票池中随机选取 n 只，作为策略对比基准。
    """

    def __init__(self, stock_pool: List[str], pick_count: int = 1, seed: int = 42):
        self.stock_pool = stock_pool
        self.pick_count = pick_count
        self.rng = random.Random(seed)

    def pick(self, trade_date: date, prompt: str = "") -> PickResult:
        n = min(self.pick_count, len(self.stock_pool))
        codes = self.rng.sample(self.stock_pool, n)
        return PickResult(
            trade_date=trade_date,
            codes=codes,
            confidence={c: 50.0 for c in codes},
            reason={c: "RandomPicker 随机选股" for c in codes},
        )
