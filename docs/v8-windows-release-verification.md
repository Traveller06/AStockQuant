# AStockQuant v8.0 Windows 安装包验证

- 构建平台：Linux，Python 3.12；未进行 Windows GUI 实机验证。
- 源码分支：`codex/v8-phase1`。
- 构建命令：`python scripts/build_windows_release.py --output dist/AStockQuant_v8_0_周线趋势确认_双击版.zip`。
- 独立解压验证：`python scripts/verify_release.py dist/AStockQuant_v8_0_周线趋势确认_双击版.zip`；包内 64 项离线测试通过。
- 源码测试：`python -m pytest -q`，172 项通过；旧版原有测试 63 项通过。
- 包内文件：60 个，平面根目录，可运行 `main.py` 和两个原有双击启动器；未携带账户、缓存、股票样本或运行数据。
- 安装包 SHA-256：`c96181708c83d0c474d1abbad17cd84c238692e28577f85e1f219a4396dfcce2`。
- 导入 v7.6.3 原始安装包 SHA-256：`dfc50da574d6a15b280ba65091e883cfd7047cc4238e3aca92badef970be540e`。
- 旧日线缓存缺少真实成交额以及停牌、涨跌停交易状态；v8 页面提示该口径限制。没有成交配对统计时，胜率和盈亏因子显示“待逐笔配对”，不伪造指标。
