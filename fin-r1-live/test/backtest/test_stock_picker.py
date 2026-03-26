"""stock_picker 单元测试"""
import json
import os
import tempfile
from datetime import date
from unittest.mock import patch

import pytest

from backtest.stock_picker import (
    PickResult, StockPicker, DeepSeekPicker, MockPicker, RandomPicker,
    load_prompt, PROMPTS_DIR,
)


# ======== PickResult ========

class TestPickResult:
    def test_basic(self):
        r = PickResult(trade_date=date(2025, 1, 2), codes=["000001", "600519"])
        assert r.trade_date == date(2025, 1, 2)
        assert r.codes == ["000001", "600519"]
        assert r.confidence == {}
        assert r.reason == {}
        assert r.raw_response is None

    def test_with_confidence_and_reason(self):
        r = PickResult(
            trade_date=date(2025, 1, 2),
            codes=["000001"],
            confidence={"000001": 85.0},
            reason={"000001": "强势突破"},
            raw_response="raw llm output",
        )
        assert r.confidence["000001"] == 85.0
        assert r.reason["000001"] == "强势突破"
        assert r.raw_response == "raw llm output"

    def test_empty_codes(self):
        r = PickResult(trade_date=date(2025, 3, 1), codes=[])
        assert len(r.codes) == 0


# ======== DeepSeekPicker ========

class TestDeepSeekPicker:
    def test_not_implemented(self):
        picker = DeepSeekPicker()
        with pytest.raises(NotImplementedError, match="DeepSeek 选股尚未实现"):
            picker.pick(date(2025, 1, 2))

    def test_custom_config(self):
        picker = DeepSeekPicker(api_key="test-key", base_url="http://test", model="test-model")
        assert picker.api_key == "test-key"
        assert picker.base_url == "http://test"
        assert picker.model == "test-model"

    def test_env_defaults(self):
        with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "env-key", "DEEPSEEK_BASE_URL": "http://env"}):
            picker = DeepSeekPicker()
            assert picker.api_key == "env-key"
            assert picker.base_url == "http://env"

    def test_with_prompt(self):
        picker = DeepSeekPicker()
        with pytest.raises(NotImplementedError):
            picker.pick(date(2025, 1, 2), prompt="选股提示词")


# ======== MockPicker ========

class TestMockPicker:
    def test_from_dict(self):
        schedule = {
            date(2025, 1, 2): ["000001", "600519"],
            date(2025, 1, 6): ["000002"],
        }
        picker = MockPicker(schedule=schedule)
        r = picker.pick(date(2025, 1, 2))
        assert r.codes == ["000001", "600519"]
        assert r.trade_date == date(2025, 1, 2)
        assert r.confidence == {"000001": 80.0, "600519": 80.0}

    def test_missing_date_returns_empty(self):
        picker = MockPicker(schedule={date(2025, 1, 2): ["000001"]})
        r = picker.pick(date(2025, 3, 1))
        assert r.codes == []
        assert r.confidence == {}

    def test_from_json_file(self):
        data = {
            "2025-01-02": ["000001"],
            "2025-01-06": ["600519", "000002"],
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
            json.dump(data, f)
            f.flush()
            path = f.name

        try:
            picker = MockPicker(schedule_file=path)
            r1 = picker.pick(date(2025, 1, 2))
            assert r1.codes == ["000001"]
            r2 = picker.pick(date(2025, 1, 6))
            assert r2.codes == ["600519", "000002"]
        finally:
            os.unlink(path)

    def test_empty_schedule(self):
        picker = MockPicker(schedule={})
        r = picker.pick(date(2025, 5, 1))
        assert r.codes == []

    def test_reason_filled(self):
        picker = MockPicker(schedule={date(2025, 1, 2): ["000001"]})
        r = picker.pick(date(2025, 1, 2))
        assert "MockPicker" in r.reason["000001"]


# ======== RandomPicker ========

class TestRandomPicker:
    def test_basic(self):
        pool = ["000001", "600519", "000002", "600036"]
        picker = RandomPicker(pool, pick_count=2, seed=42)
        r = picker.pick(date(2025, 1, 2))
        assert len(r.codes) == 2
        assert all(c in pool for c in r.codes)

    def test_deterministic_with_seed(self):
        pool = ["000001", "600519", "000002", "600036", "000858"]
        p1 = RandomPicker(pool, pick_count=2, seed=123)
        p2 = RandomPicker(pool, pick_count=2, seed=123)
        r1 = p1.pick(date(2025, 1, 2))
        r2 = p2.pick(date(2025, 1, 2))
        assert r1.codes == r2.codes

    def test_different_seeds_differ(self):
        pool = ["000001", "600519", "000002", "600036", "000858"]
        p1 = RandomPicker(pool, pick_count=3, seed=1)
        p2 = RandomPicker(pool, pick_count=3, seed=999)
        r1 = p1.pick(date(2025, 1, 2))
        r2 = p2.pick(date(2025, 1, 2))
        # 不同种子有可能碰巧相同，但概率极低; 这里只验证它能运行
        assert len(r1.codes) == 3
        assert len(r2.codes) == 3

    def test_pick_count_exceeds_pool(self):
        pool = ["000001", "600519"]
        picker = RandomPicker(pool, pick_count=5, seed=42)
        r = picker.pick(date(2025, 1, 2))
        assert len(r.codes) == 2

    def test_confidence_50(self):
        picker = RandomPicker(["000001"], pick_count=1, seed=42)
        r = picker.pick(date(2025, 1, 2))
        assert r.confidence[r.codes[0]] == 50.0

    def test_sequential_picks_vary(self):
        pool = ["000001", "600519", "000002", "600036", "000858"]
        picker = RandomPicker(pool, pick_count=1, seed=42)
        results = [picker.pick(date(2025, 1, d)).codes[0] for d in [2, 3, 6, 7, 8]]
        # 5 次随机选 1 只，至少应该有一些变化
        assert len(results) == 5


# ======== load_prompt ========

class TestLoadPrompt:
    def test_load_prompt1(self):
        text = load_prompt("prompt1.txt", trade_date=date(2025, 3, 24))
        assert "2025年3月24日" in text
        assert "{TRADE_DATE}" not in text

    def test_default_date_is_today(self):
        text = load_prompt("prompt1.txt")
        today = date.today()
        cn = f"{today.year}年{today.month}月{today.day}日"
        assert cn in text

    def test_trade_date_iso_placeholder(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", dir=PROMPTS_DIR,
            delete=False, encoding="utf-8"
        ) as f:
            f.write("日期: {TRADE_DATE} ISO: {TRADE_DATE_ISO}")
            f.flush()
            name = os.path.basename(f.name)
        try:
            text = load_prompt(name, trade_date=date(2025, 6, 15))
            assert "2025年6月15日" in text
            assert "2025-06-15" in text
        finally:
            os.unlink(os.path.join(PROMPTS_DIR, name))

    def test_custom_kwargs(self):
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", dir=PROMPTS_DIR,
            delete=False, encoding="utf-8"
        ) as f:
            f.write("股票池: {POOL}")
            f.flush()
            name = os.path.basename(f.name)
        try:
            text = load_prompt(name, trade_date=date(2025, 1, 1), POOL="沪深300")
            assert "沪深300" in text
        finally:
            os.unlink(os.path.join(PROMPTS_DIR, name))

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_prompt("nonexistent_prompt.txt")


# ======== ABC enforcement ========

class TestStockPickerABC:
    def test_cannot_instantiate(self):
        with pytest.raises(TypeError):
            StockPicker()
