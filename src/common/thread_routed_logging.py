"""在 root logger 上按 ``LogRecord.threadName`` 分文件, 与 ``parallel_qmt`` 的 ``dc-类别`` 线程名配合.

同进程多线程在 OS 上**不能**为每个工作线程各绑一个真 TTY; 用「一类别一线程一 .log + 多窗口 tail」达到「各线细节分开看」.
若某库在 **线程池/executor** 里打 log, 其 ``threadName`` 可能不是 ``dc-*``, 将不会进任何分文件(仍可能出现在未过滤的 ``main``/stdout)."""

from __future__ import annotations

import logging
from pathlib import Path

# 与 src.common.logger 一致
_DEFAULT_FMT = "%(asctime)s %(name)s [%(levelname)s] %(message)s"


class _ThreadNameFilter(logging.Filter):
    def __init__(self, thread_name: str) -> None:
        super().__init__()
        self._name = thread_name

    def filter(self, record: logging.LogRecord) -> bool:
        return record.threadName == self._name


def install(
    log_dir: Path,
    thread_and_file: list[tuple[str, str]],
    *,
    fmt: str = _DEFAULT_FMT,
) -> tuple[list[logging.FileHandler], int, bool]:
    """在 ``log_dir`` 下为每对 (线程名, 不含后缀的文件名) 建 ``FileHandler``, 加在 root, 用线程过滤.

    为让子 logger 的 INFO 能冒泡到 root, 若当前 root 不接收 INFO, 会临时 ``root.setLevel(INFO)``.

    返回: (handlers, 调用前的 root.level, 是否改过 root 的 level) —— 若未改过 level, 解挂时只 remove handler.
    """
    log_dir = log_dir.resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    prev_level: int = root.level
    changed_level = not root.isEnabledFor(logging.INFO)
    if changed_level:
        root.setLevel(logging.INFO)

    formatter = logging.Formatter(fmt)
    handlers: list[logging.FileHandler] = []
    for thread_name, file_stem in thread_and_file:
        path = log_dir / f"{file_stem}.log"
        h = logging.FileHandler(path, encoding="utf-8")
        h.setLevel(logging.NOTSET)  # 以 record 与 root 为准
        h.setFormatter(formatter)
        h.addFilter(_ThreadNameFilter(thread_name))
        root.addHandler(h)
        handlers.append(h)
    return handlers, prev_level, changed_level


def uninstall(
    handlers: list[logging.FileHandler],
    previous_root_level: int,
    *,
    root_level_was_changed: bool,
) -> None:
    root = logging.getLogger()
    for h in handlers:
        try:
            root.removeHandler(h)
        except ValueError:
            pass
        try:
            h.close()
        except OSError:
            pass
    if root_level_was_changed:
        root.setLevel(previous_root_level)


def write_latest_pointer(base_dir: Path, session_dir: Path) -> Path:
    """在 ``base_dir/parallel_orch_latest.txt`` 写入本次 ``session`` 绝对路径, 供多终端脚本读取."""
    base_dir = base_dir.resolve()
    base_dir.mkdir(parents=True, exist_ok=True)
    p = base_dir / "parallel_orch_latest.txt"
    p.write_text(str(session_dir.resolve()) + "\n", encoding="utf-8")
    return p
