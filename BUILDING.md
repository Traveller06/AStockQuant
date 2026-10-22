# AStockQuant 源码运行、构建与安装

## 本次发行范围

`v8.3.6-preview.1` 是预发布验证版：增加全市场历史恢复路径；不改动选股策略、参数、三级筛选条件或复权衔接阈值。它是 **Windows Python 双击安装 ZIP**，不是独立 EXE，也不含 Python 运行时或离线依赖。不能将离线测试通过理解为全市场行情一定可用。

## Windows 安装

1. 安装64位 Python 3.11，确保 `py` 或 `python` 命令可用。
2. 从 GitHub Releases 的 Assets 下载 `AStockQuant-v8.3.6-preview.1-Windows-Python.zip`，解压到可写目录，例如 `C:\AStockQuant`。不要直接在压缩包内运行。
3. 双击 `1_第一次双击_安装并打开.bat`。脚本创建本目录的 `.venv` 并通过 pip 安装 `requirements.txt`，首次需要联网。
4. 以后双击 `2_以后双击_启动软件.bat`；离线检查双击 `3_双击_离线自检.bat`。
5. 升级前关闭软件，只替换程序文件，保留 `cache`、`v8_market_updates`、`v8_history_snapshots`、`v8_runs`、`tail_strategy_cache`、持仓/账户及个人运行文件。新用户不需要复制其他人的行情或账户数据。

## 从完整源码运行

下载与安装包对应的 tag 源码或 clone 现有仓库，不要只下载 README。仓库主程序保存在 `windows_app/`，模块包在 `src/astock_quant/`。

Windows PowerShell（在源码根目录）：

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe windows_app/main.py
```

源码运行前使用 editable install，令 `src` 包可导入。不能将源码目录的 windows_app 单独复制后遗漏 src。向普通使用者交付应使用完整打包 ZIP。

## 测试与构建

```powershell
$env:QT_QPA_PLATFORM = "offscreen"
.\.venv\Scripts\python.exe -m pytest -q tests
.\.venv\Scripts\python.exe -m unittest discover -s windows_app -p "test_*.py" -q
.\.venv\Scripts\python.exe scripts/build_windows_release.py --output dist/AStockQuant-v8.3.6-preview.1-Windows-Python.zip
.\.venv\Scripts\python.exe scripts/verify_release.py dist/AStockQuant-v8.3.6-preview.1-Windows-Python.zip
Get-FileHash dist/AStockQuant-v8.3.6-preview.1-Windows-Python.zip -Algorithm SHA256
```

源码测试中的 v7.6.3 历史上传包不随仓库分发，缺少时只跳过该历史安装包的63项审计，其余测试照常执行。如你持有审定旧包，可设置环境变量 `ASTOCK_V763_ARCHIVE` 为旧ZIP的本机完整路径后重跑；传入错误或校验值不符的旧包会失败，不会被跳过。

Linux/macOS 可用 `python3 -m venv .venv`、`.venv/bin/python -m pip install -e ".[dev]"` 执行相同 Python 命令，Qt 测试设置 `QT_QPA_PLATFORM=offscreen`。目标用户界面仍是 Windows 桌面端。

## 发布与可复现性

`.github/workflows/windows-release.yml` 在 Windows runner 上安装依赖、运行项目/桌面/ZIP解压测试，成功后才发布 prerelease。发布附件包括程序 ZIP、SHA256SUMS、VALIDATION.json 和实际测试环境的 requirements-tested.txt。

构建器使用明确文件白名单和固定ZIP元数据；`release/v8.3.5-original-payload-sha256.json` 保留原75个程序文件的校验值。回归测试要求原策略文件保持字节一致，仅允许全市场扫描数据恢复模块改动行为，以及入口/两个启动脚本/版本断言更新版本文字。新增独立历史快照模块和新版安装说明；VALIDATION.json记录实际未改变的原文件数。源码归档通过同名发布 tag 取得，程序 ZIP 中 SOURCE_INFO.txt 提供永久对应链接。

运行依赖清单位于 pyproject.toml 和 windows_app/requirements.txt，使用版本下限；requirements-tested.txt 仅记录本次实际验证环境，不表示任何未来依赖组合都已测试。GitHub构建日志和VALIDATION.json是Windows自动化结果的依据；没有用户网络下的人工实机扫描验收。

## GPL 与第三方依赖

原创项目代码采用 GPL-3.0-only，正文见 LICENSE。分发修改版时请保留版权和许可说明，并依 GPL 提供相应源码及构建资料。第三方依赖保留其各自许可，详见 THIRD_PARTY_NOTICES.md；本ZIP不捆绑它们的安装二进制。
