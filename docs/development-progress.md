# AStockQuant v8.1.0 开发恢复点

更新时间：2026-09-26

## 当前工作位置

- Git分支：`codex/v8-phase1`
- 当前核心计划：`docs/superpowers/plans/2026-09-25-weekly-trend-confirmation-strategy.md`
- Windows 集成计划：`docs/superpowers/plans/2026-09-25-v8-windows-integration.md`
- 已完成：Phase 1全部任务；Phase 2 Task 1–11；Windows 集成 Task 1–8
- 最新验证：周线选股源码 183 项及离线 65 项通过；v8.1 安装包独立解压 65 项通过，Linux Qt offscreen 从 ZIP 打开界面并完成股票池筛选。
- 当前状态：v8.1.0 升级包已构建并复核；Windows GUI 实机验证仍待用户安装后确认。
- 当前交付：`dist/AStockQuant_v8_1_周线策略选股_双击版.zip`，SHA-256 `ac14fd9bb6ad7794826ec099ca87de4e3d15f6c79208677e02063b76a8a6d621`。

## 已保存检查点

- 本地设计提交：`f99bdde`
- 本地实施计划提交：`d8b150f`
- GitHub仓库：`Traveller06/AStockQuant`
- GitHub恢复分支：`codex/v8-phase1`
- 首个GitHub检查点：`e4bcab456e019456f93f51260196d8cbc60cbca3`
- 最新远程检查点：以GitHub分支 `codex/v8-phase1` 的HEAD为准

## 周线选股增量（2026-09-26）

- 用户要求按周线趋势确认策略直接筛选股票。
- 已修复未激活形态无法进入等待确认的状态转换（`a4cc930`）。
- 已实现本地股票缓存扫描与独立结果保存，`qfq` 前复权口径映射和未完成周线隔离；v8.1.0 安装包验证记录见 `docs/v8.1-windows-screen-verification.md`。
- 恢复点：先运行 `git status --short --branch` 并查看最新提交；本地功能、独立安装包和测试均完成，仍需同步 GitHub 及 Windows GUI 实机确认。不得重建项目或删除旧缓存。

## 恢复规则

下次恢复时按以下顺序只读检查：

1. 打开本文件确认当前任务。
2. 查看两个计划专属账本的最后一条记录。
3. 运行 `git status --short --branch` 和 `git log -10 --oneline`。
4. 已有 `Task N: complete` 记录的任务不得重做。
5. 从第一个没有完成记录的任务继续。
6. 每个任务通过测试后立即提交，并更新本文件及GitHub恢复分支。

不得通过重新初始化项目、复制旧版本目录、`git reset --hard` 或 `git checkout --` 恢复任务。
