"""另类日频: 多数据源级联, **同一源内**异常可重试, 0 行则换下一源; 与业务无关的纯控制逻辑.

每个数据源在单段内最多等待 ``per_source_timeout_sec``(默认 120s) 的墙钟时间; 单段内仍可在该预算下多次
``retries`` 尝试(含超时/异常重试), 与 ``DATACOLLECT_SOURCE_PER_SOURCE_TIMEOUT_SEC`` 一致.

**连续失败停用** (``CascadeStrikeState``): 在 **同一次** 多日续传任务中, 若某源名连续多次「该源执行回调返回行数
≤0」(见 ``record_attempts``), 则本任务后续日期不再把该源加入 ``layers``, 避免对无权限/无数据的接口逐日空转.
单日内的级联顺序不变; 不同 **日期** 必须分别请求, 这是业务要求, 与停用坏源不矛盾.
"""
from __future__ import annotations

import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field

from src.common.config import settings
from src.common.logger import get_logger

logger = get_logger(__name__)

DEFAULT_RETRIES = 5
RETRY_BACKOFF = 0.4


@dataclass
class CascadeStrikeState:
    """按「源名字符串」统计连续无有效行次数, 达阈值则加入 ``disabled``."""

    threshold: int
    _strikes: dict[str, int] = field(default_factory=dict)
    disabled: set[str] = field(default_factory=set)
    request_stop: bool = False
    warned_all_disabled_logged: bool = False

    def record_attempts(
        self,
        attempts: list[tuple[str, int]],
        *,
        success_if: Callable[[int], bool] | None = None,
    ) -> None:
        """对 ``run_source_stack`` 返回的按序尝试列表更新计数: 单源若本次无有效行则累加, 否则清零."""
        if self.threshold <= 0:
            return

        def _ok(x: int) -> bool:
            if success_if is not None:
                return bool(success_if(x))
            return int(x) > 0

        for name, n in attempts:
            if name in self.disabled:
                continue
            if _ok(n):
                self._strikes[name] = 0
                continue
            c = self._strikes.get(name, 0) + 1
            self._strikes[name] = c
            if c >= self.threshold:
                self.disabled.add(name)
                logger.warning(
                    "级联源 %r 已连续 %d 个交易日无有效数据, 本续传任务后续日期不再调用该源",
                    name, self.threshold,
                )


def run_source_stack(
    label: str,
    layers: list[tuple[str, Callable[[], int]]],
    *,
    retries: int = DEFAULT_RETRIES,
    success_if: Callable[[int], bool] | None = None,
    per_source_timeout_sec: float | None = None,
) -> tuple[str, int, list[tuple[str, int]]]:
    """依次尝试 ``layers`` 中 (源名, 可调用体). 对 **每个源** 在墙钟 `per_source_timeout_sec` 内可多次尝试
    (与 ``retries`` 及退避结合); 成功则返回 (源名, 写入行数, 尝试记录).

    尝试记录 ``attempts`` 为本轮按顺序 **实际执行过** 的 (源名, 回调返回值), 含首个 ``>0`` 的成功源.

    若**全部**数据源在各自时限内均未取得有效数据(含持续超时/始终 0 行), 打 ERROR 并返回 (``"none"``, 0, attempts),
    避免无限阻塞在单一坏源上.

    ``success_if`` 默认: ``>0`` 行视为该源成功.
    """
    attempts: list[tuple[str, int]] = []

    if per_source_timeout_sec is None:
        per_source_timeout_sec = float(
            getattr(
                settings.datacollect, "source_cascade_per_source_timeout_sec", 120.0,
            ),
        )

    def _ok(x: int) -> bool:
        if success_if is not None:
            return bool(success_if(x))
        return int(x) > 0

    if not layers:
        logger.error(
            "%s: 无可用数据源(级联列表为空), 无法拉取此类数据",
            label,
        )
        return "none", 0, attempts

    for src_name, fn in layers:
        source_deadline = time.perf_counter() + max(0.1, per_source_timeout_sec)
        last_out: int = 0
        got_int = False
        for attempt in range(1, retries + 1):
            remaining = source_deadline - time.perf_counter()
            if remaining <= 0:
                logger.warning(
                    "%s: 源=%s 已用尽本源 %.0f 秒预算, 换源",
                    label, src_name, per_source_timeout_sec,
                )
                break
            try:
                with ThreadPoolExecutor(max_workers=1) as ex:
                    fut = ex.submit(fn)
                    out = fut.result(timeout=remaining)
                if isinstance(out, bool):
                    last_out = 1 if out else 0
                else:
                    try:
                        last_out = int(out)
                    except (TypeError, ValueError):
                        last_out = 0
                got_int = True
            except FutureTimeoutError:
                logger.debug(
                    "%s: 源=%s 第 %d/%d 次调用超时(本段剩余约 %.1fs, 每源总预算 %.0fs)",
                    label, src_name, attempt, retries, remaining, per_source_timeout_sec,
                )
                if attempt < retries and time.perf_counter() < source_deadline:
                    time.sleep(
                        min(RETRY_BACKOFF * attempt, 2.0, max(0.0, source_deadline - time.perf_counter())),
                    )
                continue
            except Exception as e:  # noqa: BLE001
                logger.debug(
                    "%s: 源=%s 第 %d/%d 次异常: %s", label, src_name, attempt, retries, e,
                )
                if attempt < retries and time.perf_counter() < source_deadline:
                    time.sleep(
                        min(RETRY_BACKOFF * attempt, 2.0, max(0.0, source_deadline - time.perf_counter())),
                    )
                continue
            if _ok(last_out):
                attempts.append((src_name, last_out))
                logger.info(
                    "%s: 源=%s 第 %d 次 写入/命中=%r", label, src_name, attempt, last_out,
                )
                return src_name, last_out, attempts
            # 成功返回但 0 行: 非网络瞬态, 换源, 不重复重试
            break
        if not got_int:
            last_out = 0
        attempts.append((src_name, last_out))
        logger.warning("%s: 源=%s 无有效数据, 换源", label, src_name)

    logger.error(
        "%s: 已顺序尝试全部 %d 个数据源(各源单段墙钟约 %.0f 秒、同源最多 %d 次重试)仍未取得有效数据; "
        "当前系统无法从已配置源拉取本段数据, 级联结束",
        label, len(layers), per_source_timeout_sec, retries,
    )
    return "none", 0, attempts
