"""实时行情快照采集 (A17)

数据来源 (双通道):
  1. akshare  stock_zh_a_spot_em  → 全市场实时行情 (无需 QMT)
  2. QMTClient.get_full_tick     → QMT tick 快照 (延迟更低)

盘中可按定时任务调度 (如每 3 分钟), 采集后 bulk insert 至 stock_realtime。
"""
from datetime import datetime, timedelta

from src.common.config import settings
from src.common.db import get_session
from src.common.db_batch import DEFAULT_TABLE_UPSERT_FLUSH, log_upsert_commit
from src.common.logger import get_logger
from src.data.models import StockRealtime
from src.datacollect.rate_limiter import TokenBucketLimiter

logger = get_logger(__name__)

_AKSHARE_COL_MAP = {
    "代码": "code",
    "最新价": "price",
    "涨跌额": "change",
    "涨跌幅": "change_pct",
    "成交量": "volume",
    "成交额": "amount",
    "振幅": "amplitude",
    "换手率": "turnover_rate",
    "涨速": "rise_speed",
    "5分钟涨跌": "change_5min",
    "60日涨跌幅": "change_60d",
    "年初至今涨跌幅": "change_ytd",
    "总市值": "market_cap",
    "流通市值": "float_market_cap",
    "动态市盈率": "pe_dynamic",
    "市净率": "pb",
}

_SCALE_TO_YI = {"market_cap", "float_market_cap"}


def _get_limiter() -> TokenBucketLimiter:
    return TokenBucketLimiter.for_domain(
        "akshare",
        rate=settings.datacollect.akshare_rate,
        burst=settings.datacollect.akshare_burst,
    )


class RealtimeSnapshotCollector:
    """实时行情快照采集 — 盘中定时采集全市场快照"""

    def collect_snapshot(self) -> int:
        """使用 akshare 采集全市场实时行情快照.

        Returns:
            入库记录数
        """
        import akshare as ak

        limiter = _get_limiter()

        try:
            limiter.acquire()
            df = ak.stock_zh_a_spot_em()
        except Exception as e:
            logger.error("获取全市场实时行情失败: %s", e)
            return 0

        if df is None or df.empty:
            logger.warning("全市场实时行情为空")
            return 0

        now = datetime.now()
        rows = self._map_snapshot_rows(df, now)
        if not rows:
            return 0

        count = self._bulk_insert(rows)
        logger.info("实时快照采集完成: %d 条, 时间 %s", count, now.strftime("%H:%M:%S"))
        return count

    def cleanup_old_snapshots(self, keep_days: int = 5) -> int:
        """清理过期快照数据.

        Args:
            keep_days: 保留最近几天的数据

        Returns:
            删除记录数
        """
        cutoff = datetime.now() - timedelta(days=keep_days)
        with get_session() as session:
            deleted = (
                session.query(StockRealtime)
                .filter(StockRealtime.timestamp < cutoff)
                .delete(synchronize_session=False)
            )
        logger.info("清理 %d 天前快照: 删除 %d 条", keep_days, deleted)
        return deleted

    def collect_snapshot_qmt(self) -> int:
        """使用 QMT get_full_tick 采集实时快照.

        QMT 不可用时自动降级到 akshare。

        Returns:
            入库记录数
        """
        try:
            from src.data.qmt_client import QMTClient
            client = QMTClient()
            tick_data = client.get_full_tick(["SH", "SZ"])
        except (ImportError, Exception) as e:
            logger.warning("QMT 不可用 (%s), 降级到 akshare", e)
            return self.collect_snapshot()

        if not tick_data:
            logger.warning("QMT tick 数据为空, 降级到 akshare")
            return self.collect_snapshot()

        now = datetime.now()
        rows = self._map_qmt_tick_rows(tick_data, now)
        if not rows:
            return 0

        count = self._bulk_insert(rows)
        logger.info("QMT 实时快照采集完成: %d 条", count)
        return count

    # ------------------------------------------------------------------
    # 字段映射
    # ------------------------------------------------------------------
    @staticmethod
    def _map_snapshot_rows(df, ts: datetime) -> list[dict]:
        import pandas as pd

        rows: list[dict] = []
        for _, row in df.iterrows():
            code = row.get("代码")
            if not code:
                continue

            rec: dict = {"code": str(code), "timestamp": ts}
            for cn_col, en_col in _AKSHARE_COL_MAP.items():
                if cn_col == "代码":
                    continue
                v = row.get(cn_col)
                if v is not None and not pd.isna(v):
                    try:
                        fv = float(v)
                        if en_col in _SCALE_TO_YI:
                            fv = fv / 1e8
                        rec[en_col] = fv
                    except (ValueError, TypeError):
                        rec[en_col] = None
                else:
                    rec[en_col] = None

            if rec.get("volume") is not None:
                rec["volume"] = int(rec["volume"])

            rows.append(rec)
        return rows

    @staticmethod
    def _map_qmt_tick_rows(tick_data: dict, ts: datetime) -> list[dict]:
        rows: list[dict] = []
        for qmt_code, tick in tick_data.items():
            if not tick:
                continue
            code = qmt_code.split(".")[0] if "." in qmt_code else qmt_code
            rows.append({
                "code": code,
                "timestamp": ts,
                "price": _safe_tick_float(tick, "lastPrice"),
                "change": _safe_tick_float(tick, "lastClose",
                                           transform=lambda lc: (
                                               _safe_tick_float(tick, "lastPrice") - lc
                                               if lc and _safe_tick_float(tick, "lastPrice")
                                               else None)),
                "volume": _safe_tick_int(tick, "volume"),
                "amount": _safe_tick_float(tick, "amount"),
            })
        return rows

    # ------------------------------------------------------------------
    # DB
    # ------------------------------------------------------------------
    @staticmethod
    def _bulk_insert(
        rows: list[dict], batch_size: int = DEFAULT_TABLE_UPSERT_FLUSH,
    ) -> int:
        count = 0
        for i in range(0, len(rows), batch_size):
            batch = rows[i: i + batch_size]
            with get_session() as session:
                session.bulk_insert_mappings(StockRealtime, batch)
                count += len(batch)
            log_upsert_commit("realtime.stock_realtime", len(batch))
        return count


# ====================================================================
# 工具
# ====================================================================

def _safe_tick_float(tick, key: str, transform=None):
    try:
        v = tick.get(key) if isinstance(tick, dict) else getattr(tick, key, None)
        if v is not None:
            fv = float(v)
            if transform:
                return transform(fv)
            return fv
    except Exception:
        pass
    return None


def _safe_tick_int(tick, key: str):
    try:
        v = tick.get(key) if isinstance(tick, dict) else getattr(tick, key, None)
        if v is not None:
            return int(v)
    except Exception:
        pass
    return None


if __name__ == "__main__":
    collector = RealtimeSnapshotCollector()
    n = collector.collect_snapshot()
    print(f"采集完成: {n} 条")  # noqa: T201
