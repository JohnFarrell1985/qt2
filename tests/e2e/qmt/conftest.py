"""QMT E2E 子目录 conftest — 通用 download 超时包装"""
import threading

import pytest

DOWNLOAD_TIMEOUT = 90


def run_download(fn, timeout=DOWNLOAD_TIMEOUT):
    """在 daemon 线程执行 QMT download, 超时返回 'timeout', 成功返回 None, 异常原样抛出"""
    done = threading.Event()
    error = [None]

    def _worker():
        try:
            fn()
        except Exception as e:
            error[0] = e
        finally:
            done.set()

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    if not done.wait(timeout=timeout):
        return "timeout"
    if error[0]:
        raise error[0]
    return None


def skip_if_broker_error(fn, action_name=""):
    """执行 fn, 遇 broker ErrorID 300000/200005 自动 skip"""
    try:
        return fn()
    except RuntimeError as e:
        msg = str(e)
        if "300000" in msg or "not realize" in msg or "200005" in msg:
            pytest.skip(f"券商不支持 {action_name}: {e}")
        raise


def download_or_skip(fn, action_name="download"):
    """download 封装: 超时 skip, 券商不支持 skip"""
    try:
        result = run_download(fn)
        if result == "timeout":
            pytest.skip(f"{action_name} 超时 ({DOWNLOAD_TIMEOUT}s), 券商数据服务阻塞")
    except RuntimeError as e:
        msg = str(e)
        if "300000" in msg or "not realize" in msg or "200005" in msg:
            pytest.skip(f"券商不支持 {action_name}: {e}")
        raise
