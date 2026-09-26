@echo off
chcp 65001 >nul
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  echo 未找到 Python 虚拟环境。请先双击 install.bat。
  pause
  exit /b 1
)
.venv\Scripts\python.exe main.py
if errorlevel 1 echo 程序启动失败，请保留本窗口中的错误信息。
pause
