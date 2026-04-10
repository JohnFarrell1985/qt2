"""Tests for src/sentiment/models.py"""
from datetime import date, datetime
from src.sentiment.models import SentimentDaily, SentimentIngestLog


class TestSentimentDaily:
    def test_instantiation(self):
        obj = SentimentDaily(
            trade_date=date(2025, 1, 6),
            ad_ratio=1.25,
            limit_up_count=42,
            limit_down_count=8,
            composite_sentiment=0.35,
            suggested_state="bull_weak",
            applied_state="bull_weak",
            state_confidence=0.82,
            earning_effect=0.5,
            capital_mood=0.3,
            volatility_mood=-0.2,
            sector_heat=0.4,
            news_mood=0.1,
            global_mood=-0.1,
            hot_sectors=["半导体", "AI"],
            key_events=["降息预期"],
        )
        assert obj.trade_date == date(2025, 1, 6)
        assert obj.ad_ratio == 1.25
        assert obj.limit_up_count == 42
        assert obj.limit_down_count == 8
        assert obj.composite_sentiment == 0.35
        assert obj.suggested_state == "bull_weak"
        assert obj.hot_sectors == ["半导体", "AI"]

    def test_to_dict_keys(self):
        obj = SentimentDaily(
            trade_date=date(2025, 3, 10),
            ad_ratio=0.8,
            limit_up_count=15,
            limit_down_count=30,
            composite_sentiment=-0.5,
            suggested_state="bear_strong",
            applied_state="bear_strong",
            state_confidence=0.9,
            earning_effect=-0.3,
            capital_mood=-0.4,
            volatility_mood=0.6,
            sector_heat=-0.1,
            news_mood=-0.5,
            global_mood=-0.3,
            hot_sectors=[],
            key_events=[],
        )
        d = obj.to_dict()
        expected_keys = {
            "trade_date", "ad_ratio", "limit_up_count", "limit_down_count",
            "composite_sentiment", "suggested_state", "applied_state",
            "state_confidence", "earning_effect", "capital_mood",
            "volatility_mood", "sector_heat", "news_mood", "global_mood",
            "hot_sectors", "key_events",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_values(self):
        obj = SentimentDaily(
            trade_date=date(2025, 6, 1),
            ad_ratio=2.0,
            limit_up_count=60,
            limit_down_count=3,
            composite_sentiment=0.8,
            suggested_state="bull_strong",
            applied_state="bull_strong",
            state_confidence=0.95,
        )
        d = obj.to_dict()
        assert d["trade_date"] == "2025-06-01"
        assert d["ad_ratio"] == 2.0
        assert d["limit_up_count"] == 60
        assert d["composite_sentiment"] == 0.8

    def test_to_dict_none_trade_date(self):
        obj = SentimentDaily(trade_date=None)
        d = obj.to_dict()
        assert d["trade_date"] is None


class TestSentimentIngestLog:
    def test_instantiation(self):
        collected = datetime(2025, 3, 10, 9, 30, 0)
        obj = SentimentIngestLog(
            id=1,
            trade_date=date(2025, 3, 10),
            source_name="akshare_north",
            schedule_slot="09:30",
            status="success",
            llm_provider="openai",
            llm_model="gpt-4o-mini",
            llm_tokens_in=500,
            llm_tokens_out=200,
            llm_cost_cny=0.05,
            collected_at=collected,
        )
        assert obj.id == 1
        assert obj.trade_date == date(2025, 3, 10)
        assert obj.source_name == "akshare_north"
        assert obj.status == "success"
        assert obj.llm_provider == "openai"

    def test_to_dict_keys(self):
        obj = SentimentIngestLog(
            id=2,
            trade_date=date(2025, 3, 10),
            source_name="news_llm",
            schedule_slot="15:30",
            status="failed",
            error_message="timeout",
            llm_provider="deepseek",
            llm_model="deepseek-chat",
            llm_tokens_in=100,
            llm_tokens_out=0,
            llm_cost_cny=0.01,
            collected_at=datetime(2025, 3, 10, 15, 30),
        )
        d = obj.to_dict()
        expected_keys = {
            "id", "trade_date", "source_name", "schedule_slot",
            "status", "error_message", "llm_provider", "llm_model",
            "llm_tokens_in", "llm_tokens_out", "llm_cost_cny",
            "collected_at",
        }
        assert set(d.keys()) == expected_keys

    def test_to_dict_values(self):
        collected = datetime(2025, 5, 20, 10, 0, 0)
        obj = SentimentIngestLog(
            id=10,
            trade_date=date(2025, 5, 20),
            source_name="xueqiu",
            schedule_slot="10:00",
            status="success",
            llm_provider="qwen",
            llm_model="qwen-max",
            llm_tokens_in=800,
            llm_tokens_out=300,
            llm_cost_cny=0.03,
            collected_at=collected,
        )
        d = obj.to_dict()
        assert d["id"] == 10
        assert d["trade_date"] == "2025-05-20"
        assert d["source_name"] == "xueqiu"
        assert d["collected_at"] == "2025-05-20T10:00:00"

    def test_to_dict_none_collected_at(self):
        obj = SentimentIngestLog(
            id=3,
            trade_date=date(2025, 1, 1),
            source_name="test",
            collected_at=None,
        )
        d = obj.to_dict()
        assert d["collected_at"] is None
