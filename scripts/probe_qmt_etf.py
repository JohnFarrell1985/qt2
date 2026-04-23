"""探测 MiniQMT 中 ETF 板块列表规模 (``DATACOLLECT_QMT_ETF_MIN_SECTOR_SIZE`` 仅日志参考, 不挡 QMT 优先).

用法:
  uv run python scripts/probe_qmt_etf.py

退出码: 0=连接成功; 1=未连上或列表为空。
"""
from __future__ import annotations

import sys

from src.data.kline_bulk_sync import _probe_qmt, probe_qmt_etf_sector_size
from src.common.config import settings


def main() -> int:
    if not _probe_qmt():
        print("QMT/xtdata 不可用 (请检查 MiniQMT 已登入与 QMT_PATH)。", file=sys.stderr)
        return 1
    n, label = probe_qmt_etf_sector_size()
    th = int(settings.datacollect.qmt_etf_min_sector_size)
    print(f"板块: {label}")
    print(f"ETF 合约数: {n}")
    print(f"DATACOLLECT_QMT_ETF_MIN_SECTOR_SIZE: {th}")
    print(f"是否 >= 配置阈值 (仅与日志对比, kline 只要 QMT 连上就先试 xtdata): {n >= th}")
    return 0 if n > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
