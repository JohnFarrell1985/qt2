"""Tests for src/common/event_bus.py"""
import pytest

from src.common.event_bus import _SimpleSignal, _SimpleNamespace


class TestSimpleSignal:
    @pytest.mark.timeout(30)
    def test_connect_and_send(self):
        sig = _SimpleSignal("test")
        received = []
        sig.connect(lambda sender, **kw: received.append((sender, kw)))
        sig.send("me", key="val")
        assert len(received) == 1
        assert received[0] == ("me", {"key": "val"})

    @pytest.mark.timeout(30)
    def test_multiple_handlers(self):
        sig = _SimpleSignal("test")
        calls = []
        sig.connect(lambda s, **kw: calls.append("a"))
        sig.connect(lambda s, **kw: calls.append("b"))
        sig.send("x")
        assert calls == ["a", "b"]

    @pytest.mark.timeout(30)
    def test_disconnect(self):
        sig = _SimpleSignal("test")
        calls = []

        def handler(sender, **kw):
            calls.append(sender)

        sig.connect(handler)
        sig.send("first")
        assert len(calls) == 1

        sig.disconnect(handler)
        sig.send("second")
        assert len(calls) == 1

    @pytest.mark.timeout(30)
    def test_handler_exception_does_not_crash_others(self):
        sig = _SimpleSignal("test")
        results = []

        def bad_handler(sender, **kw):
            raise ValueError("boom")

        def good_handler(sender, **kw):
            results.append(sender)

        sig.connect(bad_handler)
        sig.connect(good_handler)
        sig.send("ok")
        assert results == ["ok"]

    @pytest.mark.timeout(30)
    def test_send_with_no_receivers(self):
        sig = _SimpleSignal("empty")
        sig.send("nobody_listening")


class TestSimpleNamespace:
    @pytest.mark.timeout(30)
    def test_signal_creation(self):
        ns = _SimpleNamespace()
        s1 = ns.signal("foo")
        assert isinstance(s1, _SimpleSignal)
        assert s1.name == "foo"

    @pytest.mark.timeout(30)
    def test_same_name_returns_same_signal(self):
        ns = _SimpleNamespace()
        s1 = ns.signal("bar")
        s2 = ns.signal("bar")
        assert s1 is s2

    @pytest.mark.timeout(30)
    def test_different_names_different_signals(self):
        ns = _SimpleNamespace()
        s1 = ns.signal("a")
        s2 = ns.signal("b")
        assert s1 is not s2


class TestPredefinedSignals:
    @pytest.mark.timeout(30)
    def test_predefined_signals_exist(self):
        from src.common import event_bus

        expected = [
            "data_collected", "data_cleaned", "factor_computed",
            "model_predicted", "signal_generated", "trade_executed",
            "risk_alert", "flywheel_queued",
        ]
        for name in expected:
            sig = getattr(event_bus, name, None)
            assert sig is not None, f"signal '{name}' not found on event_bus module"

    @pytest.mark.timeout(30)
    def test_events_namespace_exists(self):
        from src.common.event_bus import events
        assert events is not None
