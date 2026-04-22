"""循环执行 ``etf_daily_failover`` 直至 ``etf_daily_audit`` 无缺口 (或达最大轮数).

    uv run python -m src.data.etf_backfill_loop
    uv run python -m src.data.etf_backfill_loop --max-rounds 5
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-date", default="20160101", help="与 etf_daily 一致")
    ap.add_argument("--stall-sec", type=float, default=120.0)
    ap.add_argument("--max-rounds", type=int, default=30, help="0=不限制(慎用)")
    ap.add_argument("--sleep", type=float, default=60.0, help="有缺口时休息秒数")
    a = ap.parse_args()

    rnd = 0
    while True:
        rnd += 1
        if a.max_rounds and rnd > a.max_rounds:
            print(f"达 max-rounds={a.max_rounds}, 停止", flush=True)  # noqa: T201
            return 1
        print(f"\n======== 第 {rnd} 轮: 多源 ETF 日线 (failover) ========\n", flush=True)  # noqa: T201
        r1 = subprocess.run(
            [
                sys.executable, "-m", "src.data.etf_daily_failover",
                "--start-date", a.start_date,
                "--stall-sec", str(a.stall_sec),
            ],
            cwd=_REPO,
        )
        print(f"failover 退出码={r1.returncode}\n", flush=True)  # noqa: T201
        r2 = subprocess.run(
            [
                sys.executable, "-m", "src.data.etf_daily_audit",
                "--floor", a.start_date,
            ],
            cwd=_REPO,
        )
        if r2.returncode == 0:
            print("======== 审计无缺口, 结束 ========\n", flush=True)  # noqa: T201
            return 0
        print(  # noqa: T201
            f"======== 仍有缺口, {a.sleep:.0f}s 后继续 ========\n",
            flush=True,
        )
        time.sleep(a.sleep)


if __name__ == "__main__":
    raise SystemExit(main())
