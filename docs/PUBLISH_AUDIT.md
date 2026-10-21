# v8.3.5-preview.1 公开发行检查（2026-10-21）

## 文件与来源

- 原本地源码工作目录因工作区维护清理而不再存在；从已有GitHub仓库clone恢复，没有重建项目或覆盖旧策略。
- 原完整源码分支：codex/v8-phase1，起点68ab76dc605859e258ced85f77fa24c1f7fbfcd4。
- 原main仅包含首页文档；现在完整源码已合入main，初次集成提交30fb9d464eb191ad4309d95a72e935f180e19b60；最终受测发行提交3a2e0f940b4c4435ed83a431943f3f18e54b3dda。
- 集成后的源树当前含166个文件、106个Python文件；原src和windows_app未改变。README采用追加说明，原LICENSE字节保持不变。

## 安全检查范围与结果

- 对原154个跟踪文件、全部可达历史301个blob，以及准备发布的164个文件（后续仅新增审计文档及.gitattributes，最终166个文件），检查敏感路径和常见密钥/密码模式。
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

- 最终项目233项pytest通过（设置ASTOCK_V763_ARCHIVE，含审定v7.6.3旧包63项自检）。
- 公共clone不具备私人旧包时，该一项审计明确跳过；其余项目测试执行。
- 现有桌面71项unittest通过；旧ZIP和GPL发行ZIP各自重新解压71项自检通过。
- Linux offscreen真实Qt主窗口构造通过；发布工作流进一步在Windows执行同类检查，验证三级筛选页面实际加载。
- 独立发布审查确认原75个文件哈希不变；补齐标签指向受测提交的保护，四项标签测试已验证错提交拒绝、缺失创建、匹配只读、权限错误拒绝。

## Windows验证与实际边界

最终Windows工作流成功： https://github.com/Traveller06/AStockQuant/actions/runs/39543683515

- Windows10 runner、64位Python3.11.9：232项项目测试通过，1项私人历史包审计明确跳过。
- 71项桌面测试、真实Qt主窗口和三级筛选页面构造、独立解压71项自检全部成功。
- 发布页： https://github.com/Traveller06/AStockQuant/releases/tag/v8.3.5-preview.1 ，prerelease=true，draft=false。
- 发行tag严格指向受测3a2e0f940b4c4435ed83a431943f3f18e54b3dda。
- 已从公开下载链接取回全部4个附件，逐项匹配GitHub返回digest，并按SHA256SUMS重新核验；取回ZIP的原75个文件与审定清单相符，LICENSE与仓库相同。
- Windows公开ZIP SHA256：040cab2b15b8ee3d5d453783f64c9b447f21748cab6aa865c69c006e09a92a19，216485字节，79个文件。
- 不同平台zlib可能产生不同压缩字节；本地Linux与WindowsZIP的逐文件原程序内容一致，以公开Windows附件的校验值为准。
- 两次失败均被发布门禁拦截：第一次是Git检出CRLF转换，已用.gitattributes固定LF；第二次是缺失标签查询返回422，已改用标签引用查询并核对提交。均未分发失败构建。

对应源码、构建脚本和GPL说明已保存在同名tag；最终真实结果、依赖环境、校验值同时保存在Release的VALIDATION.json、requirements-tested.txt及SHA256SUMS.txt中。

安装包为Windows Python ZIP，需要64位Python（推荐3.11）与首次依赖安装网络，不是独立EXE或离线安装器。发布标记为prerelease；没有用户网络下人工实机全市场验收，也没有盈利或实盘可用声明。
