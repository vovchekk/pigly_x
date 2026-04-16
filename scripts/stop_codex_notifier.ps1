$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $scriptDir "codex_completion_notifier.pid"

if (-not (Test-Path $pidFile)) {
    Write-Output "Codex notifier is not running."
    exit 0
}

$watcherPid = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
if ($watcherPid) {
    $process = Get-Process -Id $watcherPid -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id $watcherPid -Force -ErrorAction SilentlyContinue
    }
}

Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
Write-Output "Codex notifier stopped."
