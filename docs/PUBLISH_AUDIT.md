# v8.3.5-preview.1 公开发行检查（2026-10-21）

## 文件与来源

- 原本地源码工作目录因工作区维护清理而不再存在；从已有GitHub仓库clone恢复，没有重建项目或覆盖旧策略。
- 原完整源码分支：codex/v8-phase1，起点68ab76dc605859e258ced85f77fa24c1f7fbfcd4。
- 原main仅包含首页文档；现在完整源码已合入main，受测提交30fb9d464eb191ad4309d95a72e935f180e19b60。
- 集成后的源树含164个文件、106个Python文件；原src和windows_app未改变。README采用追加说明，原LICENSE字节保持不变。

## 安全检查范围与结果

- 对原154个跟踪文件、全部可达历史301个blob，以及准备发布的164个文件，检查敏感路径和常见密钥/密码模式。
- 检查内容包括GitHub/AWS/OpenAI常见密钥形式、私钥头、带凭据URL、字面量API密钥/密码/券商账户赋值，以及cache、v8_runs、个人持仓/账户、数据库、环境文件等私有路径。
- 没有发现候选项。结果表示这些范围内的模式检查未发现问题，不等价于形式化安全证明。
- 缓存、个人账户、交易明细、下载行情、私人旧上传包不随源码提交或发行包公开。
- Actions使用临时GITHUB_TOKEN；没有向用户索取、写入源码或公开任何个人令牌。

## 原安装包与发行包

- 原v8.3.5 ZIP SHA256：178076bb54eff3d8a01d882d23a7e413be5a8aec00fc150500aaab1f58f2802c。
- 原75个程序文件均与恢复源码逐字节相同，校验清单见release/v8.3.5-original-payload-sha256.json。
- GPL发行包仅增加LICENSE、BUILDING.md、THIRD_PARTY_NOTICES.md、SOURCE_INFO.txt，共79个文件。
- 本地发行ZIP SHA256：610f2ae17d3a5765d020cff608f04dbbbe7b59cc5f0dfc50ff46500bc7192c43。
- 不将ZIP提交到源码Git树；在GitHub Releases作为附件分发。Windows构建后再独立确认其校验值。

## 已执行的本地验证

- 最终项目232项pytest通过（设置ASTOCK_V763_ARCHIVE，含审定v7.6.3旧包63项自检）。
- 公共clone不具备私人旧包时，该一项审计明确跳过；其余项目测试执行。
- 现有桌面71项unittest通过；旧ZIP和GPL发行ZIP各自重新解压71项自检通过。
- Linux offscreen真实Qt主窗口构造通过；发布工作流进一步在Windows执行同类检查，验证三级筛选页面实际加载。
- 独立发布审查确认原75个文件哈希不变；补齐标签指向受测提交的保护，四项标签测试已验证错提交拒绝、缺失创建、匹配只读、权限错误拒绝。

## Windows验证与实际边界

Windows工作流： https://github.com/Traveller06/AStockQuant/actions/runs/39543141748

此文件记录提交时Windows流程仍在运行。最终真实结果以工作流及Release附件VALIDATION.json为准；测试失败会阻止发布。相应源码由v8.3.5-preview.1 tag固定，标签不同于受测SHA时拒绝发布。

安装包为Windows Python ZIP，需要64位Python（推荐3.11）与首次依赖安装网络，不是独立EXE或离线安装器。发布标记为prerelease；没有用户网络下人工实机全市场验收，也没有盈利或实盘可用声明。
