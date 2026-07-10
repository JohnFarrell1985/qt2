"""ST / *ST 股票识别与代码集合加载."""

from __future__ import annotations

from src.common.db import get_session
from src.common.logger import get_logger
from sqlalchemy import text

logger = get_logger(__name__)

_st_codes_cache: set[str] | None = None


def normalize_a_code(code: str) -> str:
    """统一为 6 位数字代码 (与 stock_daily.code 一致)."""
    c = str(code).strip().upper()
    if "." in c:
        c = c.split(".", 1)[0]
    return c.zfill(6) if c.isdigit() else c


def is_st_name(name: str | None) -> bool:
    """A 股 ST / *ST / S*ST 名称判定."""
    if not name or not str(name).strip():
        return False
    n = str(name).strip().upper()
    return n.startswith("*ST") or n.startswith("ST") or n.startswith("S*ST") or n.startswith("SST")


def clear_st_codes_cache() -> None:
    global _st_codes_cache
    _st_codes_cache = None


def _load_st_codes_from_db() -> set[str]:
    codes: set[str] = set()
    with get_session() as session:
        rows = session.execute(
            text("""
                SELECT code, name FROM stocks
                WHERE name ILIKE 'ST%' OR name ILIKE '*ST%' OR name ILIKE 'S*ST%'
            """),
        ).fetchall()
        for code, name in rows:
            if is_st_name(name):
                codes.add(normalize_a_code(code))

        uni_rows = session.execute(
            text("SELECT code FROM stock_universe WHERE status = 'st'"),
        ).fetchall()
        codes.update(normalize_a_code(r[0]) for r in uni_rows)
    return codes


def _load_st_codes_from_qmt() -> set[str]:
    try:
        from src.data.qmt_client import QMTClient

        client = QMTClient()
    except Exception as e:
        logger.debug("[ST] QMT 不可用: %s", e)
        return set()

    codes: set[str] = set()
    try:
        sectors = client.get_sector_list()
        for sector in sectors:
            label = str(sector)
            if "ST" not in label.upper() and "风险" not in label:
                continue
            for raw in client.get_stock_list_in_sector(label):
                codes.add(normalize_a_code(raw))
    except Exception as e:
        logger.debug("[ST] QMT 板块扫描失败: %s", e)

    if codes:
        logger.info("[ST] QMT 板块识别 ST/*ST: %d 只", len(codes))
        return codes

    try:
        for raw in client.get_stock_list_in_sector("沪深A股"):
            detail = client.get_instrument_detail(raw)
            if is_st_name(str(detail.get("InstrumentName", ""))):
                codes.add(normalize_a_code(raw))
        if codes:
            logger.info("[ST] QMT 全量名称扫描 ST/*ST: %d 只", len(codes))
    except Exception as e:
        logger.warning("[ST] QMT 全量扫描失败: %s", e)
    return codes


def _load_st_codes_from_akshare() -> set[str]:
    try:
        import akshare as ak
    except ImportError:
        logger.warning("[ST] akshare 未安装, 无法在线识别 ST")
        return set()

    codes: set[str] = set()
    try:
        df = ak.stock_info_a_code_name()
    except Exception as e:
        logger.warning("[ST] stock_info_a_code_name 失败: %s", e)
        try:
            df = ak.stock_zh_a_spot_em()
            if "代码" in df.columns:
                df = df.rename(columns={"代码": "code", "名称": "name"})
        except Exception as e2:
            logger.warning("[ST] stock_zh_a_spot_em 备用失败: %s", e2)
            return set()

    if df is None or df.empty:
        return set()

    name_col = "name" if "name" in df.columns else ("名称" if "名称" in df.columns else None)
    code_col = "code" if "code" in df.columns else ("代码" if "代码" in df.columns else None)
    if not name_col or not code_col:
        return set()

    for _, row in df.iterrows():
        if is_st_name(str(row.get(name_col, ""))):
            codes.add(normalize_a_code(str(row.get(code_col, ""))))
    logger.info("[ST] akshare 识别 ST/*ST: %d 只", len(codes))
    return codes


def get_st_codes(*, refresh: bool = False) -> set[str]:
    """返回 ST/*ST 代码集合 (进程内缓存)."""
    global _st_codes_cache
    if _st_codes_cache is not None and not refresh:
        return _st_codes_cache

    codes = _load_st_codes_from_db()
    if not codes:
        codes = _load_st_codes_from_akshare()
    if not codes:
        logger.warning(
            "[ST] 未能加载 ST/*ST 名单 (stocks/stock_universe 为空且 QMT/akshare 不可用); "
            "exclude_st 暂无法生效, 建议运行 sync_stocks_full 或配置 QMT"
        )
    _st_codes_cache = codes
    return _st_codes_cache


def filter_out_st(codes: list[str]) -> list[str]:
    """从代码列表中剔除 ST/*ST."""
    if not codes:
        return codes
    st_set = get_st_codes()
    if not st_set:
        return codes
    return [c for c in codes if normalize_a_code(c) not in st_set]
