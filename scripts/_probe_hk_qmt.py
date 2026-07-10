"""Probe QMT HK sectors and sample kline fetch."""
from __future__ import annotations

import sys

from src.data.qmt_client import QMTClient
from src.data.kline_bulk_sync import _qmt_fetch_stock


def main() -> int:
    c = QMTClient()
    sectors = c.get_sector_list()
    hk_sectors = [s for s in sectors if "港" in s or "HK" in s.upper() or "陆港" in s]
    print("hk_related_sectors:", len(hk_sectors))
    for s in hk_sectors[:30]:
        print(" ", s)

    # try common sector names
    for name in ["港股通", "沪港通", "深港通", "陆港通", "港股"]:
        try:
            codes = c.get_stock_list_in_sector(name)
            print(f"sector[{name!r}] count={len(codes)} sample={codes[:5]}")
        except Exception as e:
            print(f"sector[{name!r}] error={e}")

    # if we find codes with .HK suffix, test kline
    for name in hk_sectors:
        codes = c.get_stock_list_in_sector(name)
        if codes and any(".HK" in x.upper() or x.startswith("0") for x in codes[:3]):
            print(f"\nTesting sector {name!r} first code {codes[0]}")
            pure = codes[0].split(".")[0]
            rows = _qmt_fetch_stock(pure, "20250701", "20250710")
            print(f"  _qmt_fetch_stock({pure}) rows={len(rows)}")
            if rows:
                print(f"  sample={rows[-1]}")
            # also test with full sym
            rows2 = _qmt_fetch_stock(codes[0], "20250701", "20250710")
            print(f"  _qmt_fetch_stock({codes[0]}) rows={len(rows2)}")
            break

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
