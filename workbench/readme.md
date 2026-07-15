# Reflex Next 工作台

更新时间：2026-07-15

本文件提供项目内部交接入口。任务状态和完成证据以
`workbench/backend-production-tasks.md` 为唯一账本；迁移计划、开发记录和早期阶段计划只用于追溯。

## 当前阶段

项目处于 `v0.7.0-alpha.8` 生产化收尾阶段，不是正式稳定版。

- 阶段 0：13/13 完成；
- 阶段 1：14/14 完成；
- 阶段 2：10/11 完成，当前提交的构建物扫描和 SBOM Artifact 待复核；
- 阶段 3：7/8 完成，正式 72 小时浸泡待重新运行；
- 阶段 4：版本统一完成，Windows 10、真实升级、签名和发布候选仍在处理；
- 阶段 5：用户文档完成，受控试用、最终回归、签名包和 `v1.0.0` 尚未开始。

## 已实现范围

### Core 与 Runtime

- 稳定请求模型、事件信封、场景路由、模板渲染、安全校验和通用场景回退；
- 固定并发和等待队列、请求 ID 生命周期、总时限、输出和分片上限；
- Runtime NDJSON 命令循环、插件发现、取消、Sidecar 崩溃恢复和脱敏诊断；
- Core 导入不引入 PyQt、PySide、sqlite3、pyperclip、torch、sentence-transformers 或 huggingface-hub。

### Provider 与插件

- MiniMax 和 OpenAI-compatible Provider 的流式、取消、重试、断流和错误分类；
- 内置模板包、42 个场景和多风格渲染；
- 加密历史、翻译、批处理、Markdown 预览和可选语义识别；
- 历史恢复、轮换、大数据量性能和插件资源浸泡。

### 桌面宿主与前端

- Svelte/Vite 主界面、命令面板、设置、历史、结果对比和反馈面板；
- Rust Host、常驻 Sidecar、托盘、全局快捷键、窗口恢复和剪贴板策略；
- Windows Credential Manager、Tauri capability 白名单和外部导航限制；
- 动态 Provider/模型目录由 Runtime 提供，前端不维护重复真值。

### Reflex Cloud

- 匿名安装身份、隐私授权、免费额度和全局预算；
- 用户反馈、可选截图、提示词改进计划和数据删除；
- 管理端反馈分析、质量草稿、发布、回滚和曝光归因；
- PostgreSQL 多实例发布/回滚并发、唯一终态和 schema 清理验证；
- Cloud 默认本机端口为 `8787`，其他项目的 `8020` 服务不属于 Reflex Cloud。

## 当前验证基线

- Python：10 个项目按包隔离验证；Reflex Cloud 最近记录为 48 项通过；
- Rust/Tauri Host：194 项通过，3 项 Credential Manager 实机测试单独通过；
- 前端：26 个测试文件、168 项测试通过，Vite 生产构建 242 个模块；
- Runtime：本机 10,000 次短门禁通过，完成和取消各 5,000 次；
- Provider：真实 MiniMax 流式成功和取消通过，证据不保存正文或密钥；
- Cloud：PostgreSQL 16 独立测试库的并发发布和回滚通过；
- 安全：受版本控制文件敏感扫描、依赖审计、许可证和权限矩阵已有通过记录。

以上证据不能替代仍未完成的正式发布门禁。远端 CI 或旧提交的 Artifact 也不能自动证明当前提交通过。

## 未完成门禁

1. 正式 72 小时且至少 10,000 次请求/取消浸泡；
2. 当前提交对应的前端构建物扫描和 12 组件 SBOM Artifact 复核；
3. Windows 10 干净构建、安装、覆盖安装、卸载和重装；
4. 官方旧版包和真实旧数据的完整升级链路；
5. 实际代码签名、更新和回滚演练；
6. 受控试用、全量回归、签名安装包、回滚包和 `v1.0.0`。

## 工作区约束

- 根目录 `resources/` 是本地旧资产参考，不修改、不暂存；
- 根目录前端设计归档不进入版本库；
- `workbench` 下截图、日志和浸泡 JSON 是本地运行产物，不提交；
- `.env`、`.env.local`、凭据和真实用户数据不得读取或提交；
- 已有用户修改不得回滚、格式化或混入项目整理提交；
- 不创建正式安装包或 Tag，除非全部门禁满足并获得明确批准。

## 文档入口

- `docs/INDEX.md`：统一文档导航；
- `docs/ARCHITECTURE.md`：架构边界；
- `docs/MIGRATION.md`：迁移设计基线；
- `docs/BACKEND-PRODUCTION-GOAL.md`：长期完成标准；
- `docs/BACKEND-PRODUCTION-ROADMAP.md`：阶段门禁；
- `workbench/backend-production-tasks.md`：当前任务和证据；
- `docs/verification/`：可复核验证记录。

## 后续顺序

1. 在资源条件满足时重新运行正式 72 小时浸泡；
2. 为当前提交取得构建物扫描和 SBOM 证据；
3. 在 Windows 10 环境完成构建与安装生命周期；
4. 使用官方旧版本和脱敏真实数据完成升级验证；
5. 准备证书并完成签名、更新、回滚和 RC 审计；
6. 受控试用通过后再生成正式发布物和 `v1.0.0`。
