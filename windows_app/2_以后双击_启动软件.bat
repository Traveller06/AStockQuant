@echo off
chcp 65001 >nul
title AStockQuant v8.3.0
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
  echo 尚未完成安装。
  echo 请先双击：1_第一次双击_安装并打开.bat
  pause
  exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" main.py
if errorlevel 1 (
  echo 启动失败，正在显示错误信息...
  ".venv\Scripts\python.exe" main.py
  pause
  exit /b 1
)

exit /b 0
