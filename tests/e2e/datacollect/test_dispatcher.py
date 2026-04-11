"""E2E: FallbackDispatcher 降级链集成测试

验证 Dispatcher 在真实环境中的降级逻辑:
- 主数据源成功时直接返回
- 主数据源失败时自动降级到下一个
- 所有源失败时正确抛异常

注: stock_list 类型通过 akshare 会触发 stock_zh_a_spot_em 全量拉取 (分钟级),
因此 E2E 测试优先使用 daily_kline (仅查单只股票几天数据, 秒级完成)。
"""
import pytest
import time

import pandas as pd

from src.datacollect.base import CollectResult
from src.datacollect.dispatcher import FallbackDispatcher
from src.datacollect.rate_limiter import TokenBucketLimiter


RATE_LIMIT_PAUSE = 3


@pytest.fixture(autouse=True)
def _rate_limit_reset():
    yield
    TokenBucketLimiter.reset_all()


@pytest.fixture(scope="module")
def dispatcher():
    return FallbackDispatcher()


class TestDispatcherFetchDailyKline:
    """通过 daily_kline 降级链验证 Dispatcher 基本功能"""

    @pytest.mark.timeout(90)
    def test_fetch_daily_kline(self, dispatcher):
        """daily_kline 降级链: baostock 优先, 取贵州茅台近几天"""
        time.sleep(RATE_LIMIT_PAUSE)
        try:
            result = dispatcher.fetch(
                "daily_kline",
                code="sh.600519",
                start_date="2026-03-01",
                end_date="2026-03-10",
            )
        except RuntimeError:
            pytest.skip("所有 daily_kline 数据源均不可用")

        assert isinstance(result, CollectResult)
        assert result.source in ("baostock", "akshare", "tushare", "adata", "pytdx")
        df = result.data
        assert isinstance(df, pd.DataFrame)
        assert len(df) >= 1

    @pytest.mark.timeout(90)
    def test_fetch_index_daily(self, dispatcher):
        """index_daily 降级链"""
        time.sleep(RATE_LIMIT_PAUSE)
        try:
            result = dispatcher.fetch(
                "index_daily",
                code="sh.000300",
                start_date="2026-03-01",
                end_date="2026-03-10",
            )
        except RuntimeError:
            pytest.skip("所有 index_daily 数据源均不可用")

        assert isinstance(result, CollectResult)
        df = result.data
        assert isinstance(df, pd.DataFrame)
        assert len(df) >= 1


class TestDispatcherFallbackLogic:
    """降级链逻辑验证 — 纯 mock, 不触发真实网络请求"""

    @pytest.mark.timeout(30)
    def test_all_sources_fail_raises(self, dispatcher):
        """所有源都失败时应抛 RuntimeError"""
        from unittest.mock import MagicMock

        chain = dispatcher.registry.get_fallback_chain("daily_kline")
        saved = {}
        for src in chain:
            bad = MagicMock()
            bad.health_check.return_value = True
            bad.collect.side_effect = RuntimeError("模拟全部失败")
            saved[src] = dispatcher._collectors.get(src)
            dispatcher._collectors[src] = bad

        try:
            with pytest.raises(RuntimeError, match="所有数据源均失败"):
                dispatcher.fetch(
                    "daily_kline",
                    code="sh.600519",
                    start_date="2026-03-01",
                    end_date="2026-03-05",
                )
        finally:
            for src in chain:
                if saved[src] is not None:
                    dispatcher._collectors[src] = saved[src]
                else:
                    dispatcher._collectors.pop(src, None)

    @pytest.mark.timeout(30)
    def test_fallback_skips_unavailable(self, dispatcher):
        """mock 某个源 collect 抛异常, dispatcher 应跳过并尝试下一个"""
        from unittest.mock import MagicMock

        chain = dispatcher.registry.get_fallback_chain("daily_kline")
        if len(chain) < 2:
            pytest.skip("daily_kline 降级链不足 2 个源")

        first_source = chain[0]
        bad = MagicMock()
        bad.health_check.return_value = True
        bad.collect.side_effect = RuntimeError("模拟源故障")

        good_result = CollectResult(
            source=chain[1],
            data=pd.DataFrame({"date": ["2026-03-03"], "close": [1900.0]}),
        )
        good = MagicMock()
        good.health_check.return_value = True
        good.collect.return_value = good_result

        saved_first = dispatcher._collectors.get(first_source)
        saved_second = dispatcher._collectors.get(chain[1])
        dispatcher._collectors[first_source] = bad
        dispatcher._collectors[chain[1]] = good

        try:
            result = dispatcher.fetch(
                "daily_kline",
                code="sh.600519",
                start_date="2026-03-01",
                end_date="2026-03-05",
            )
            assert result.source == chain[1]
            assert len(result.data) == 1
        finally:
            if saved_first is not None:
                dispatcher._collectors[first_source] = saved_first
            else:
                dispatcher._collectors.pop(first_source, None)
            if saved_second is not None:
                dispatcher._collectors[chain[1]] = saved_second
            else:
                dispatcher._collectors.pop(chain[1], None)

    @pytest.mark.timeout(30)
    def test_empty_result_triggers_fallback(self, dispatcher):
        """主源返回空 DataFrame 时应降级到下一个"""
        from unittest.mock import MagicMock

        chain = dispatcher.registry.get_fallback_chain("daily_kline")
        if len(chain) < 2:
            pytest.skip("daily_kline 降级链不足 2 个源")

        empty = MagicMock()
        empty.health_check.return_value = True
        empty.collect.return_value = CollectResult(
            source=chain[0], data=pd.DataFrame(),
        )

        good_result = CollectResult(
            source=chain[1],
            data=pd.DataFrame({"date": ["2026-03-03"], "close": [1900.0]}),
        )
        good = MagicMock()
        good.health_check.return_value = True
        good.collect.return_value = good_result

        saved_first = dispatcher._collectors.get(chain[0])
        saved_second = dispatcher._collectors.get(chain[1])
        dispatcher._collectors[chain[0]] = empty
        dispatcher._collectors[chain[1]] = good

        try:
            result = dispatcher.fetch(
                "daily_kline",
                code="sh.600519",
                start_date="2026-03-01",
                end_date="2026-03-05",
            )
            assert result.source == chain[1]
        finally:
            if saved_first is not None:
                dispatcher._collectors[chain[0]] = saved_first
            else:
                dispatcher._collectors.pop(chain[0], None)
            if saved_second is not None:
                dispatcher._collectors[chain[1]] = saved_second
            else:
                dispatcher._collectors.pop(chain[1], None)

    @pytest.mark.timeout(10)
    def test_unknown_data_type_raises(self, dispatcher):
        """不存在的 data_type 应抛异常"""
        with pytest.raises(RuntimeError, match="未配置"):
            dispatcher.fetch("nonexistent_type_xyz")


class TestDispatcherIdempotent:
    """幂等性: 多次 fetch 同类型数据不报错"""

    @pytest.mark.timeout(120)
    def test_repeated_fetch(self, dispatcher):
        time.sleep(RATE_LIMIT_PAUSE)
        results = []
        for _ in range(2):
            try:
                r = dispatcher.fetch(
                    "daily_kline",
                    code="sh.600519",
                    start_date="2026-03-01",
                    end_date="2026-03-05",
                )
                results.append(len(r.data))
            except RuntimeError:
                pytest.skip("daily_kline 源不可用")
            time.sleep(RATE_LIMIT_PAUSE)

        assert len(results) == 2
        assert results[0] == results[1]
