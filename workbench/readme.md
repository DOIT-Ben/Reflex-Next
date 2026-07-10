# Reflex Next 工作台

## 当前状态

项目已完成架构契约冻结、`reflex-core` Stage 1、Runtime Mock Sidecar、Figma Current 主浮窗重构，以及 Tauri/Rust Host 真实 Sidecar 桥接，当前进入桌面宿主能力补齐阶段。

当前主线基线：

- Figma `Current` 区域是唯一 UI 真值；
- `docs/UI-IMPLEMENTATION-SPEC.md` 已冻结 Figma、Tauri、Sidecar 和 Core 的实现契约；
- `docs/CODEX-DELIVERY-PLAN.md` 已冻结分阶段交付路线；
- `packages/reflex-core` 已具备稳定事件协议、请求规范化、取消语义、L0 场景规则、安全纯函数和无网络优化用例；
- `packages/reflex-runtime` 已具备 NDJSON 命令循环、Mock Provider、取消和多请求隔离；
- `apps/tauri-host` 已具备 Svelte + Vite 小浮窗、`CoreBridge` 抽象、Tauri API 适配层、Figma Current 主状态机、Rust 剪贴板命令、常驻 Python Runtime 管理、窗口内快捷键契约、错误恢复态和设置覆盖层；
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
- 当前机器 Rust 工具链可用，Rust 测试和 Tauri debug 构建已执行；
- Stage 1 已通过独立 QA 并合入 `main`。

## 下一阶段

进入 Stage 4：桌面宿主能力。

必须完成：

1. 实现单实例、托盘和全局快捷键；
2. 实现窗口显示、隐藏、聚焦和位置越界恢复；
3. 实现设置持久化与平台安全 SecretStore；
4. 保留 Mock Provider，不接真实 MiniMax；
5. 完成 Python Runtime 发布态自包含打包；
6. 补 125% / 150% DPI、多显示器和安装/卸载生命周期证据。
