"""调度器独立入口 — 本地后台常驻进程."""
import signal
import sys
import time

sys.path.insert(0, ".")

from src.scheduler import start_scheduler, stop_scheduler
from src.common.logger import get_logger

logger = get_logger(__name__)
_shutdown = False


def _handle_signal(signum, frame):
    global _shutdown
    logger.info("收到信号 %s, 正在优雅退出...", signum)
    _shutdown = True
    stop_scheduler()


def main():
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    logger.info("调度器进程启动")
    start_scheduler()

    try:
        while not _shutdown:
            time.sleep(5)
    except KeyboardInterrupt:
        pass
    finally:
        stop_scheduler()
        logger.info("调度器进程退出")


if __name__ == "__main__":
    main()
