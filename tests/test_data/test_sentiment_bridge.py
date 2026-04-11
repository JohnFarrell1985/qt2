"""Tests for SentimentBridge"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from src.datacollect.sentiment_bridge import SentimentBridge, _clip


class TestClip:
    def test_within_range(self):
        assert _clip(0.5) == 0.5

    def test_above_max(self):
        assert _clip(1.5) == 1.0

    def test_below_min(self):
        assert _clip(-1.5) == -1.0

    def test_exact_bounds(self):
        assert _clip(1.0) == 1.0
        assert _clip(-1.0) == -1.0


class TestComputeGlobalFields:
    @pytest.fixture
    def bridge(self):
        session = MagicMock()
        return SentimentBridge(session=session)

    def test_empty_snapshots(self, bridge):
        with patch.object(bridge, "_latest_snapshots", return_value={}):
            fields = bridge.compute_global_fields(date(2026, 4, 2))
        assert fields == {}

    def test_direct_field_mappings(self, bridge):
        snapshots = {
            "USDCNY": {"close_price": 7.25, "change_pct": 0.1, "source": "yfinance", "asset_class": "forex", "_collected_at": None},
            "XAUUSD": {"close_price": 2350.0, "change_pct": 0.5, "source": "yfinance", "asset_class": "commodity", "_collected_at": None},
            "WTI": {"close_price": 75.0, "change_pct": -0.3, "source": "yfinance", "asset_class": "commodity", "_collected_at": None},
        }
        with patch.object(bridge, "_latest_snapshots", return_value=snapshots):
            fields = bridge.compute_global_fields(date(2026, 4, 2))
        assert fields["fx_usdcny"] == 7.25
        assert fields["gold_price_usd"] == 2350.0
        assert fields["crude_oil_usd"] == 75.0

    def test_global_mood_bullish(self, bridge):
        snapshots = {
            "SPX": {"close_price": 5100, "change_pct": 1.5, "source": "yf", "asset_class": "global_index", "_collected_at": None},
            "VIX": {"close_price": 12.0, "change_pct": -5, "source": "yf", "asset_class": "vix", "_collected_at": None},
            "FTSE_A50": {"close_price": 13000, "change_pct": 1.2, "source": "yf", "asset_class": "global_index", "_collected_at": None},
        }
        with patch.object(bridge, "_latest_snapshots", return_value=snapshots):
            fields = bridge.compute_global_fields(date(2026, 4, 2))
        assert fields["global_mood"] > 0

    def test_global_mood_bearish(self, bridge):
        snapshots = {
            "SPX": {"close_price": 4800, "change_pct": -2.0, "source": "yf", "asset_class": "global_index", "_collected_at": None},
            "VIX": {"close_price": 35.0, "change_pct": 15, "source": "yf", "asset_class": "vix", "_collected_at": None},
            "USDCNY": {"close_price": 7.5, "change_pct": 0.5, "source": "yf", "asset_class": "forex", "_collected_at": None},
        }
        with patch.object(bridge, "_latest_snapshots", return_value=snapshots):
            fields = bridge.compute_global_fields(date(2026, 4, 2))
        assert fields["global_mood"] < 0

    def test_global_mood_clipped(self, bridge):
        snapshots = {
            "SPX": {"close_price": 5100, "change_pct": 3.0, "source": "yf", "asset_class": "global_index", "_collected_at": None},
            "VIX": {"close_price": 10.0, "change_pct": -10, "source": "yf", "asset_class": "vix", "_collected_at": None},
            "XAUUSD": {"close_price": 2300, "change_pct": -2.0, "source": "yf", "asset_class": "commodity", "_collected_at": None},
            "USDCNY": {"close_price": 7.0, "change_pct": -0.5, "source": "yf", "asset_class": "forex", "_collected_at": None},
            "FTSE_A50": {"close_price": 14000, "change_pct": 2.0, "source": "yf", "asset_class": "global_index", "_collected_at": None},
        }
        with patch.object(bridge, "_latest_snapshots", return_value=snapshots):
            fields = bridge.compute_global_fields(date(2026, 4, 2))
        assert -1.0 <= fields["global_mood"] <= 1.0


class TestUpdateSentimentDaily:
    def test_insert_new_row(self):
        session = MagicMock()
        session.get.return_value = None
        bridge = SentimentBridge(session=session)

        with patch.object(bridge, "compute_global_fields", return_value={"fx_usdcny": 7.25, "global_mood": 0.3}):
            result = bridge.update_sentiment_daily(date(2026, 4, 2))
        assert result["fx_usdcny"] == 7.25
        session.add.assert_called_once()
        session.flush.assert_called_once()

    def test_update_existing_row(self):
        session = MagicMock()
        existing = MagicMock()
        session.get.return_value = existing
        bridge = SentimentBridge(session=session)

        with patch.object(bridge, "compute_global_fields", return_value={"gold_price_usd": 2350.0}):
            bridge.update_sentiment_daily(date(2026, 4, 2))
        assert existing.gold_price_usd == 2350.0
        session.add.assert_not_called()

    def test_empty_fields_returns_empty(self):
        session = MagicMock()
        bridge = SentimentBridge(session=session)

        with patch.object(bridge, "compute_global_fields", return_value={}):
            result = bridge.update_sentiment_daily(date(2026, 4, 2))
        assert result == {}
        session.flush.assert_not_called()
