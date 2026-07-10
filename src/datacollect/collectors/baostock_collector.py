"""BaoStock 数据采集器 — 免费、无限流、历史数据回溯到 1990 年

通过 BaseCollector 接口统一管理, 内置限流和错误处理。
baostock 仅在函数内部延迟导入, CI 环境无需安装该 SDK。

连接生命周期: 首次查询时自动 login, 之后复用会话;
查询失败时自动重置并重试一次; 可通过 close() 或 context manager 主动释放。
"""
from __future__ import annotations

import time
from datetime import datetime

from src.common.config import settings
from src.common.logger import get_logger
from src.datacollect.base import BaseCollector, CollectResult, CollectTask
from src.datacollect.rate_limiter import TokenBucketLimiter

logger = get_logger(__name__)

_CFG = settings.datacollect


class BaostockCollector(BaseCollector):
    """基于 baostock 的 A 股数据采集器。

    特点:
    - 免费, 无需注册、无需 Token
    - 历史数据回溯到 1990 年, 财务数据 2007 年起
    - 会话复用: login 一次, 多次查询, 最终 close() 释放
    - 股票代码格式: "sh.600000" / "sz.000001"
    """

    SOURCE = "baostock"

    def __init__(self, limiter: TokenBucketLimiter | None = None):
        if limiter is None:
            limiter = TokenBucketLimiter.for_domain(
                "baostock",
                rate=_CFG.baostock_rate,
                burst=_CFG.baostock_burst,
            )
        super().__init__(limiter)
        self._logged_in: bool = False
        self._bs = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def _ensure_login(self):
        """确保 baostock 会话已登录 (延迟导入 + 单次 login)。

        Returns:
            baostock 模块引用 (已 login)

        Raises:
            RuntimeError: baostock 不可用或登录失败
        """
        if self._logged_in and self._bs is not None:
            return self._bs

        try:
            import baostock as bs
        except ImportError:
            raise RuntimeError("baostock 未安装, 无法进行数据采集")

        lg = bs.login()
        if lg.error_code != "0":
            raise RuntimeError(f"baostock login 失败: {lg.error_msg}")

        self._bs = bs
        self._logged_in = True
        logger.debug("baostock 会话已建立")
        return bs

    def close(self) -> None:
        """主动释放 baostock 会话。"""
        if self._logged_in and self._bs is not None:
            try:
                self._bs.logout()
                logger.debug("baostock 会话已释放")
            except Exception as e:
                logger.warning("baostock logout 异常: %s", e)
            finally:
                self._logged_in = False
                self._bs = None

    def _reset_connection(self) -> None:
        """重置连接状态, 用于查询失败后重连。"""
        if self._bs is not None:
            try:
                self._bs.logout()
            except Exception:
                pass
        self._logged_in = False
        self._bs = None

    @staticmethod
    def _to_dataframe(rs):
        """将 baostock ResultData 转为 DataFrame。"""
        import pandas as pd

        data_list: list[list] = []
        while (rs.error_code == "0") and rs.next():
            data_list.append(rs.get_row_data())
        return pd.DataFrame(data_list, columns=rs.fields)

    def _query_with_retry(self, query_fn, *args, **kwargs):
        """执行查询, 连接错误时重置并重试一次。"""
        try:
            return query_fn(*args, **kwargs)
        except (ConnectionError, OSError, RuntimeError) as e:
            logger.warning("baostock 查询失败, 尝试重连: %s", e)
            self._reset_connection()
            self._ensure_login()
            return query_fn(*args, **kwargs)

    def query_history_k_data(
        self,
        code: str,
        start_date: str,
        end_date: str,
        frequency: str = "d",
        adjustflag: str = "2",
    ):
        """查询历史 K 线数据。

        Args:
            code: 股票代码 "sh.600000" 或 "sz.000001"
            start_date: 开始日期 "2023-01-01"
            end_date: 结束日期 "2026-04-01"
            frequency: "d"=日线, "w"=周线, "m"=月线,
                       "5"=5分钟, "15"=15分钟, "30"=30分钟, "60"=60分钟
            adjustflag: "1"=后复权, "2"=前复权, "3"=不复权
        """
        if self._limiter:
            self._limiter.acquire()

        self._ensure_login()

        def _do_query():
            fields = "date,code,open,high,low,close,volume,amount,adjustflag"
            if frequency == "d":
                fields += ",turn,pctChg"

            rs = self._bs.query_history_k_data_plus(
                code,
                fields,
                start_date=start_date,
                end_date=end_date,
                frequency=frequency,
                adjustflag=adjustflag,
            )
            if rs.error_code != "0":
                raise RuntimeError(
                    f"query_history_k_data_plus 失败: {rs.error_msg}"
                )
            return self._to_dataframe(rs)

        df = self._query_with_retry(_do_query)
        logger.debug(
            "baostock K线查询完成: %s %s~%s (%d 行)",
            code, start_date, end_date, len(df),
        )
        return df

    def query_stock_basic(self):
        """查询股票基础信息列表。"""
        if self._limiter:
            self._limiter.acquire()

        self._ensure_login()

        def _do_query():
            rs = self._bs.query_stock_basic()
            if rs.error_code != "0":
                raise RuntimeError(
                    f"query_stock_basic 失败: {rs.error_msg}"
                )
            return self._to_dataframe(rs)

        df = self._query_with_retry(_do_query)
        logger.debug("baostock 基础信息查询完成 (%d 行)", len(df))
        return df

    def stock_list(self):
        """兼容 FallbackDispatcher 的 func_name=stock_list."""
        return self.query_stock_basic()

    def query_profit_data(self, code: str, year: int, quarter: int):
        """查询季度盈利能力数据。

        Args:
            code: 股票代码 "sh.600000"
            year: 年份 (如 2024)
            quarter: 季度 1-4
        """
        if self._limiter:
            self._limiter.acquire()

        self._ensure_login()

        def _do_query():
            rs = self._bs.query_profit_data(code=code, year=year, quarter=quarter)
            if rs.error_code != "0":
                raise RuntimeError(
                    f"query_profit_data 失败: {rs.error_msg}"
                )
            return self._to_dataframe(rs)

        df = self._query_with_retry(_do_query)
        logger.debug(
            "baostock 盈利能力查询: %s %dQ%d (%d 行)",
            code, year, quarter, len(df),
        )
        return df

    def query_growth_data(self, code: str, year: int, quarter: int):
        """查询季度成长能力数据。

        Args:
            code: 股票代码 "sh.600000"
            year: 年份 (如 2024)
            quarter: 季度 1-4
        """
        if self._limiter:
            self._limiter.acquire()

        self._ensure_login()

        def _do_query():
            rs = self._bs.query_growth_data(code=code, year=year, quarter=quarter)
            if rs.error_code != "0":
                raise RuntimeError(
                    f"query_growth_data 失败: {rs.error_msg}"
                )
            return self._to_dataframe(rs)

        df = self._query_with_retry(_do_query)
        logger.debug(
            "baostock 成长能力查询: %s %dQ%d (%d 行)",
            code, year, quarter, len(df),
        )
        return df

    def query_balance_data(self, code: str, year: int, quarter: int):
        """查询季度偿债能力数据。

        Args:
            code: 股票代码 "sh.600000"
            year: 年份 (如 2024)
            quarter: 季度 1-4
        """
        if self._limiter:
            self._limiter.acquire()

        self._ensure_login()

        def _do_query():
            rs = self._bs.query_balance_data(code=code, year=year, quarter=quarter)
            if rs.error_code != "0":
                raise RuntimeError(
                    f"query_balance_data 失败: {rs.error_msg}"
                )
            return self._to_dataframe(rs)

        df = self._query_with_retry(_do_query)
        logger.debug(
            "baostock 偿债能力查询: %s %dQ%d (%d 行)",
            code, year, quarter, len(df),
        )
        return df

    def collect(self, task: CollectTask) -> CollectResult:
        """执行采集任务 — 从 task.params 读取 func_name 和参数。

        task.params 结构:
            - func_name (str): 方法名 (必需, 如 "query_history_k_data")
            - 其余键值对作为方法参数传入
        """
        params = dict(task.params)
        func_name = params.pop("func_name", "")
        if not func_name:
            raise ValueError("task.params 缺少必需字段 'func_name'")

        fn = getattr(self, func_name, None)
        if fn is None or func_name.startswith("_"):
            raise AttributeError(
                f"BaostockCollector 没有公开方法: {func_name}"
            )

        t0 = time.monotonic()
        data = fn(**params)
        elapsed_ms = (time.monotonic() - t0) * 1000

        records = len(data) if hasattr(data, "__len__") else 0
        return CollectResult(
            source=self.SOURCE,
            data=data,
            collected_at=datetime.now(),
            metadata={
                "task_id": task.task_id,
                "func_name": func_name,
                "params": params,
                "records_count": records,
                "elapsed_ms": round(elapsed_ms, 1),
            },
        )

    def health_check(self) -> bool:
        """尝试 login 验证 baostock 可用性。"""
        try:
            self._ensure_login()
            return True
        except Exception as e:
            logger.warning("baostock 健康检查失败: %s", e)
            return False
