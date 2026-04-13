"""板块行情数据采集 (A15)

数据来源: akshare
  - stock_board_industry_name_em        → 行业板块名称列表
  - stock_board_industry_hist_em        → 板块历史日 K
  - stock_sector_fund_flow_rank         → 板块资金流向排名

所有 akshare 调用均延迟导入、限流、try/except 包裹。
"""
from datetime import datetime, date

from sqlalchemy.dialects.postgresql import insert

from src.common.config import settings
from src.common.db import get_session
from src.common.logger import get_logger
from src.datacollect.rate_limiter import TokenBucketLimiter

logger = get_logger(__name__)


def _get_limiter() -> TokenBucketLimiter:
    return TokenBucketLimiter.for_domain(
        "akshare",
        rate=settings.datacollect.akshare_rate,
        burst=settings.datacollect.akshare_burst,
    )


class SectorMarketSync:
    """板块行情数据采集 — 通过 akshare 获取行业板块涨跌幅和资金流向"""

    def sync_sector_data(self, start_date: str = "20230101") -> int:
        """采集行业板块历史行情 + 当日资金流向, UPSERT 至 sector_data.

        Args:
            start_date: 历史数据起始日期, 格式 YYYYMMDD

        Returns:
            入库记录数
        """
        import akshare as ak

        limiter = _get_limiter()
        end_date = datetime.now().strftime("%Y%m%d")
        total = 0

        total += self._sync_sector_hist(ak, limiter, start_date, end_date)
        total += self._sync_sector_fund_flow(ak, limiter)

        logger.info("板块行情同步完成, 共 UPSERT %d 条", total)
        return total

    # ------------------------------------------------------------------
    # 历史日 K
    # ------------------------------------------------------------------
    def _sync_sector_hist(self, ak, limiter: TokenBucketLimiter,
                          start_date: str, end_date: str) -> int:
        sector_names = self._fetch_sector_names(ak, limiter)
        if not sector_names:
            return 0

        count = 0
        for idx, name in enumerate(sector_names):
            try:
                limiter.acquire()
                df = ak.stock_board_industry_hist_em(
                    symbol=name,
                    start_date=start_date,
                    end_date=end_date,
                    period="日k",
                    adjust="",
                )
                if df is None or df.empty:
                    continue

                rows = self._map_hist_rows(name, df)
                if rows:
                    self._bulk_upsert(rows)
                    count += len(rows)

                if (idx + 1) % 50 == 0:
                    logger.info("板块历史行情进度: %d/%d", idx + 1, len(sector_names))
            except Exception as e:
                logger.warning("获取板块 %s 历史行情失败: %s", name, e)

        logger.info("板块历史行情入库 %d 条 (共 %d 个板块)", count, len(sector_names))
        return count

    @staticmethod
    def _fetch_sector_names(ak, limiter: TokenBucketLimiter) -> list[str]:
        try:
            limiter.acquire()
            df = ak.stock_board_industry_name_em()
            if df is None or df.empty:
                logger.warning("获取行业板块名称列表为空")
                return []
            col = "板块名称"
            if col not in df.columns:
                col = df.columns[0]
            names = df[col].dropna().unique().tolist()
            logger.info("获取到 %d 个行业板块", len(names))
            return names
        except Exception as e:
            logger.error("获取行业板块列表失败: %s", e)
            return []

    @staticmethod
    def _map_hist_rows(sector_name: str, df) -> list[dict]:
        rows: list[dict] = []
        for _, row in df.iterrows():
            raw_date = row.get("日期")
            if raw_date is None:
                continue
            try:
                if isinstance(raw_date, str):
                    td = datetime.strptime(raw_date[:10], "%Y-%m-%d").date()
                elif isinstance(raw_date, (date, datetime)):
                    td = raw_date if isinstance(raw_date, date) else raw_date.date()
                else:
                    import pandas as pd
                    td = pd.Timestamp(raw_date).date()
            except Exception:
                continue

            rows.append({
                "sector_name": sector_name,
                "trade_date": td,
                "change_pct": _safe_float(row, "涨跌幅"),
            })
        return rows

    # ------------------------------------------------------------------
    # 当日资金流向
    # ------------------------------------------------------------------
    def _sync_sector_fund_flow(self, ak, limiter: TokenBucketLimiter) -> int:
        try:
            limiter.acquire()
            df = ak.stock_sector_fund_flow_rank(indicator="今日")
        except Exception as e:
            logger.warning("获取板块资金流向失败: %s", e)
            return 0

        if df is None or df.empty:
            return 0

        today = date.today()
        rows: list[dict] = []
        for _, row in df.iterrows():
            name = row.get("名称") or row.get("行业")
            if not name:
                continue
            rows.append({
                "sector_name": str(name),
                "trade_date": today,
                "change_pct": _safe_float(row, "今日涨跌幅"),
                "net_inflow": _safe_float(row, "今日主力净流入-净额", scale=1e-8),
                "leading_stock": _safe_str(row, "今日领涨股"),
            })

        if rows:
            self._bulk_upsert(rows)
        logger.info("板块资金流向入库 %d 条", len(rows))
        return len(rows)

    # ------------------------------------------------------------------
    # DB
    # ------------------------------------------------------------------
    @staticmethod
    def _bulk_upsert(rows: list[dict], batch_size: int = 500) -> None:
        from src.data.models import SectorData

        with get_session() as session:
            for i in range(0, len(rows), batch_size):
                batch = rows[i: i + batch_size]
                stmt = insert(SectorData).values(batch)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["sector_name", "trade_date"],
                    set_={
                        "change_pct": stmt.excluded.change_pct,
                        "net_inflow": stmt.excluded.net_inflow,
                        "leading_stock": stmt.excluded.leading_stock,
                    },
                )
                session.execute(stmt)


# ====================================================================
# 工具
# ====================================================================

def _safe_float(row, col: str, scale: float = 1.0):
    try:
        v = row.get(col)
        if v is not None:
            import pandas as pd
            if not pd.isna(v):
                return float(v) * scale
    except Exception:
        pass
    return None


def _safe_str(row, col: str) -> str | None:
    try:
        v = row.get(col)
        if v is not None:
            import pandas as pd
            if not pd.isna(v):
                return str(v)
    except Exception:
        pass
    return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="板块行情数据采集 (akshare)")
    parser.add_argument(
        "action",
        choices=["all", "hist", "fund_flow"],
        help="all=历史K+资金流, hist=仅历史日K, fund_flow=仅当日资金流向",
    )
    parser.add_argument("--start-date", default="20250401", help="历史数据起始日期 (默认 20250401)")
    args = parser.parse_args()

    sync = SectorMarketSync()

    if args.action == "fund_flow":
        import akshare as ak

        limiter = _get_limiter()
        n = sync._sync_sector_fund_flow(ak, limiter)
        print(f"板块资金流向同步完成: {n} 条")  # noqa: T201
    elif args.action == "hist":
        import akshare as ak

        limiter = _get_limiter()
        n = sync._sync_sector_hist(ak, limiter, args.start_date, datetime.now().strftime("%Y%m%d"))
        print(f"板块历史K线同步完成: {n} 条")  # noqa: T201
    else:
        n = sync.sync_sector_data(start_date=args.start_date)
        print(f"板块行情全量同步完成: {n} 条")  # noqa: T201
