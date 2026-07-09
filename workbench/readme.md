# Reflex Next 工作台

## 当前状态

项目已完成架构契约冻结、`reflex-core` Stage 1、Runtime Mock Sidecar、前端 Tauri API Bridge，以及 Figma Current 主浮窗重构，当前进入 Rust Host 真实桥接准备阶段。

当前主线基线：

- Figma `Current` 区域是唯一 UI 真值；
- `docs/UI-IMPLEMENTATION-SPEC.md` 已冻结 Figma、Tauri、Sidecar 和 Core 的实现契约；
- `docs/CODEX-DELIVERY-PLAN.md` 已冻结分阶段交付路线；
- `packages/reflex-core` 已具备稳定事件协议、请求规范化、取消语义、L0 场景规则、安全纯函数和无网络优化用例；
- `packages/reflex-runtime` 已具备 NDJSON 命令循环、Mock Provider、取消和多请求隔离；
- `apps/tauri-host` 已具备 Svelte + Vite 小浮窗、`CoreBridge` 抽象、Tauri API 适配层和 Figma Current 主状态机；
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
- 当前机器未安装 Rust 工具链，尚未运行 Rust Host 编译和测试；
- Stage 1 已通过独立 QA 并合入 `main`。

## 下一阶段

进入 Stage 3 前置：Tauri/Rust 真实桥接。

必须完成：

1. 安装或切换到可用 Rust 工具链；
2. 初始化 `apps\tauri-host\src-tauri`；
3. 用 Rust 启动和复用 `python -m reflex_runtime.cli`；
4. 保留 Mock Provider，不接真实 MiniMax；
5. 补 Rust 侧进程启动、事件读取、取消和退出测试；
6. 做 Figma Current 多状态截图证据。
