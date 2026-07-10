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

当前已建立 Svelte + Vite 前端原型，用于承接 Tauri 小浮窗体验。主界面已对齐 Figma `Current` 的 760×540 单浮窗结构。

覆盖画面：

- Default：输入内容、配置摘要和主操作
- Adjust：模式、风格、场景、模型调整
- Generating：流式生成和取消
- Complete：结果、复制、替换剪贴板和重新生成
- Copied：复制成功 Toast
- Clipboard Confirm：首次替换剪贴板确认
- Error：脱敏错误说明、重试、打开设置和复制诊断 ID
- Settings：默认 Provider、模型、模式、风格、场景策略、剪贴板策略和安全说明
- Clipboard Read：用户点击后读取剪贴板文本，失败时展示可理解错误

本切片只消费 Runtime/Core 事件流，不承载 Prompt 构建、Provider 请求或场景路由业务。

## Core Bridge

前端现在通过 `CoreBridge` 消费事件流，而不是在组件中直接绑定演示数据源。

当前实现：

- `DemoCoreBridge` 用于前端原型交互。
- `TauriRuntimeBridge` 用于 Tauri WebView 内通过 `invoke/listen` 消费 Runtime 事件。
- `tauriHostApi` 动态加载 `@tauri-apps/api/core` 和 `@tauri-apps/api/event`，浏览器预览不可用时自动回退演示桥。
- `parseNdjsonEvents` 可解析 Python sidecar 输出的 NDJSON 事件。
- `parseNdjsonEnvelopes` 和 `selectEventsForRequest` 用于按 `request_id` 丢弃迟到事件。
- `hostState` 负责 Host 状态机、调整草稿、事件映射、错误恢复元数据和迟到事件过滤。
- `settingsDraft` 只保存可展示默认值；真实 API Key 不进入前端状态。
- `mockCore` 支持成功链和 provider 不可用错误链，便于无网络验证 Error Recovery。
- UI reducer 同时兼容 `done.data.final_text` 与 `done.data.text`。
- `clipboardBridge` 优先调用 Tauri `read_clipboard_text`，浏览器预览时回退 `navigator.clipboard.readText`，并统一转换空内容和权限失败提示。
- Runtime 启动或写入失败时，`TauriRuntimeBridge` 会转换为固定中文错误事件，不向 UI 透传底层命令、路径或诊断文本。

## Rust Host 与 Runtime

`src-tauri` 已接入开发态 Python Runtime：

- `runtime_available` 检查仓库内 Runtime/Core 开发布局；
- `runtime_optimize` 与 `runtime_cancel` 校验协议版本、请求标识、命令类型和对象 payload；
- 首次请求启动一个常驻 Runtime 进程，后续请求复用同一进程；
- stdin/stdout 使用 UTF-8 NDJSON，stdout 事件通过 `reflex://core-event` 转发给前端；
- stderr 独立排空，用户可见错误统一转换为安全中文；
- Runtime 异常退出后在下一次请求时重启，并为未完成请求发送可恢复错误；
- 应用退出时先发送 `shutdown`，超时后只终止宿主自己创建的子进程；
- 剪贴板读取由 Rust Host 响应明确的用户操作，不在打开窗口时静默读取。

默认开发态启动命令为：

```text
uv run --python 3.12 --no-python-downloads --offline python -m reflex_runtime.cli
```

可通过以下环境变量覆盖：

- `REFLEX_RUNTIME_ROOT`：仓库根目录；
- `REFLEX_RUNTIME_PYTHON`：单一 Python 可执行文件路径。

当前仍使用无网络 Mock Provider，不读取 API Key，也不进行真实模型请求。发布态 Python 自包含打包尚未完成，因此当前可执行文件只用于仓库开发环境。

## 本地运行

```powershell
cd apps\tauri-host
npm install
npm test
npm run build
npm run dev -- --port 5173
npm run tauri:build -- --debug --no-bundle
```

Rust 测试：

```powershell
cd src-tauri
cargo test -- --test-threads=2
```
