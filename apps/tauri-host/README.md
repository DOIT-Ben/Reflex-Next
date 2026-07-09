# Tauri Host

Tauri Host 是 Reflex Next 的轻量桌面外壳。

职责：

- 托盘
- 全局快捷键
- 小浮窗
- 剪贴板读写
- 设置入口
- 插件开关界面

禁止承载：

- Prompt 构建业务
- Provider 请求逻辑
- 场景识别逻辑
- 历史存储业务

宿主只消费 `reflex-core` 事件流，并把事件渲染给用户。

## 当前前端切片

当前已建立 Svelte + Vite 前端原型，用于承接 Tauri 小浮窗体验。

覆盖画面：

- 快捷浮窗输入区
- 模式、风格、场景、识别策略控制
- Core 事件流渲染区
- 完成态结果操作
- 最小设置入口
- 插件开关入口

本切片只模拟 Core 事件流，不承载 Prompt 构建、Provider 请求或场景路由业务。

## Core Bridge

前端现在通过 `CoreBridge` 消费事件流，而不是在组件中直接绑定演示数据源。

当前实现：

- `DemoCoreBridge` 用于前端原型交互。
- `TauriRuntimeBridge` 用于 Tauri WebView 内通过 `invoke/listen` 消费 Runtime 事件。
- `tauriHostApi` 动态加载 `@tauri-apps/api/core` 和 `@tauri-apps/api/event`，浏览器预览不可用时自动回退演示桥。
- `parseNdjsonEvents` 可解析 Python sidecar 输出的 NDJSON 事件。
- `parseNdjsonEnvelopes` 和 `selectEventsForRequest` 用于按 `request_id` 丢弃迟到事件。
- UI reducer 同时兼容 `done.data.final_text` 与 `done.data.text`。

下一步需要补齐 Tauri/Rust 宿主命令：启动 Python sidecar、转发 `runtime_optimize/runtime_cancel`、读取 stdout 事件流并向前端发送 `reflex://core-event`。

## 本地运行

```powershell
cd apps\tauri-host
npm install
npm test
npm run build
npm run dev -- --port 5173
```
