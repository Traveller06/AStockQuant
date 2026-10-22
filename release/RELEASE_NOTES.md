Windows Python 双击安装 ZIP，预发布验证版。需要Windows 64位和Python（推荐3.11），首次安装依赖需联网；不是独立EXE。

## v8.3.6变化

- 全市场扫描的旧缓存损坏、复权衔接失败或重叠不足不再阻止请求独立历史。
- 独立行情通过日期、OHLCV、有限数值、新鲜度检查后，保存至新的v8_history_snapshots目录；原cache和旧增量文件保留。
- 快照包含SHA-256、日期范围和恢复原因；中断/损坏的快照不作为有效行情使用。
- 不降低21个完整周要求，不放宽复权衔接阈值；历史不足、数据过期和无效价格继续明确报告。
- 周线策略、预确认/确认/强确认、规则1/2/3、世坤因子、尾盘策略保持不变。

## 安装与验收

下载Assets中的AStockQuant-v8.3.6-preview.1-Windows-Python.zip，解压到原安装目录并双击“1_第一次双击_安装并打开.bat”；以后双击“2_以后双击_启动软件.bat”。保留cache、v8_market_updates、v8_history_snapshots、v8_runs、tail_strategy_cache及所有个人运行数据。

同日期扫描复用已保存成功记录，只重试error/stale；新日期扫描全部股票。实际覆盖率须重新扫描并导出CSV核对。本环境没有用户电脑上的旧缓存，不能宣称164个真实错误全部修复，也不宣称Windows用户网络下已经完成人工验收。

自动化验证通过才发布：完整项目测试、71项桌面测试、真实Qt窗口构造、ZIP解压71项测试。实际结果和源码提交见VALIDATION.json，环境见requirements-tested.txt，校验值见SHA256SUMS.txt。

GPL-3.0-only。完整相应源码见同名tag v8.3.6-preview.1及Source code ZIP；构建说明见BUILDING.md，包内附LICENSE、SOURCE_INFO.txt与第三方许可说明。
