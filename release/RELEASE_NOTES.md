这是 **Windows Python 双击安装 ZIP 的预发布验证版**，不是独立EXE或经人工实机验收的正式版。

## 下载与安装

- 普通用户下载 Assets 中的 `AStockQuant-v8.3.5-preview.1-Windows-Python.zip`，不要误下仅用于源码的 Source code ZIP。
- Windows 64位，推荐已安装 Python 3.11；首次安装依赖需要联网。
- 解压后双击 `1_第一次双击_安装并打开.bat`，以后双击 `2_以后双击_启动软件.bat`。
- 升级保留原有cache、v8_market_updates、v8_runs、tail_strategy_cache、持仓和账户数据。

## 内容与验证

- 复用原v8.3.5全部75个程序文件，保留周线趋势、预确认/确认/强确认、规则1/2/3、世坤因子与尾盘两日策略。
- 原75个程序文件与上次校验安装包逐项一致；只增加GPL许可证和源码/构建说明。
- 发布工作流在Windows执行项目测试、71项桌面离线测试、真实Qt窗口构造、独立解压71项自检，全部通过后才发布。
- 项目测试中，缺失的私人v7.6.3上传包审计明确跳过；该旧包在本次本地恢复后已通过63项审计，不在源码仓库重新分发。
- 每次实际结果、跳过项、环境版本和对应提交详见本Release的 `VALIDATION.json`；依赖环境见 `requirements-tested.txt`，校验值见 `SHA256SUMS.txt`。
- 自动化离线检查不代表用户网络下所有股票行情已补齐；没有真实账户下单、实盘收益或Windows人工全市场扫描验收声明。

## 相应源码与GPL

采用GPL-3.0-only。完整对应源码为本Release同名tag `v8.3.5-preview.1` 下的源代码，使用GitHub自动提供的Source code ZIP/tar.gz即可取得。构建步骤见 `BUILDING.md`，程序包内附 `LICENSE`、`SOURCE_INFO.txt` 及第三方许可说明。
