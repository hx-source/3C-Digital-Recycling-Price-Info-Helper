@echo off
chcp 65001 >nul
title PriceRadar 金山文档自动同步设置
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\kdocs-daily-sync.ps1" -Login
if errorlevel 1 (
  echo.
  echo 设置失败，请查看上方错误信息。
  pause
  exit /b 1
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\install-kdocs-task.ps1"
echo.
echo 设置完成。以后无需打开 Codex，Windows 会每天自动执行。
pause
