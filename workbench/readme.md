# Reflex Next 工作台

## 当前状态

项目已完成架构契约冻结与 `reflex-core` Stage 1，当前进入 Runtime Sidecar、Tauri Host 前端原型和真实桥接准备阶段。

当前主线基线：

- Figma `Current` 区域是唯一 UI 真值；
- `docs/UI-IMPLEMENTATION-SPEC.md` 已冻结 Figma、Tauri、Sidecar 和 Core 的实现契约；
- `docs/CODEX-DELIVERY-PLAN.md` 已冻结分阶段交付路线；
- `packages/reflex-core` 已具备稳定事件协议、请求规范化、取消语义、L0 场景规则、安全纯函数和无网络优化用例；
- `apps/tauri-host` 已具备 Svelte + Vite 小浮窗前端原型和 `CoreBridge` 抽象；
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
- Stage 1 已通过独立 QA 并合入 `main`。

## 下一阶段

进入 Stage 2：Runtime Sidecar 与 Tauri Host 真实桥接。

必须完成：

1. 建立 `packages/reflex-runtime`；
2. 定义 NDJSON stdin/stdout 命令与事件信封；
3. 实现 `optimize`、`cancel`、`ping`、`shutdown`；
4. stdout 只输出机器可解析协议，诊断仅写入脱敏 stderr；
5. 实现 Mock Provider、Mock Template Pack 和可控错误场景；
6. 把前端 `DemoCoreBridge` 替换为真实宿主 bridge；
7. 覆盖多请求隔离、取消、非法消息、协议版本和进程退出测试；
8. 暂不接真实 MiniMax。
