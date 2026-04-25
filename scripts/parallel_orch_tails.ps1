# 在多个 PowerShell 窗口中分别 tail 一次 parallel_qmt 采集写入的 .log(UTF-8).
# 用法: 在仓库根或任意目录
#   .\scripts\parallel_orch_tails.ps1 -LogDir C:\path\to\logs\parallel\orch_20260101_120000
# 或只传 base (含 parallel_orch_latest.txt 的目录):
#   .\scripts\parallel_orch_tails.ps1
# 若当前目录有 parallel_orch_latest.txt(由 unified_collect --thread-log-dir 在 base 下生成), 可省略 -LogDir.

param(
    [string]$LogDir = ""
)
$ErrorActionPreference = "Stop"
if (-not $LogDir) {
    if (Test-Path "parallel_orch_latest.txt") {
        $LogDir = (Get-Content "parallel_orch_latest.txt" -Raw -Encoding utf8).Trim()
    } elseif (Test-Path (Join-Path $PSScriptRoot "..\parallel_orch_latest.txt")) {
        $p = Join-Path $PSScriptRoot "..\parallel_orch_latest.txt"
        $LogDir = (Get-Content $p -Raw -Encoding utf8).Trim()
    }
}
if (-not $LogDir) {
    Write-Error '请指定 -LogDir <本次 orch_YYYYMMDD_HHMMSS 目录>，或在与 parallel_orch_latest.txt 同目录下运行。'
    exit 1
}
$LogDir = (Resolve-Path -LiteralPath $LogDir).Path
$items = @(
    Get-ChildItem -Path (Join-Path $LogDir "*.log") -File -ErrorAction SilentlyContinue
)
if ($items.Count -eq 0) {
    Write-Error "目录下无 .log: $LogDir"
    exit 1
}
foreach ($f in $items) {
    $p = $f.FullName
    Start-Process powershell -ArgumentList @(
        "-NoExit", "-NoProfile", "-Command",
        "Get-Content -LiteralPath """ + $p + """ -Wait -Tail 40 -Encoding utf8; Write-Host '--- log file ended ---'"
    ) -WindowStyle Normal
}
