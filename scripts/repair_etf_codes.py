"""将误写入的 ``sz159xxx.SZ`` / ``sh510xxx.SH`` 规范为 ``159xxx.SZ`` / ``510xxx.SH`` 并合并冲突行。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import text  # noqa: E402

from src.common.db import get_engine  # noqa: E402


def _norm(code: str) -> str | None:
    c = (code or "").strip()
    m = re.match(r"^([sS][hHzZ])(\d{6})\.(SH|SZ)$", c)
    if not m:
        return None
    pfx, num, suf = m.group(1).lower(), m.group(2), m.group(3).upper()
    if pfx == "sh":
        return f"{num}.SH"
    return f"{num}.SZ"


def main() -> None:
    eng = get_engine()
    with eng.connect() as conn:
        rows = list(conn.execute(text("SELECT code FROM etf_info")).fetchall())
    bad: list[tuple[str, str]] = []
    for (code,) in rows:
        n = _norm(code)
        if n and n != code:
            bad.append((code, n))
    if not bad:
        print("无 sh/sz 前缀的 etf_info 主键, 跳过")
        return

    print(f"待规范化 {len(bad)} 个 etf_info 主键")
    with eng.begin() as conn:
        for old, new in bad:
            exists = conn.execute(
                text("SELECT 1 FROM etf_info WHERE code = :c LIMIT 1"),
                {"c": new},
            ).scalar()
            if exists:
                conn.execute(
                    text("""
                        DELETE FROM etf_daily AS d
                        USING etf_daily AS d2
                        WHERE d.code = :old AND d2.code = :new
                          AND d.trade_date = d2.trade_date
                    """),
                    {"old": old, "new": new},
                )
                conn.execute(
                    text("UPDATE etf_daily SET code = :n WHERE code = :o"),
                    {"n": new, "o": old},
                )
                conn.execute(
                    text("DELETE FROM etf_info WHERE code = :o"),
                    {"o": old},
                )
                continue
            conn.execute(
                text("UPDATE etf_daily SET code = :n WHERE code = :o"),
                {"n": new, "o": old},
            )
            conn.execute(
                text("UPDATE etf_info SET code = :n WHERE code = :o"),
                {"n": new, "o": old},
            )
    print("repair_etf_codes 完成")


def repair_daily_orphans() -> None:
    """修正仅存在于 ``etf_daily``、仍带 ``sh/sz`` 前缀的 ``code`` (合并同日重复后改主键)。"""
    eng = get_engine()
    with eng.connect() as conn:
        rows = list(
            conn.execute(
                text(
                    "SELECT DISTINCT code FROM etf_daily "
                    "WHERE code ~ '^[sS][hHzZ][0-9]{6}\\.(SH|SZ)$'"
                ),
            ).fetchall(),
        )
    if not rows:
        print("etf_daily 无 sh/sz 前缀 code")
        return
    print(f"etf_daily 待修正 {len(rows)} 个 code")
    with eng.begin() as conn:
        for (code,) in rows:
            new = _norm(code)
            if not new:
                continue
            has = conn.execute(
                text("SELECT 1 FROM etf_daily WHERE code = :c LIMIT 1"),
                {"c": new},
            ).scalar()
            if has:
                conn.execute(
                    text("""
                        DELETE FROM etf_daily AS d
                        USING etf_daily AS d2
                        WHERE d.code = :old AND d2.code = :new
                          AND d.trade_date = d2.trade_date
                    """),
                    {"old": code, "new": new},
                )
            conn.execute(
                text("UPDATE etf_daily SET code = :n WHERE code = :o"),
                {"n": new, "o": code},
            )
    print("repair_daily_orphans 完成")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--daily-only":
        repair_daily_orphans()
    else:
        main()
        repair_daily_orphans()
