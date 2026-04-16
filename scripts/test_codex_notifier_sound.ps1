$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
if (-not $pythonCommand) {
    throw "Python interpreter was not found in PATH."
}

& $pythonCommand.Source (Join-Path $scriptDir "codex_completion_notifier.py") --test-sound
