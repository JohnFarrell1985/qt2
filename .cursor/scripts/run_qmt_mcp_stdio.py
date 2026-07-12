#!/usr/bin/env python3
"""兼容入口：转发到 ~/.local/mcp/QMT-MCP/run_stdio_mcp.py"""

from __future__ import annotations

import runpy
from pathlib import Path

TARGET = Path.home() / ".local" / "mcp" / "QMT-MCP" / "run_stdio_mcp.py"

if __name__ == "__main__":
    runpy.run_path(str(TARGET), run_name="__main__")
