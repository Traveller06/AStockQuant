# 周线策略与旧版兼容性验证

- 日期：2026-09-26；执行环境：Linux / Python 3.12.14。
- v8：`python -m pytest -q`，162 项通过。
- v7.6.3：`scripts/verify_v763_baseline.py` 在临时目录运行 63 项，结果 OK。
- 原安装包 SHA-256：`dfc50da574d6a15b280ba65091e883cfd7047cc4238e3aca92badef970be540e`，运行前后相同。
- 测试涵盖策略模块导入边界、旧策略默认注册和每个交易日前缀下的决定、信号、成交及权益不变。
- 只验证了源代码与无界面测试，未进行 Windows GUI 实机验证。
