"""通过 akshare 采集 ETF / 财务报表 / 财务指标数据

独立于 QMT 的数据补充通道, 使用 akshare 公开接口采集:
- A12: ETF 列表 + ETF 日线行情
- A13: 财务报表 (利润/资产负债/现金流摘要)
- A14: 财务分析指标 (每股/盈利/偿债/成长)

所有 akshare 调用均受 TokenBucketLimiter 限流保护。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd
from sqlalchemy.dialects.postgresql import insert

from src.common.config import settings
from src.common.db import get_session
from src.common.logger import get_logger
from src.data.models import (
    ETFDaily,
    ETFInfo,
    Stock,
    StockFinancialIndicator,
    StockFinancialReport,
)
from src.datacollect.rate_limiter import TokenBucketLimiter

logger = get_logger(__name__)

_CFG = settings.datacollect


def _safe_float(v: Any) -> float | None:
    """安全转换为 float, 失败返回 None。"""
    try:
        if v is not None and not pd.isna(v):
            return float(v)
    except (TypeError, ValueError):
        pass
    return None


def _safe_date(v: Any) -> Any:
    """安全转换为 date 对象, 失败返回 None。"""
    try:
        if v is not None and not pd.isna(v):
            return pd.Timestamp(v).date()
    except Exception:
        pass
    return None


class AkshareFinancialSync:
    """通过 akshare 采集 ETF / 财务报表 / 财务指标数据"""

    def __init__(self, limiter: TokenBucketLimiter | None = None):
        self._limiter = limiter or TokenBucketLimiter.for_domain(
            "akshare",
            rate=_CFG.akshare_rate,
            burst=_CFG.akshare_burst,
        )

    def _call_ak(self, func_name: str, **kwargs: Any) -> pd.DataFrame:
        """调用 akshare 函数, 带限流控制。"""
        import akshare as ak

        fn = getattr(ak, func_name, None)
        if fn is None:
            raise AttributeError(f"akshare 没有函数: {func_name}")

        self._limiter.acquire()
        return fn(**kwargs)

    # ------------------------------------------------------------------
    # A12: ETF 列表 + ETF 日线
    # ------------------------------------------------------------------

    def sync_etf_list(self) -> int:
        """从 akshare fund_etf_spot_em 获取 ETF 列表, upsert 到 etf_info 表。"""
        logger.info("开始同步 ETF 列表...")
        try:
            df = self._call_ak("fund_etf_spot_em")
        except Exception as e:
            logger.error("获取 ETF 列表失败: %s", e)
            return 0

        if df is None or df.empty:
            logger.warning("ETF 列表为空")
            return 0

        records: list[dict] = []
        for _, row in df.iterrows():
            raw_code = str(row.get("代码", ""))
            if not raw_code:
                continue
            suffix = ".SH" if raw_code.startswith(("51", "56", "58")) else ".SZ"
            record: dict[str, Any] = {
                "code": raw_code + suffix,
                "name": str(row.get("名称", "")),
                "updated_at": datetime.now(),
            }
            records.append(record)

        if not records:
            logger.warning("ETF 列表解析后无有效记录")
            return 0

        total = 0
        with get_session() as session:
            for batch_start in range(0, len(records), 500):
                batch = records[batch_start:batch_start + 500]
                for rec in batch:
                    stmt = insert(ETFInfo).values(**rec)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["code"],
                        set_={k: v for k, v in rec.items() if k != "code"},
                    )
                    session.execute(stmt)
                    total += 1

        logger.info("ETF 列表同步完成, 共 %d 条", total)
        return total

    def sync_etf_daily(self, start_date: str = "20230101") -> int:
        """为 etf_info 中的每只 ETF 采集日线行情, upsert 到 etf_daily 表。

        Args:
            start_date: 起始日期, 格式 YYYYMMDD
        """
        end_date = datetime.now().strftime("%Y%m%d")
        logger.info("开始同步 ETF 日线 (%s ~ %s)...", start_date, end_date)

        with get_session() as session:
            etf_codes = [
                row[0] for row in session.query(ETFInfo.code).all()
            ]

        if not etf_codes:
            logger.warning("etf_info 表为空, 请先执行 sync_etf_list")
            return 0

        total = 0
        failed = 0
        for i, full_code in enumerate(etf_codes):
            symbol = full_code.split(".")[0]
            try:
                df = self._call_ak(
                    "fund_etf_hist_em",
                    symbol=symbol,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust="qfq",
                )
            except Exception as e:
                logger.warning("ETF %s 日线获取失败: %s", full_code, e)
                failed += 1
                continue

            if df is None or df.empty:
                continue

            records = self._map_etf_daily(df, full_code)
            if not records:
                continue

            with get_session() as session:
                for rec in records:
                    stmt = insert(ETFDaily).values(**rec)
                    stmt = stmt.on_conflict_do_update(
                        constraint="idx_etf_code_date",
                        set_={k: v for k, v in rec.items() if k not in ("code", "trade_date")},
                    )
                    session.execute(stmt)
                total += len(records)

            if (i + 1) % 50 == 0:
                logger.info("ETF 日线进度: %d/%d (累计 %d 条)", i + 1, len(etf_codes), total)

        logger.info("ETF 日线同步完成: %d 条, 失败 %d 只", total, failed)
        return total

    @staticmethod
    def _map_etf_daily(df: pd.DataFrame, code: str) -> list[dict]:
        """将 akshare fund_etf_hist_em 返回的 DataFrame 映射为 ETFDaily 记录。"""
        col_map = {
            "日期": "trade_date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
        }
        records: list[dict] = []
        for _, row in df.iterrows():
            trade_date = _safe_date(row.get("日期"))
            if trade_date is None:
                continue
            rec: dict[str, Any] = {"code": code, "trade_date": trade_date}
            for cn_col, db_col in col_map.items():
                if db_col == "trade_date":
                    continue
                if db_col == "volume":
                    val = row.get(cn_col)
                    rec[db_col] = int(val) if val is not None and not pd.isna(val) else None
                else:
                    rec[db_col] = _safe_float(row.get(cn_col))
            records.append(rec)
        return records

    # ------------------------------------------------------------------
    # A13: 财务报表
    # ------------------------------------------------------------------

    def sync_financial_report(
        self,
        stock_codes: list[str] | None = None,
        report_types: list[str] | None = None,
    ) -> int:
        """通过 akshare stock_financial_abstract_ths 采集财务摘要, upsert 到 stock_financial_report。

        Args:
            stock_codes: 股票代码列表 (6位纯数字或带后缀)。为 None 时从 stocks 表读取全部。
            report_types: 保留参数, 当前实现使用统一的财务摘要接口。
        """
        codes = self._resolve_stock_codes(stock_codes)
        if not codes:
            logger.warning("无可用股票代码")
            return 0

        logger.info("开始同步财务报表, 共 %d 只股票...", len(codes))
        total = 0
        failed = 0

        for i, code in enumerate(codes):
            symbol = code.split(".")[0]
            try:
                df = self._call_ak(
                    "stock_financial_abstract_ths",
                    symbol=symbol,
                    indicator="按报告期",
                )
            except Exception as e:
                logger.warning("股票 %s 财务摘要获取失败: %s", code, e)
                failed += 1
                continue

            if df is None or df.empty:
                continue

            records = self._map_financial_report(df, symbol)
            if not records:
                continue

            with get_session() as session:
                for rec in records:
                    stmt = insert(StockFinancialReport).values(**rec)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["code", "report_type", "report_period"],
                        set_={
                            k: v for k, v in rec.items()
                            if k not in ("code", "report_type", "report_period", "id")
                        },
                    )
                    session.execute(stmt)
                total += len(records)

            if (i + 1) % 50 == 0:
                logger.info("财务报表进度: %d/%d (累计 %d 条)", i + 1, len(codes), total)

        logger.info("财务报表同步完成: %d 条, 失败 %d 只", total, failed)
        return total

    @staticmethod
    def _map_financial_report(df: pd.DataFrame, code: str) -> list[dict]:
        """将 stock_financial_abstract_ths 返回数据映射到 StockFinancialReport 字段。"""
        col_map = {
            "营业总收入": "total_revenue",
            "营业利润": "operating_profit",
            "净利润": "net_profit",
            "总资产": "total_assets",
            "总负债": "total_liabilities",
            "股东权益": "total_equity",
            "经营活动产生的现金流量净额": "operating_cash_flow",
            "毛利率": "gross_margin",
            "净利率": "net_margin",
            "净资产收益率": "roe",
            "资产负债率": "debt_ratio",
            "流动比率": "current_ratio",
            "速动比率": "quick_ratio",
        }

        records: list[dict] = []
        for _, row in df.iterrows():
            report_date_raw = row.get("报告期") or row.get("日期")
            report_date = _safe_date(report_date_raw)
            if report_date is None:
                continue

            period_str = report_date.strftime("%Y%m%d")
            rec: dict[str, Any] = {
                "code": code,
                "report_type": "combined",
                "report_period": period_str,
                "report_date": report_date,
                "updated_at": datetime.now(),
            }
            for cn_col, db_col in col_map.items():
                if cn_col in df.columns:
                    rec[db_col] = _safe_float(row.get(cn_col))
            records.append(rec)
        return records

    # ------------------------------------------------------------------
    # A14: 财务分析指标
    # ------------------------------------------------------------------

    def sync_financial_indicator(
        self,
        stock_codes: list[str] | None = None,
        start_year: str = "2023",
    ) -> int:
        """通过 akshare stock_financial_analysis_indicator 采集财务指标, upsert 到 stock_financial_indicator。

        Args:
            stock_codes: 股票代码列表。为 None 时从 stocks 表读取全部。
            start_year: 起始年份
        """
        codes = self._resolve_stock_codes(stock_codes)
        if not codes:
            logger.warning("无可用股票代码")
            return 0

        logger.info("开始同步财务指标, 共 %d 只股票...", len(codes))
        total = 0
        failed = 0

        for i, code in enumerate(codes):
            symbol = code.split(".")[0]
            try:
                df = self._call_ak(
                    "stock_financial_analysis_indicator",
                    symbol=symbol,
                    start_year=start_year,
                )
            except Exception as e:
                logger.warning("股票 %s 财务指标获取失败: %s", code, e)
                failed += 1
                continue

            if df is None or df.empty:
                continue

            records = self._map_financial_indicator(df, symbol)
            if not records:
                continue

            with get_session() as session:
                for rec in records:
                    stmt = insert(StockFinancialIndicator).values(**rec)
                    stmt = stmt.on_conflict_do_update(
                        index_elements=["code", "report_date"],
                        set_={
                            k: v for k, v in rec.items()
                            if k not in ("code", "report_date", "id")
                        },
                    )
                    session.execute(stmt)
                total += len(records)

            if (i + 1) % 50 == 0:
                logger.info("财务指标进度: %d/%d (累计 %d 条)", i + 1, len(codes), total)

        logger.info("财务指标同步完成: %d 条, 失败 %d 只", total, failed)
        return total

    @staticmethod
    def _map_financial_indicator(df: pd.DataFrame, code: str) -> list[dict]:
        """将 stock_financial_analysis_indicator 返回数据映射到 StockFinancialIndicator 字段。"""
        col_map = {
            "基本每股收益": "eps_basic",
            "每股净资产": "bps",
            "加权净资产收益率": "roe_weighted",
            "摊薄净资产收益率": "roe_diluted",
            "资产负债率": "debt_asset_ratio",
            "流动比率": "current_ratio",
            "速动比率": "quick_ratio",
            "营业总收入同比增长率": "revenue_growth",
            "净利润同比增长率": "profit_growth",
            "每股经营现金流量": "cfps",
            "每股股利": "dps",
            "毛利率": "gross_profit_margin",
            "净利率": "net_profit_margin",
            "总资产周转率": "total_asset_turnover",
            "存货周转率": "inventory_turnover",
            "应收账款周转率": "receivable_turnover",
        }

        records: list[dict] = []
        for _, row in df.iterrows():
            date_raw = row.get("日期") or row.get("报告期")
            report_date = _safe_date(date_raw)
            if report_date is None:
                continue

            rec: dict[str, Any] = {
                "code": code,
                "report_date": report_date,
                "updated_at": datetime.now(),
            }
            for cn_col, db_col in col_map.items():
                if cn_col in df.columns:
                    rec[db_col] = _safe_float(row.get(cn_col))
            records.append(rec)
        return records

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_stock_codes(stock_codes: list[str] | None) -> list[str]:
        """解析股票代码列表: 传入为 None 时从 stocks 表读取全部。"""
        if stock_codes:
            return [c.split(".")[0] if "." in c else c for c in stock_codes]
        with get_session() as session:
            rows = session.query(Stock.code).all()
        return [row[0] for row in rows]


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="akshare 财务/ETF 数据采集")
    parser.add_argument(
        "action",
        choices=["etf_list", "etf_daily", "report", "indicator", "all"],
        help="采集动作",
    )
    parser.add_argument("--start-date", default="20230101", help="ETF 日线起始日期")
    parser.add_argument("--start-year", default="2023", help="财务指标起始年份")
    parser.add_argument("--codes", nargs="*", help="股票代码列表 (仅 report/indicator)")
    args = parser.parse_args()

    syncer = AkshareFinancialSync()

    if args.action in ("etf_list", "all"):
        syncer.sync_etf_list()
    if args.action in ("etf_daily", "all"):
        syncer.sync_etf_daily(start_date=args.start_date)
    if args.action in ("report", "all"):
        syncer.sync_financial_report(stock_codes=args.codes)
    if args.action in ("indicator", "all"):
        syncer.sync_financial_indicator(
            stock_codes=args.codes, start_year=args.start_year,
        )
