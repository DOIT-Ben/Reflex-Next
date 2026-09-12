# 2026-07-10 Figma Current 主浮窗重构记录

## 目标

将 Tauri Host 前端从旧双面板演示页推进到 Figma `Current` 的 760×540 单浮窗主体验，并补齐 Host 状态机。

## 已完成

- 通过 Figma MCP 确认 `Version Zone / Current` 是唯一开发基线。
- 抓取并对齐 `Current / Default` 与 `Current / Adjust` 视觉结构。
- 新增 `hostState` 模块，覆盖：
  - `empty`
  - `ready`
  - `adjusting`
  - `analyzing_scene`
  - `connecting_provider`
  - `streaming`
  - `completed`
  - `cancelled`
  - `error`
- Host 按 `request_id` 丢弃迟到事件。
- 调整页使用草稿，取消不污染当前请求。
- `App.svelte` 重构为 Figma Current 单浮窗：
  - Default
  - Adjust
  - Generating
  - Complete
  - Copied Toast
  - Clipboard Confirm
  - Error Recovery
- 基于 Figma `Support / Settings / Provider` 转译为小浮窗内 Settings 覆盖层：
  - 默认 Provider / 模型
  - 默认模式 / 风格
  - 场景识别策略
  - 剪贴板策略
  - 安全与隐私说明
- Settings 只保存可展示默认值，API Key 仅以掩码呈现，不进入 Host 状态。
- 基于 Figma `Input Card` 接入显式读取剪贴板：
  - 用户点击“读取剪贴板”后才读取，不在窗口打开时静默读取。
  - Tauri 环境调用 `read_clipboard_text`。
  - 浏览器预览回退 `navigator.clipboard.readText`。
  - 空剪贴板和权限失败均显示用户可理解提示，不展示系统 API 原始异常。
- `mockCore` 增加 provider 不可用错误链，用于无网络触发错误态。
- Error UI 只展示脱敏错误说明、恢复动作、错误代码和诊断 ID 复制入口。
- 补齐窗口内快捷键契约：
  - `Ctrl + Enter` 仅在可生成且非生成中触发生成。
  - 生成中重复 `Ctrl + Enter` 不会重复提交。
  - `Esc` 优先关闭剪贴板确认弹窗，其次退出调整面板，再取消生成或隐藏窗口。
- 取消生成后回到可执行输入态，不停留在不可恢复的 `cancelled` 画面。
- 移除旧左侧导航和双面板结构。
- 避免在用户可见 UI 中展示内部 `Mock` 命名。

## Rust Host 补充

- 初始化 `apps\tauri-host\src-tauri`，接入 Tauri 2 Rust 宿主和剪贴板插件。
- 新增 `runtime_optimize`、`runtime_cancel` 与 `runtime_available` 命令及 capability 声明。
- Rust Host 首次请求启动并复用一个 Python Runtime，使用 UTF-8 NDJSON 转发命令和事件。
- Runtime stdout 事件统一发送为 `reflex://core-event`，stderr 独立排空且不进入用户界面。
- 命令校验和 Runtime 启动/写入失败只返回固定中文错误，不透传底层异常。
- 取消请求不伪造完成事件；Runtime 异常退出后可在下一次请求重启。
- 应用退出时发送 `shutdown`，超时后只终止宿主创建的子进程。
- 默认开发态通过离线 `uv` 命令使用 Python 3.12；可用 `REFLEX_RUNTIME_PYTHON` 覆盖单一 Python 可执行文件。
- 保留无网络 Mock Provider，未接真实 MiniMax、API Key 或付费调用。
- 修复 Runtime 启动失败时前端停留在生成态的问题，失败现在进入可重试 Error Recovery。
- 修复 760×540 宿主窗口双向滚动条；680×480 时默认页无横向或纵向溢出，长调整面板只在自身内容区滚动。

## 验证

```powershell
cd apps\tauri-host
npm test
npm run build
npm audit --audit-level=moderate
```

结果：前端 35 passed，构建通过，审计 0 vulnerabilities。

```powershell
cd apps\tauri-host\src-tauri
cargo test -- --test-threads=2
cargo clippy --all-targets -- -D warnings
```

结果：Rust 15 passed，Clippy 零警告。

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

- Default、Adjust、Complete、Clipboard Confirm 均可截图。
- 生成链路可跑通并输出结果。
- 移动端无横向溢出。
- Empty 专门截图：输入为空时主按钮禁用。
- Copied 专门截图：复制结果后出现 Toast。
- Error 专门截图：provider 不可用错误、恢复动作和诊断 ID 复制。
- Settings 专门截图：设置覆盖层、API Key 掩码、保存默认值和移动端无横向溢出。
- Clipboard Read 专门截图：点击读取剪贴板后，输入框内容和字数同步更新。
- 键盘路径：`Ctrl + Enter` 可触发生成；`Esc` 可关闭确认弹窗和退出调整面板。

Windows Tauri 实机验证：

- 760×540 Default 无页面滚动条，底部快捷键完整可见。
- 明确点击后可读取系统剪贴板文本。
- 冷启动可进入 Generating，完成后显示 Runtime/Core 结果。
- 生成中按 `Esc` 返回可执行输入态，未出现迟到完成画面。
- Runtime 暂不可用时进入脱敏 Error Recovery，恢复后“重试”可完成请求。
- 关闭应用后无残留 `reflex_runtime.cli`、`uv` 或 Python 子进程。
- 680×480 浏览器视口下页面 `scrollWidth/scrollHeight` 与视口一致，默认页无溢出；Adjust 仅内部纵向滚动。

截图：16 张本机运行产物（默认/调整/完成/剪贴板确认/移动端/键盘导航/错误态/设置浮层/剪贴板读取），不入库。

## 下一步

1. 实现托盘、全局快捷键、单实例和 Rust 宿主窗口显示/隐藏命令。
2. 实现设置持久化与平台安全 SecretStore，仍不把密钥放入前端状态或命令行。
3. 完成发布态 Python Runtime 自包含打包和安装/卸载生命周期验证。
4. 补 125% / 150% DPI、多显示器和完整流式录屏证据。
