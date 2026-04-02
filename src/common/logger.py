"""日志模块"""
import logging
import os
import sys

_DEFAULT_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
_FMT = "%(asctime)s %(name)s [%(levelname)s] %(message)s"


def get_logger(name: str, level: str = "") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter(_FMT))
        logger.addHandler(handler)
    effective = (level or _DEFAULT_LEVEL).upper()
    logger.setLevel(getattr(logging, effective, logging.INFO))
    return logger
