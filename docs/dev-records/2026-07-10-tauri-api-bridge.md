# 2026-07-10 Tauri API Bridge 记录

## 目标

在 Rust 工具链尚未就绪前，先完成前端到 Tauri API 的可测试桥接层，让 Svelte UI 可以在 Tauri WebView 中切换到真实 Runtime bridge。

## 已完成

- 新增 `TauriRuntimeBridge`，通过 Tauri Host API 调用 `runtime_optimize` 和 `runtime_cancel`。
- 新增 `TauriHostApi` 抽象，避免前端组件直接绑定具体 Tauri 包。
- 新增 `tauriHostApi` 适配层，动态加载 `@tauri-apps/api/core` 的 `invoke` 和 `@tauri-apps/api/event` 的 `listen`。
- `App.svelte` 在浏览器预览中继续使用 `DemoCoreBridge`，在 Tauri 环境检测到 API 后切换到 `TauriRuntimeBridge`。
- `TauriRuntimeBridge` 监听 `reflex://core-event`，按 `request_id` 过滤迟到事件。
- AbortSignal 触发时会发送 `runtime_cancel`。
- 新增前端单测覆盖 Tauri invoke/listen 适配、事件过滤、取消命令。

## 验证

```powershell
cd apps\tauri-host
npm test
npm run build
npm audit --audit-level=moderate
```

结果：前端测试 14 passed，构建通过，审计 0 vulnerabilities。

```powershell
cd packages\reflex-core
uv run --python 3.12 --with pytest pytest
```

结果：23 passed。

```powershell
cd packages\reflex-runtime
uv run --python 3.12 --with pytest pytest
```

结果：10 passed。

浏览器验证：

- 浏览器预览可回退到演示桥并完成一次优化。
- 桌面端事件时间线正常渲染。
- 移动端无横向溢出。

截图：本机运行产物，不入库。

## 当前限制

当前机器没有 `cargo` / `rustc` / `rustup`，因此本轮未创建可编译的 Rust Host，也未运行 `cargo test`。下一步需要先安装 Rust 工具链或切换到具备 Rust 的环境。

## 下一步

1. 初始化 `apps\tauri-host\src-tauri`。
2. 实现 Rust 命令 `runtime_optimize` 和 `runtime_cancel`。
3. Rust 侧启动并复用 `python -m reflex_runtime.cli`。
4. Rust 读取 Runtime stdout 后向前端发送 `reflex://core-event`。
5. 补 Rust 侧进程生命周期和取消测试。
