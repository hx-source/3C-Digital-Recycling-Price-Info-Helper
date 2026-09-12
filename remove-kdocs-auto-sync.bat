@echo off
chcp 65001 >nul
title PriceRadar 删除金山文档自动同步
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\uninstall-kdocs-task.ps1"
pause
