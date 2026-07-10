# 启动 QMT-MCP SSE 服务（需先打开 QMT 客户端并登录）
$ErrorActionPreference = "Stop"
$qmtMcpDir = "$env:USERPROFILE\.local\mcp\QMT-MCP"
$python = Join-Path $qmtMcpDir ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "QMT-MCP venv not found. Run: cd $qmtMcpDir; uv venv; uv pip install -r requirements.txt"
}

Set-Location $qmtMcpDir
Write-Host "Starting QMT-MCP on http://127.0.0.1:8000/sse ..."
Write-Host "Press Ctrl+C to stop."
& $python main.py
