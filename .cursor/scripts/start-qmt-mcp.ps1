# 可选：以 SSE 模式手动启动 QMT-MCP（调试用）
# Cursor 已通过 .cursor/mcp.json + run_qmt_mcp_stdio.py 自启动（stdio），通常无需运行本脚本。
$ErrorActionPreference = "Stop"
$qmtMcpDir = "$env:USERPROFILE\.local\mcp\QMT-MCP"
$python = Join-Path $qmtMcpDir ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "QMT-MCP venv not found. Run: cd $qmtMcpDir; uv venv; uv pip install -r requirements.txt"
}

Set-Location $qmtMcpDir
$env:QUANTMCP_TRANSPORT = "sse"
Write-Host "Starting QMT-MCP SSE on http://127.0.0.1:8000/sse ..."
Write-Host "Press Ctrl+C to stop."
& $python main.py
