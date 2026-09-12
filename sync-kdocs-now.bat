@echo off
chcp 65001 >nul
title PriceRadar 立即同步金山文档
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\kdocs-daily-sync.ps1"
if errorlevel 1 pause
