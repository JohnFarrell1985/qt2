"""Backward-compat re-export — canonical location is src.sentiment.sentiment_bridge"""
from src.sentiment.sentiment_bridge import SentimentBridge, _clip  # noqa: F401

__all__ = ["SentimentBridge", "_clip"]
