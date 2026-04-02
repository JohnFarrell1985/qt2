"""数据下载引擎 — 分批、限流、断点续传、重试

核心设计 (基于社区实测经验):
- download_history_data2 实际是异步执行, 需通过 callback 判断完成
- 每批不超过 500 只, 避免 MiniQMT 过载
- 批间暂停 2~3s 防限流
- incrementally=None 让 xtdata 自动增量 (本地有则续传, 无则全量)
- 单批失败自动重试, 不影响后续批次
- 按周期自动选择合理的默认数据范围
"""
import time
import threading
from datetime import datetime
from typing import List, Dict, Optional, Callable, Any
from dataclasses import dataclass, field

from src.common.logger import get_logger
from src.common.config import settings

logger = get_logger(__name__)

_dl_cfg = settings.download

PERIOD_DEFAULT_START: Dict[str, str] = {
    "1d": _dl_cfg.default_start_1d,
    "1w": _dl_cfg.default_start_1w,
    "1mon": _dl_cfg.default_start_1d,
    "1q": _dl_cfg.default_start_1d,
    "1hy": _dl_cfg.default_start_1d,
    "1y": _dl_cfg.default_start_1d,
    "5m": _dl_cfg.default_start_5m,
    "15m": _dl_cfg.default_start_15m,
    "30m": _dl_cfg.default_start_30m,
    "1h": _dl_cfg.default_start_1h,
    "1m": _dl_cfg.default_start_1m,
    "tick": _dl_cfg.default_start_tick,
}


@dataclass
class BatchResult:
    batch_index: int
    stock_count: int
    success: bool
    elapsed_sec: float
    error: str = ""
    finished_count: int = 0


@dataclass
class DownloadProgress:
    """全局下载进度追踪"""
    total_stocks: int = 0
    total_batches: int = 0
    finished_stocks: int = 0
    finished_batches: int = 0
    failed_batches: int = 0
    current_batch: int = 0
    batch_results: List[BatchResult] = field(default_factory=list)

    @property
    def pct(self) -> float:
        return (self.finished_stocks / self.total_stocks * 100) if self.total_stocks else 0.0


def get_default_start(period: str) -> str:
    """按周期获取合理的默认起始日期"""
    return PERIOD_DEFAULT_START.get(period, _dl_cfg.default_start_1d)


def split_batches(items: list, batch_size: int) -> List[list]:
    return [items[i: i + batch_size] for i in range(0, len(items), batch_size)]


class DownloadEngine:
    """分批下载引擎

    用法:
        engine = DownloadEngine(qmt_client)
        progress = engine.download_kline(stock_list, "1d")
        progress = engine.download_kline(stock_list, "1m")
        progress = engine.download_financial(stock_list, ["Balance", "Income"])
    """

    def __init__(self, client):
        self.client = client
        self.batch_size = _dl_cfg.batch_size
        self.batch_pause = _dl_cfg.batch_pause
        self.retry_count = _dl_cfg.retry_count
        self.retry_delay = _dl_cfg.retry_delay
        self.timeout = _dl_cfg.download_timeout

    # ================================================================
    # K线行情下载
    # ================================================================

    def download_kline(
        self,
        stock_list: List[str],
        period: str = "1d",
        start_time: str = "",
        end_time: str = "",
        incremental: bool = True,
        on_batch_done: Optional[Callable] = None,
    ) -> DownloadProgress:
        """分批下载K线历史数据

        Args:
            stock_list: QMT 格式代码列表
            period: K线周期
            start_time: 起始时间, 空则用周期默认值
            end_time: 结束时间, 空则用当天
            incremental: True=增量(续传), False=全量重下
            on_batch_done: 每批完成的回调 (BatchResult)
        """
        if not start_time:
            start_time = get_default_start(period)
        if not end_time:
            end_time = datetime.now().strftime("%Y%m%d")

        batches = split_batches(stock_list, self.batch_size)
        progress = DownloadProgress(
            total_stocks=len(stock_list),
            total_batches=len(batches),
        )

        logger.info(
            f"[下载引擎] K线下载启动: {len(stock_list)}只, period={period}, "
            f"{start_time}~{end_time}, {len(batches)}批 x {self.batch_size}"
        )

        for i, batch in enumerate(batches):
            progress.current_batch = i + 1
            result = self._download_one_batch_kline(
                batch, period, start_time, end_time, incremental, i + 1, len(batches),
            )
            progress.batch_results.append(result)
            progress.finished_batches += 1
            progress.finished_stocks += result.finished_count

            if result.success:
                logger.info(
                    f"[下载引擎] 批次 {i+1}/{len(batches)} 完成 "
                    f"({result.finished_count}只, {result.elapsed_sec:.1f}s)"
                )
            else:
                progress.failed_batches += 1
                logger.error(
                    f"[下载引擎] 批次 {i+1}/{len(batches)} 失败: {result.error}"
                )

            if on_batch_done:
                on_batch_done(result)

            if i < len(batches) - 1:
                logger.debug(f"[下载引擎] 批间暂停 {self.batch_pause}s...")
                time.sleep(self.batch_pause)

        logger.info(
            f"[下载引擎] K线下载完成: period={period}, "
            f"{progress.finished_stocks}/{progress.total_stocks}只, "
            f"失败{progress.failed_batches}批"
        )
        return progress

    def _download_one_batch_kline(
        self,
        batch: List[str],
        period: str,
        start_time: str,
        end_time: str,
        incremental: bool,
        batch_num: int,
        total_batches: int,
    ) -> BatchResult:
        """单批下载, 含重试"""
        incrementally = None if incremental else False
        t0 = time.time()

        for attempt in range(1, self.retry_count + 1):
            try:
                done_event = threading.Event()
                batch_finished = {"count": 0, "error": ""}

                def _callback(data):
                    batch_finished["count"] = data.get("finished", 0)
                    total = data.get("total", 0)
                    msg = data.get("message", "")
                    if msg:
                        batch_finished["error"] = msg
                    if total > 0 and batch_finished["count"] >= total:
                        done_event.set()

                self.client.download_history_data2(
                    stock_list=batch,
                    period=period,
                    start_time=start_time,
                    end_time=end_time,
                    callback=_callback,
                    incrementally=incrementally,
                )

                completed = done_event.wait(timeout=self.timeout)

                if not completed:
                    if batch_finished["count"] > 0:
                        logger.warning(
                            f"[下载引擎] 批次 {batch_num} 超时但已完成 "
                            f"{batch_finished['count']}/{len(batch)}只, 视为成功"
                        )
                        return BatchResult(
                            batch_index=batch_num,
                            stock_count=len(batch),
                            success=True,
                            elapsed_sec=time.time() - t0,
                            finished_count=batch_finished["count"],
                        )
                    raise TimeoutError(
                        f"批次 {batch_num} 下载超时 ({self.timeout}s), "
                        f"仅完成 {batch_finished['count']}/{len(batch)}"
                    )

                return BatchResult(
                    batch_index=batch_num,
                    stock_count=len(batch),
                    success=True,
                    elapsed_sec=time.time() - t0,
                    finished_count=batch_finished["count"],
                )

            except Exception as e:
                elapsed = time.time() - t0
                logger.warning(
                    f"[下载引擎] 批次 {batch_num} 第{attempt}次尝试失败 "
                    f"({elapsed:.1f}s): {e}"
                )
                if attempt < self.retry_count:
                    delay = self.retry_delay * attempt
                    logger.info(f"[下载引擎] {delay}s 后重试...")
                    time.sleep(delay)
                else:
                    return BatchResult(
                        batch_index=batch_num,
                        stock_count=len(batch),
                        success=False,
                        elapsed_sec=time.time() - t0,
                        error=str(e),
                        finished_count=batch_finished.get("count", 0),
                    )

        return BatchResult(
            batch_index=batch_num, stock_count=len(batch),
            success=False, elapsed_sec=time.time() - t0, error="unreachable",
        )

    # ================================================================
    # 财务数据下载
    # ================================================================

    def download_financial(
        self,
        stock_list: List[str],
        table_list: Optional[List[str]] = None,
        start_time: str = "",
        end_time: str = "",
        on_batch_done: Optional[Callable] = None,
    ) -> DownloadProgress:
        """分批下载财务数据"""
        if table_list is None:
            table_list = []
        if not end_time:
            end_time = datetime.now().strftime("%Y%m%d")

        batches = split_batches(stock_list, self.batch_size)
        progress = DownloadProgress(
            total_stocks=len(stock_list),
            total_batches=len(batches),
        )

        logger.info(
            f"[下载引擎] 财务数据下载: {len(stock_list)}只, "
            f"tables={table_list or '全部'}, {len(batches)}批"
        )

        for i, batch in enumerate(batches):
            progress.current_batch = i + 1
            result = self._download_one_batch_financial(
                batch, table_list, start_time, end_time, i + 1, len(batches),
            )
            progress.batch_results.append(result)
            progress.finished_batches += 1
            progress.finished_stocks += result.finished_count

            if not result.success:
                progress.failed_batches += 1

            if on_batch_done:
                on_batch_done(result)

            if i < len(batches) - 1:
                time.sleep(self.batch_pause)

        logger.info(
            f"[下载引擎] 财务下载完成: "
            f"{progress.finished_stocks}/{progress.total_stocks}只, "
            f"失败{progress.failed_batches}批"
        )
        return progress

    def _download_one_batch_financial(
        self,
        batch: List[str],
        table_list: List[str],
        start_time: str,
        end_time: str,
        batch_num: int,
        total_batches: int,
    ) -> BatchResult:
        t0 = time.time()

        for attempt in range(1, self.retry_count + 1):
            try:
                done_event = threading.Event()
                batch_finished = {"count": 0}

                def _callback(data):
                    batch_finished["count"] = data.get("finished", 0)
                    total = data.get("total", 0)
                    if total > 0 and batch_finished["count"] >= total:
                        done_event.set()

                self.client.download_financial_data2(
                    stock_list=batch,
                    table_list=table_list,
                    start_time=start_time,
                    end_time=end_time,
                    callback=_callback,
                )

                completed = done_event.wait(timeout=self.timeout)
                if not completed and batch_finished["count"] == 0:
                    raise TimeoutError(f"财务数据批次 {batch_num} 超时")

                return BatchResult(
                    batch_index=batch_num,
                    stock_count=len(batch),
                    success=True,
                    elapsed_sec=time.time() - t0,
                    finished_count=batch_finished["count"] or len(batch),
                )

            except Exception as e:
                logger.warning(
                    f"[下载引擎] 财务批次 {batch_num} 第{attempt}次失败: {e}"
                )
                if attempt < self.retry_count:
                    time.sleep(self.retry_delay * attempt)
                else:
                    return BatchResult(
                        batch_index=batch_num, stock_count=len(batch),
                        success=False, elapsed_sec=time.time() - t0,
                        error=str(e),
                    )

        return BatchResult(
            batch_index=batch_num, stock_count=len(batch),
            success=False, elapsed_sec=time.time() - t0, error="unreachable",
        )

    # ================================================================
    # 读取已下载数据 (分批读取, 避免内存爆炸)
    # ================================================================

    def get_local_kline_batched(
        self,
        stock_list: List[str],
        period: str = "1d",
        start_time: str = "",
        end_time: str = "",
        dividend_type: str = "front",
    ):
        """分批读取本地K线数据, 返回生成器 (code, DataFrame)

        避免一次性将5000只股票全部读入内存。
        """
        if not start_time:
            start_time = get_default_start(period)
        if not end_time:
            end_time = datetime.now().strftime("%Y%m%d")

        batches = split_batches(stock_list, self.batch_size)
        for batch in batches:
            try:
                data_dict = self.client.get_local_data(
                    stock_list=batch,
                    period=period,
                    start_time=start_time,
                    end_time=end_time,
                    dividend_type=dividend_type,
                )
                for code, df in data_dict.items():
                    if df is not None and not df.empty:
                        yield code, df
            except Exception as e:
                logger.warning(f"[下载引擎] 读取本地数据异常: {e}")
