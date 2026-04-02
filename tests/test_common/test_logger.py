"""Tests for src/common/logger.py"""
import logging

from src.common.logger import get_logger


class TestGetLogger:
    def test_returns_logger_instance(self):
        logger = get_logger("test_returns")
        assert isinstance(logger, logging.Logger)
        assert logger.name == "test_returns"

    def test_sets_default_info_level(self):
        logger = get_logger("test_default_level")
        assert logger.level == logging.INFO

    def test_sets_debug_level(self):
        logger = get_logger("test_debug", level="DEBUG")
        assert logger.level == logging.DEBUG

    def test_sets_warning_level(self):
        logger = get_logger("test_warning", level="WARNING")
        assert logger.level == logging.WARNING

    def test_sets_error_level(self):
        logger = get_logger("test_error", level="ERROR")
        assert logger.level == logging.ERROR

    def test_sets_critical_level(self):
        logger = get_logger("test_critical", level="CRITICAL")
        assert logger.level == logging.CRITICAL

    def test_case_insensitive_level(self):
        logger = get_logger("test_case", level="debug")
        assert logger.level == logging.DEBUG

    def test_invalid_level_falls_back_to_info(self):
        logger = get_logger("test_invalid_level", level="NONEXISTENT")
        assert logger.level == logging.INFO

    def test_adds_stream_handler(self):
        logger = get_logger("test_handler_added")
        assert len(logger.handlers) >= 1
        assert any(isinstance(h, logging.StreamHandler) for h in logger.handlers)

    def test_no_duplicate_handlers(self):
        name = "test_no_dup_handlers"
        logger1 = get_logger(name)
        count_after_first = len(logger1.handlers)
        logger2 = get_logger(name)
        assert len(logger2.handlers) == count_after_first
        assert logger1 is logger2

    def test_handler_has_formatter(self):
        logger = get_logger("test_formatter")
        handler = logger.handlers[0]
        fmt = handler.formatter._fmt
        assert "%(asctime)s" in fmt
        assert "%(name)s" in fmt
        assert "%(levelname)s" in fmt
        assert "%(message)s" in fmt

    def test_different_names_return_different_loggers(self):
        a = get_logger("logger_a")
        b = get_logger("logger_b")
        assert a is not b
        assert a.name != b.name

    def test_level_can_be_changed_on_subsequent_call(self):
        logger = get_logger("test_relevel", level="INFO")
        assert logger.level == logging.INFO
        logger = get_logger("test_relevel", level="DEBUG")
        assert logger.level == logging.DEBUG
