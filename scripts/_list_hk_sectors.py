# -*- coding: utf-8 -*-
"""List all QMT sectors that contain .HK codes."""
from src.data.qmt_client import QMTClient

c = QMTClient()
for s in c.get_sector_list():
    codes = c.get_stock_list_in_sector(s)
    if not codes:
        continue
    hk = [x for x in codes if str(x).upper().endswith(".HK")]
    if hk:
        print(f"{s}\t{len(hk)}")
