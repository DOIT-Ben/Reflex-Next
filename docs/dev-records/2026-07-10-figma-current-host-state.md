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
- 补齐窗口内快捷键契约：
  - `Ctrl + Enter` 仅在可生成且非生成中触发生成。
  - 生成中重复 `Ctrl + Enter` 不会重复提交。
  - `Esc` 优先关闭剪贴板确认弹窗，其次退出调整面板，再取消生成或隐藏窗口。
- 取消生成后回到可执行输入态，不停留在不可恢复的 `cancelled` 画面。
- 移除旧左侧导航和双面板结构。
- 避免在用户可见 UI 中展示内部 `Mock` 命名。

## 验证

```powershell
cd apps\tauri-host
npm test
npm run build
npm audit --audit-level=moderate
```

结果：前端测试 22 passed，构建通过，审计 0 vulnerabilities。

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
- 键盘路径：`Ctrl + Enter` 可触发生成；`Esc` 可关闭确认弹窗和退出调整面板。

截图：

- `D:\Desktop\reflex-next-current-default.png`
- `D:\Desktop\reflex-next-current-adjust.png`
- `D:\Desktop\reflex-next-current-complete.png`
- `D:\Desktop\reflex-next-current-clipboard-confirm.png`
- `D:\Desktop\reflex-next-current-mobile.png`
- `D:\Desktop\reflex-next-current-empty-keyboard.png`
- `D:\Desktop\reflex-next-current-copied-keyboard.png`
- `D:\Desktop\reflex-next-current-clipboard-confirm-keyboard.png`
- `D:\Desktop\reflex-next-current-mobile-keyboard.png`

## 下一步

1. 补齐 Error 的专门界面和截图验收。
2. 初始化 Rust Host 后接入真实 `runtime_optimize/runtime_cancel`。
3. 继续实现托盘、剪贴板读取、设置页和 Rust 宿主窗口隐藏命令。
