# -*- coding: utf-8 -*-
from src.data.qmt_client import QMTClient

c = QMTClient()
sectors = c.get_sector_list()
for s in sectors:
    codes = c.get_stock_list_in_sector(s)
    if not codes:
        continue
    if any(str(x).upper().endswith(".HK") for x in codes[:5]):
        hk = [x for x in codes if str(x).upper().endswith(".HK")]
        print(f"sector={s!r} total={len(codes)} hk={len(hk)} sample={hk[:5]}")
        break
