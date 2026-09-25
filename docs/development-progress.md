# AStockQuant v8.0 开发恢复点

更新时间：2026-09-25

## 当前工作位置

- Git分支：`codex/v8-phase1`
- 当前核心计划：`docs/superpowers/plans/2026-09-25-weekly-trend-confirmation-strategy.md`
- Windows 集成计划：`docs/superpowers/plans/2026-09-25-v8-windows-integration.md`
- 已完成：Phase 1全部任务；Phase 2 Task 1–8
- 当前状态：v8.0 Windows 集成规格已审核，实施计划已保存，等待用户确认计划
- 首个未完成步骤：集成计划 Task 1（原 Phase 2 Task 9，A股下一交易日撮合与组合约束）

## 已保存检查点

- 本地设计提交：`f99bdde`
- 本地实施计划提交：`d8b150f`
- GitHub仓库：`Traveller06/AStockQuant`
- GitHub恢复分支：`codex/v8-phase1`
- 首个GitHub检查点：`e4bcab456e019456f93f51260196d8cbc60cbca3`
- 最新远程检查点：以GitHub分支 `codex/v8-phase1` 的HEAD为准

## 恢复规则

下次恢复时按以下顺序只读检查：

1. 打开本文件确认当前任务。
2. 查看两个计划专属账本的最后一条记录。
3. 运行 `git status --short --branch` 和 `git log -10 --oneline`。
4. 已有 `Task N: complete` 记录的任务不得重做。
5. 从第一个没有完成记录的任务继续。
6. 每个任务通过测试后立即提交，并更新本文件及GitHub恢复分支。

不得通过重新初始化项目、复制旧版本目录、`git reset --hard` 或 `git checkout --` 恢复任务。
