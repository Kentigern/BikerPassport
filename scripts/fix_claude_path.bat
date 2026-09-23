@echo off
rem Double-click fix for "Could not locate the Claude CLI" / "claude is not recognised".
rem Runs fix_claude_path.ps1 (same folder), which finds claude.exe and adds it to your PATH.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0fix_claude_path.ps1"
echo.
pause
