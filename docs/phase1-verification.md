# AStockQuant v8.0 Phase 1 验证记录

验证日期：2026-09-25

## 环境

- Python：3.12.14
- 平台：Linux x86_64，内核 6.18.44
- 分支：`codex/v8-phase1`
- Phase 1验证前提交：`1de82a4`

当前执行环境用于源码、迁移和离线行为验证，没有安装PySide6，也没有声称完成Windows桌面窗口实机验证。

## v8基础测试

命令：

```bash
python -m pytest tests/unit tests/contracts tests/integration -q
```

结果：65项通过，0项失败。

覆盖范围包括：

- 核心不可变模型与领域错误。
- 程序目录和个人数据目录分离。
- 安全设置读取与原子保存。
- v7白名单数据只读盘点。
- 复制、哈希校验、原子提升、幂等和回滚。
- 运行清单、递归脱敏、完成标记和路径安全。
- 应用装配的只读/初始化两种模式。
- 核心层、界面层和v7依赖边界。

## v7.6.3回归基线

命令：

```bash
python -m unittest discover \
  -s /workspace/scratch/08ddc3994218/astock_quant_v7_6 \
  -p 'test_*.py' -q
```

结果：`Ran 63 tests`，`OK`。

验证前后v7.6.3目录文件集合哈希均为：

```text
9b32c2541b7bc2c64e4f1f7d6376ac2c735e5645626f8ce604d5069a8315f5e9
```

因此本阶段没有修改v7.6.3基线文件。

## 其他门槛

命令：

```bash
python -m compileall -q src tests
git diff --check
```

结果：源码和测试语法编译通过，Git差异没有空白错误。

## Phase 1结论

Phase 1的项目骨架、核心模型、个人数据路径、v7盘点与安全迁移、运行存储和应用装配已经具备可执行测试证据。真实券商、Windows界面实机验证和策略迁移不属于Phase 1。
