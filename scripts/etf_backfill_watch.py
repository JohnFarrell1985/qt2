"""轮询 ETF 日线补全日志, 标出反爬/断连/停写等风险行.

  uv run python scripts/etf_backfill_watch.py
  uv run python scripts/etf_backfill_watch.py --log logs/etf_backfill.log --interval 20 --rounds 0

--rounds 0 表示一直轮询 (Ctrl+C 结束).
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

# 命中即高亮(疑似反爬、限流、长暂停) —— HTTP 码用 \b 避免在日期/代码里误匹配
PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"curl:\s*\(56\)|Connection closed", re.I), "连接被对端关(常伴随频控/反爬)"),
    (re.compile(r"ConnectionError|Connection reset|Connection refused|timeout", re.I), "连接异常/超时"),
    (re.compile(r"(?:\b|status[=_])(?:401|403|404|405|429|50[234])\b", re.I), "HTTP 状态(限流/封禁/网关)"),
    (re.compile(r"熔断|探测失败|不可达|push2his", re.I), "东财路径熔断/探测"),
    (re.compile(r"EtfDailyStall|stall.*内无新|无新 K 线", re.I), "停写(stall)"),
    (re.compile(r"全段均无|各段均无数据|exit=2|exit=3", re.I), "全失败/子进程非0"),
    (re.compile(r"验证码|captcha|robot|forbidden|blocked|拒绝访问", re.I), "明牌反爬/封禁文案"),
    (re.compile(r"Too Many|rate.?limit|频控|限流", re.I), "限流"),
]


def _worth_reporting(line: str) -> bool:
    """排除纯进度 [INFO] 行, 减少误报。"""
    if "拉取中" in line and "[INFO]" in line and "WARNING" not in line and "ERROR" not in line:
        return False
    if "【etf_daily】进段" in line and "WARNING" not in line:
        return False
    return True

PROGRESS_RE = re.compile(r"拉取中\s+(\d+)/(\d+)")


def _scan_file(path: Path, last_size: int) -> tuple[int, list[str], str | None]:
    """返回 (新 offset, 风险行列表, 最后进度)."""
    if not path.is_file():
        return last_size, [], None
    data = path.read_bytes()
    if len(data) <= last_size:
        return len(data), [], None
    chunk = data[last_size:].decode("utf-8", errors="replace")
    hits: list[str] = []
    for line in chunk.splitlines():
        if not _worth_reporting(line):
            continue
        for rx, _label in PATTERNS:
            if rx.search(line):
                hits.append(line.strip()[:500])
                break
    last_prog: str | None = None
    for line in chunk.splitlines():
        m = PROGRESS_RE.search(line)
        if m:
            last_prog = f"{m.group(1)}/{m.group(2)}"
    return len(data), hits, last_prog


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--log",
        type=Path,
        default=Path("logs/etf_backfill.log"),
        help="补全任务 tee 的日志文件",
    )
    ap.add_argument("--interval", type=float, default=30.0, help="轮询秒数")
    ap.add_argument(
        "--rounds",
        type=int,
        default=8,
        help="轮询次数; 0=直到手动中断",
    )
    args = ap.parse_args()

    if not args.log.is_file():
        print(f"找不到日志: {args.resolve()} — 先启动补全并写入该文件", file=sys.stderr)
        return 1

    # 从末尾前 64KB 起跟增量, 避免首屏无进度; 大文件不全文扫
    st = args.log.stat()
    pos = max(0, st.st_size - 65536)
    if st.st_size > 65536:
        print("从约最后 64KB 起监控增量新内容…", flush=True)
    round_ = 0
    while True:
        round_ += 1
        pos, hits, prog = _scan_file(args.log, pos)
        ts = time.strftime("%H:%M:%S")
        if prog:
            print(f"[{ts}] 最近进度: 段 {prog}", flush=True)
        for h in hits:
            # Windows 控制台常见为 GBK, 非 BMP/乱码用 ASCII 兜底
            safe = h.encode("ascii", errors="backslashreplace").decode("ascii")
            print(f"[{ts}] [RISK] {safe}", flush=True)
        if not hits and not prog and round_ == 1:
            print(f"[{ts}] 等待新日志… (文件: {args.log.resolve()})", flush=True)
        if args.rounds and round_ >= args.rounds:
            break
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
