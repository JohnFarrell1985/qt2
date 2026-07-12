"""模拟盘交易 Web UI 启动入口

用法:
    python -m src.webui                       # 0.0.0.0:8001
    python -m src.webui --port 8001 --host 0.0.0.0
手机访问: 与电脑同一局域网, 浏览器打开 http://<电脑IP>:8001
"""
from __future__ import annotations

import argparse
import socket

import uvicorn

from src.common.logger import get_logger

logger = get_logger(__name__)


def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


def main() -> None:
    parser = argparse.ArgumentParser(description="QT 模拟盘交易终端 Web UI")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址 (默认 0.0.0.0, 允许手机访问)")
    parser.add_argument("--port", type=int, default=8001, help="监听端口 (默认 8001)")
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    args = parser.parse_args()

    ip = _lan_ip()
    print("=" * 56)
    print("  QT 模拟盘交易终端已启动")
    print(f"  电脑访问:  http://127.0.0.1:{args.port}")
    print(f"  手机访问:  http://{ip}:{args.port}   (需同一局域网)")
    print("=" * 56)

    uvicorn.run(
        "src.webui.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
