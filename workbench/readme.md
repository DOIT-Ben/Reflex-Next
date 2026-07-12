# Reflex Next 工作台

## 当前状态

项目已完成架构契约冻结、`reflex-core` 基础主链、Figma Current 主浮窗重构、Tauri/Rust Host 真实 Sidecar 桥接、安全配置与 MiniMax Provider 离线主链、内置模板包和 42 场景接入，以及桌面宿主能力补齐。当前进入插件能力接入阶段。

当前主线基线：

- Figma `Current` 区域是唯一 UI 真值；
- `docs/UI-IMPLEMENTATION-SPEC.md` 已冻结 Figma、Tauri、Sidecar 和 Core 的实现契约；
- `docs/CODEX-DELIVERY-PLAN.md` 已冻结分阶段交付路线；
- `packages/reflex-core` 已具备稳定事件协议、请求规范化、取消语义、覆盖 42 场景的 L0 规则、安全纯函数、模板包校验和无网络优化用例；
- `packages/reflex-runtime` 已具备 NDJSON 命令循环、Provider 插件发现与注册、私有配置、显式开发 Mock、取消和多请求隔离；
- `plugins/provider-minimax` 已具备 SSE/JSON 解析、取消、有限重试和稳定安全错误映射；
- `template-packs/builtin` 已具备 42 个场景、5 个风格、系统模板、版本化 manifest 和加载失败回退；
- `apps/tauri-host` 已具备 Svelte + Vite 小浮窗、`CoreBridge` 抽象、Tauri API 适配层、Figma Current 主状态机、42 场景手动选择、常驻 Python Runtime 管理、设置持久化、Windows 安全凭据、单实例、托盘、全局快捷键、窗口恢复和完整剪贴板策略；
- Core 自动测试已覆盖导入边界、事件协议、优化用例、安全、场景和 sidecar；
- Core 导入不引入 PyQt、PySide、sqlite3、pyperclip、torch、sentence-transformers 或 huggingface-hub。

## 当前可交接资料

- `README.md`
- `AGENTS.md`
- `docs/ARCHITECTURE.md`
- `docs/MIGRATION.md`
- `docs/CLASSIC-REFERENCE.md`
- `docs/UI-IMPLEMENTATION-SPEC.md`
- `docs/CODEX-DELIVERY-PLAN.md`
- `docs/dev-records/2026-07-10-core-and-host-bridge.md`
- `docs/dev-records/2026-07-10-runtime-sidecar.md`
- `docs/dev-records/2026-07-10-tauri-api-bridge.md`
- `docs/dev-records/2026-07-10-figma-current-host-state.md`
- `docs/verification/stage-a-verification.md`
- `docs/verification/stage-b-verification.md`
- `docs/verification/stage-c-verification.md`
- `workbench/known-pitfalls.md`

## 最近变更摘要

- 合并 Figma 到 Tauri 的实现契约与 Codex 分阶段交付计划；
- 完成 `OptimizeRequest` 规范化与稳定事件模型；
- 完成 `PROTOCOL_VERSION`、`request_id` 和 `EventEnvelope`；
- 完成可注入的 `OptimizeUseCase`、`CancellationToken` 和确定性测试假件；
- 完成零依赖 L0 场景规则与 `general` 回退；
- 完成输入校验、响应清洗、错误脱敏和禁止依赖测试；
- 完成 Tauri Host 前端原型、事件流渲染、设置页和插件页；
- 完成前端 `CoreBridge` 抽象和 sidecar NDJSON 解析；
- 完成 `packages/reflex-runtime` 的 `optimize/cancel/ping/shutdown` 命令循环；
- 完成 Runtime Mock Provider、进程级测试、多请求隔离和取消测试；
- 完成前端 Runtime 命令信封创建与 `request_id` 过滤；
- 完成前端 `TauriRuntimeBridge`、`tauriHostApi` 适配和 `runtime_cancel` 触发；
- 完成 Figma Current 单浮窗主体验、Host 状态机、调整草稿和剪贴板确认弹窗；
- 完成窗口内 `Ctrl + Enter` / `Esc` 快捷键解析、取消回到可执行态、Empty/Copied 专门截图验证；
- 完成 Error Recovery UI、provider 不可用 Mock 错误链、诊断 ID 复制和错误态截图验证；
- 完成 Settings 覆盖层、默认值保存、API Key 掩码呈现和移动端截图验证；
- 完成显式读取剪贴板前端桥接、空内容/权限失败提示和桌面/移动端截图验证；
- 完成 Tauri 2 Rust Host 初始化、命令权限声明和真实系统剪贴板读取；
- 完成 `runtime_optimize/runtime_cancel` 命令校验、常驻 Sidecar 启动复用、stdout 事件转发和 stderr 排空；
- 完成 Runtime 异常退出重启、未完成请求安全错误、取消和应用退出清理；
- 完成 Runtime 启动失败到前端可恢复错误态的转换，不透传底层诊断；
- 完成 760×540 与 680×480 布局溢出修复和可见状态复验；
- 完成版本化配置迁移、原子替换、有效备份恢复和非法值回退；
- 完成 Windows Credential Manager 安全存储，前端只读取配置状态；
- 完成 Provider 插件白名单发现、失败隔离、注册与显式 Mock；
- 完成 MiniMax SSE/JSON、取消、有限重试和安全错误分类；
- 完成设置页持久配置、密钥保存/删除和 Tauri capability 权限闭环；
- 完成内置模板包 manifest、安全加载、双模式、风格、场景和语言渲染；
- 完成 48 份模板资产迁移与逐文件哈希核对，未使用或修改当前仓库的未跟踪 `resources\`；
- 完成 L0 规则识别扩展到 42 个场景，并保持低置信 `general` 回退；
- 完成 Runtime 固定内置模板包接线和端到端渲染契约测试；
- 完成 Tauri 调整页 42 场景选择、自动/手动策略联动和语言元数据传递；
- 完成 Windows 单实例、托盘入口、关闭到托盘、全局快捷键和窗口越界恢复；
- 完成热键两阶段事务、并发串行化、冲突提示和配置保存失败回滚；
- 完成启动读取、显式读取、复制、首次替换确认和确认后自动替换剪贴板策略；
- 完成最近结果内存恢复、插件内置能力视图和桌面动作事件接线；
- 完成结果原文对比、原文/结果独立复制和历史缺失原文时的安全禁用；
- 完成批处理 CSV/TXT 文件导入、样例模板下载和导入源变更时的旧任务失效保护；
- 完成开发端口冲突快速失败，避免 Tauri 静默加载错误本地页面；
- 当前机器 Rust 工具链可用，Rust 测试和桌面开发构建已执行；
- 基础主链已通过独立 QA 并合入 `main`。

## 下一阶段

进入插件能力接入；真实 MiniMax 冒烟仍作为需要用户在设置页手动录入密钥的独立门禁保留。

必须完成：

1. 由用户在设置页手动配置密钥，完成一次真实 MiniMax 流式请求和取消；
2. 按插件边界接入历史、结果增强、批处理、语义识别和后续 Provider；
3. 完成 Python Runtime 发布态自包含打包及安装生命周期验证。
