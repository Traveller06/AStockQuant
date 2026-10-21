@echo off
chcp 65001 >nul
cd /d %~dp0
if not exist .venv\Scripts\python.exe (
  echo 正在创建 Python 虚拟环境...
  py -3.11 -m venv .venv
  if errorlevel 1 (
    echo 创建失败。请先安装 Python 3.11，并勾选 Add Python to PATH。
    pause
    exit /b 1
  )
)
echo 正在安装或核对依赖...
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 (
  echo 依赖安装失败，请检查网络后重新运行 install.bat。
  pause
  exit /b 1
)
echo 安装完成。现在可以双击 run.bat。
pause
