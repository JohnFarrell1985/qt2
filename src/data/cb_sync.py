"""可转债数据采集 — akshare 数据源 (A16)

数据来源: akshare
  - bond_cb_jsl              → 集思录可转债列表 (基础信息)
  - bond_zh_hs_cov_daily     → 可转债日线行情

与 src/data/cb_data.py (QMT 数据源) 互补, 本模块面向无 QMT 环境的场景。
"""
from datetime import datetime, date

from sqlalchemy.dialects.postgresql import insert

from src.common.config import settings
from src.common.db import get_session
from src.common.db_batch import DEFAULT_TABLE_UPSERT_FLUSH, log_upsert_commit
from src.common.logger import get_logger
from src.data.models import ConvertibleBond, CBDaily
from src.datacollect.rate_limiter import TokenBucketLimiter

logger = get_logger(__name__)


def _get_limiter() -> TokenBucketLimiter:
    return TokenBucketLimiter.for_domain(
        "akshare",
        rate=settings.datacollect.akshare_rate,
        burst=settings.datacollect.akshare_burst,
    )


class CBDataSync:
    """可转债数据采集"""

    def sync_cb_list(self) -> int:
        """从集思录获取可转债列表, UPSERT 至 convertible_bond.

        Returns:
            入库记录数
        """
        import akshare as ak

        limiter = _get_limiter()

        try:
            limiter.acquire()
            df = ak.bond_cb_jsl()
        except Exception as e:
            logger.error("获取集思录可转债列表失败: %s", e)
            return 0

        if df is None or df.empty:
            logger.warning("集思录可转债列表为空")
            return 0

        rows = self._map_cb_list(df)
        if not rows:
            return 0

        self._bulk_upsert_cb(rows)
        logger.info("可转债列表同步完成: %d 只", len(rows))
        return len(rows)

    def sync_cb_daily(self, start_date: str = "20230101") -> int:
        """采集可转债日线行情, UPSERT 至 cb_daily.

        逐只从 akshare 获取, 限流保护, 带批量进度日志。

        Args:
            start_date: 起始日期, 格式 YYYYMMDD

        Returns:
            入库记录数
        """
        import akshare as ak

        limiter = _get_limiter()

        cb_codes = self._load_cb_codes()
        if not cb_codes:
            logger.warning("convertible_bond 表为空, 请先执行 sync_cb_list")
            return 0

        total = 0
        for idx, code in enumerate(cb_codes):
            try:
                code_6 = code.split(".")[0] if "." in code else code
                if len(code_6) != 6:
                    continue

                limiter.acquire()
                df = ak.bond_zh_hs_cov_daily(symbol=code_6)
                if df is None or df.empty:
                    continue

                rows = self._map_cb_daily(code, df, start_date)
                if rows:
                    self._bulk_upsert_cb_daily(rows)
                    total += len(rows)

                if (idx + 1) % 50 == 0:
                    logger.info("可转债日线进度: %d/%d, 累计 %d 条",
                                idx + 1, len(cb_codes), total)
            except Exception as e:
                logger.warning("获取可转债 %s 日线失败: %s", code, e)

        logger.info("可转债日线同步完成: %d 条 (共 %d 只)", total, len(cb_codes))
        return total

    # ------------------------------------------------------------------
    # 字段映射
    # ------------------------------------------------------------------
    @staticmethod
    def _map_cb_list(df) -> list[dict]:
        col_map = {
            "转债代码": "code",
            "转债名称": "bond_name",
            "正股代码": "stock_code",
            "转股价": "convert_price",
            "评级": "level",
            "剩余规模": "remain_amount",
        }

        available = {k: v for k, v in col_map.items() if k in df.columns}
        if "转债代码" not in available:
            for c in df.columns:
                if "代码" in c:
                    available[c] = "code"
                    break
            else:
                logger.error("无法定位转债代码列, 可用列: %s", list(df.columns))
                return []

        rows: list[dict] = []
        for _, row in df.iterrows():
            rec: dict = {}
            for src, dst in available.items():
                rec[dst] = _clean_value(row.get(src))
            code = rec.get("code")
            if not code:
                continue
            rec["code"] = str(code)
            if rec.get("convert_price") is not None:
                rec["convert_price"] = _to_float(rec["convert_price"])
            if rec.get("remain_amount") is not None:
                rec["remain_amount"] = _to_float(rec["remain_amount"])
            rows.append(rec)
        return rows

    @staticmethod
    def _map_cb_daily(code: str, df, start_date: str) -> list[dict]:
        start_dt = datetime.strptime(start_date, "%Y%m%d").date() if start_date else None
        rows: list[dict] = []

        for _, row in df.iterrows():
            raw_date = row.get("date") or row.get("日期")
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

            if start_dt and td < start_dt:
                continue

            rows.append({
                "code": code,
                "trade_date": td,
                "open": _to_float(row.get("open")),
                "high": _to_float(row.get("high")),
                "low": _to_float(row.get("low")),
                "close": _to_float(row.get("close")),
                "volume": _to_int(row.get("volume")),
            })
        return rows

    # ------------------------------------------------------------------
    # DB
    # ------------------------------------------------------------------
    @staticmethod
    def _load_cb_codes() -> list[str]:
        with get_session() as session:
            results = session.query(ConvertibleBond.code).all()
            return [r[0] for r in results]

    @staticmethod
    def _bulk_upsert_cb(
        rows: list[dict], batch_size: int = DEFAULT_TABLE_UPSERT_FLUSH,
    ) -> None:
        for i in range(0, len(rows), batch_size):
            batch = rows[i: i + batch_size]
            with get_session() as session:
                stmt = insert(ConvertibleBond).values(batch)
                stmt = stmt.on_conflict_do_update(
                    index_elements=["code"],
                    set_={
                        "bond_name": stmt.excluded.bond_name,
                        "stock_code": stmt.excluded.stock_code,
                        "convert_price": stmt.excluded.convert_price,
                        "level": stmt.excluded.level,
                        "remain_amount": stmt.excluded.remain_amount,
                    },
                )
                session.execute(stmt)
            log_upsert_commit("akshare.convertible_bond", len(batch))

    @staticmethod
    def _bulk_upsert_cb_daily(
        rows: list[dict], batch_size: int = DEFAULT_TABLE_UPSERT_FLUSH,
    ) -> None:
        for i in range(0, len(rows), batch_size):
            batch = rows[i: i + batch_size]
            with get_session() as session:
                stmt = insert(CBDaily).values(batch)
                stmt = stmt.on_conflict_do_update(
                    constraint="idx_cbd_code_date",
                    set_={
                        "open": stmt.excluded.open,
                        "high": stmt.excluded.high,
                        "low": stmt.excluded.low,
                        "close": stmt.excluded.close,
                        "volume": stmt.excluded.volume,
                    },
                )
                session.execute(stmt)
            log_upsert_commit("akshare.cb_daily", len(batch))


# ====================================================================
# 工具
# ====================================================================

def _clean_value(v):
    if v is None:
        return None
    import pandas as pd
    if pd.isna(v):
        return None
    return v


def _to_float(v) -> float | None:
    if v is None:
        return None
    try:
        import pandas as pd
        if pd.isna(v):
            return None
        return float(v)
    except (ValueError, TypeError):
        return None


def _to_int(v) -> int | None:
    if v is None:
        return None
    try:
        import pandas as pd
        if pd.isna(v):
            return None
        return int(v)
    except (ValueError, TypeError):
        return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="可转债数据采集 (akshare)")
    parser.add_argument(
        "action",
        choices=["all", "list", "daily"],
        help="all=列表+日线, list=仅列表, daily=仅日线",
    )
    args = parser.parse_args()

    sync = CBDataSync()

    if args.action in ("list", "all"):
        n1 = sync.sync_cb_list()
        print(f"可转债列表: {n1} 只")  # noqa: T201
    if args.action in ("daily", "all"):
        n2 = sync.sync_cb_daily()
        print(f"可转债日线: {n2} 条")  # noqa: T201
