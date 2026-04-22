"""ETF 日线多源续跑, 直到底层 ``etf_daily`` 成功 (退出码 0).

顺序: ``auto`` (东财可达则用东财, 否则腾讯) → 强制定腾讯 → 仅新浪.  任一子进程
非 0 (含 stall=2, 全失败=3, 其它=1) 都自动换下一源; 三轮跑完则休眠再从头循环,
适合网络抖动/反爬/东财断连场景.

    uv run python -m src.data.etf_daily_failover --start-date 20160101
"""
from __future__ import annotations

import subprocess
import sys
import time
from argparse import ArgumentParser
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]


def main() -> int:
    p = ArgumentParser(description=__doc__.split("---", 1)[0].strip())
    p.add_argument(
        "--start-date",
        default="20160101",
        help="地板日 / 新标的起 (默认约 10 年回溯)",
    )
    p.add_argument(
        "--stall-sec",
        type=float,
        default=120.0,
        help="无新 K 线判 stall 的秒数 (传给 etf_daily); 0=关闭",
    )
    p.add_argument("--no-resume", action="store_true", help="不从 MAX(trade_date) 续传")
    p.add_argument(
        "--round-sleep",
        type=float,
        default=45.0,
        help="每跑完东财→腾讯→新浪一轮仍全部失败时, 休息秒数再从头",
    )
    p.add_argument(
        "--max-rounds",
        type=int,
        default=0,
        help="最大轮数, 0=不限制 (直到某次子进程 0 退出)",
    )
    a = p.parse_args()

    base: list[str] = [
        sys.executable, "-m", "src.data.akshare_financial_sync", "etf_daily",
        "--start-date", a.start_date,
        "--stall-sec", str(a.stall_sec),
    ]
    if a.no_resume:
        base.append("--no-resume")

    # auto 会走 kline 模块内东财健康探测, 对直连不稳环境更稳
    steps: list[tuple[list[str], str]] = [
        (["--kline-source", "auto"], "auto: 东财/探测后腾讯 + 新浪兜底"),
        (["--kline-source", "tencent"], "tencent: 腾讯 + 新浪兜底"),
        (["--sina-only-etf"], "sina: 仅新浪 K 线"),
    ]

    round_num = 0
    while True:
        if a.max_rounds and round_num >= a.max_rounds:
            print("达到 max-rounds, 未成功", flush=True)  # noqa: T201
            return 1
        round_num += 1
        print(f"\n=== ETF 日线 第 {round_num} 轮 (每轮 3 档数据源) ===\n", flush=True)  # noqa: T201

        for extra, desc in steps:
            cmd = base + extra
            print("→", desc, flush=True)  # noqa: T201
            r = subprocess.run(cmd, cwd=_REPO, check=False)
            if r.returncode == 0:
                print("完成:", desc, flush=True)  # noqa: T201
                return 0
            print(  # noqa: T201
                f"  子进程 exit={r.returncode} ({desc})，换下一档…",
                flush=True,
            )

        print(  # noqa: T201
            f"本轮 3 档均失败, {a.round_sleep:.0f}s 后重试整轮…",
            flush=True,
        )
        time.sleep(a.round_sleep)


if __name__ == "__main__":
    raise SystemExit(main())
