#Requires -Version 5.0
<#
  从 Vibe-Trading 同步 skills 到 openclaw/workspace/skills
  用法:
    .\sync_vibe_skills.ps1 -Source C:\Users\you\git\Vibe-Trading
    .\sync_vibe_skills.ps1 -Source C:\Users\you\git\Vibe-Trading -Shallow
    $env:VIBE_TRADING_ROOT = "C:\Users\you\git\Vibe-Trading"; .\sync_vibe_skills.ps1
#>
param(
    [string] $Source = $env:VIBE_TRADING_ROOT,
    [switch] $Shallow,
    [switch] $AllVibe,
    [switch] $DryRun
)

$ErrorActionPreference = "Stop"
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = Join-Path $scriptDir "sync_vibe_skills.py"
$args = @($py)
if ($Source) { $args += @("--source", $Source) }
if ($Shallow) { $args += "--shallow" }
if ($AllVibe) { $args += "--all-vibe" }
if ($DryRun) { $args += "--dry-run" }

& python @args
exit $LASTEXITCODE
