@echo off
set SCRIPT_DIR=%~dp0
start "Codex Notifier" /min powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%run_codex_notifier.ps1"
