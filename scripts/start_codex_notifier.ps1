$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $scriptDir "codex_completion_notifier.pid"
$runnerPath = Join-Path $scriptDir "run_codex_notifier.ps1"

if (Test-Path $pidFile) {
    $existingPid = (Get-Content $pidFile -ErrorAction SilentlyContinue | Select-Object -First 1).Trim()
    if ($existingPid) {
        $existingProcess = Get-Process -Id $existingPid -ErrorAction SilentlyContinue
        if ($existingProcess) {
            Write-Output "Codex notifier is already running (PID $existingPid)."
            exit 0
        }
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

$process = Start-Process -FilePath "powershell.exe" `
    -ArgumentList @(
        "-NoProfile",
        "-NoExit",
        "-ExecutionPolicy", "Bypass",
        "-File", $runnerPath
    ) `
    -WindowStyle Minimized `
    -PassThru

Set-Content -Path $pidFile -Value $process.Id -Encoding ascii
Write-Output "Codex notifier started (PID $($process.Id))."
