@echo off
chcp 65001 >nul
title AStockQuant v8.0.0 安装并启动
cd /d "%~dp0"

echo ========================================
echo   AStockQuant v8.0.0 正在自动安装
echo   请不要关闭这个窗口
echo ========================================
echo.

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] 正在创建运行环境...
  py -3.11 -m venv .venv 2>nul
  if errorlevel 1 py -3 -m venv .venv 2>nul
  if errorlevel 1 python -m venv .venv 2>nul
  if errorlevel 1 (
    echo.
    echo 没有找到可用的 Python。
    echo 请确认已经安装 Python，然后再次双击本文件。
    pause
    exit /b 1
  )
) else (
  echo [1/3] 已找到运行环境。
)

echo [2/3] 正在安装或核对组件，首次运行可能需要几分钟...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo 组件安装失败。请检查网络，然后再次双击本文件。
  pause
  exit /b 1
)

echo [3/3] 正在打开 AStockQuant v8.0.0...
start "" ".venv\Scripts\pythonw.exe" main.py
if errorlevel 1 (
  echo 启动失败，正在显示错误信息...
  ".venv\Scripts\python.exe" main.py
  pause
  exit /b 1
)

exit /b 0
