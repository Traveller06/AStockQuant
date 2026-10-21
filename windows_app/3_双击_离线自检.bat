@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo 请先双击：1_第一次双击_安装并打开.bat
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m unittest test_execution test_tail_strategy test_v8_offline -q
if errorlevel 1 (
  echo 自检未通过，请保存报错窗口内容。
  pause
  exit /b 1
)
echo 离线自检通过。
pause
