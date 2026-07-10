# 桌面宿主能力验证记录

更新日期：2026-07-11

## 结论

Windows 单实例、全局快捷键、窗口显示与隐藏、关闭到托盘、剪贴板策略、最近结果和插件入口已接入 Tauri 宿主。系统能力保留在 Rust Host，Core、Runtime、Provider 和模板包边界未变化。

真实 MiniMax 请求仍需用户在应用设置页手动保存密钥后执行。本轮未读取或导入聊天记录、文件、命令或环境变量中的凭据。

## 自动化结果

| 范围 | 命令 | 结果 |
|---|---|---|
| Core | `uv run --python 3.12 --with pytest pytest -q` | 75 passed |
| Runtime | `uv run --python 3.12 --with pytest --with httpx pytest -q` | 32 passed |
| MiniMax Provider | `uv run --python 3.12 --with pytest --with httpx pytest -q` | 18 passed |
| 前端 | `$env:VITEST_MAX_WORKERS='2'; npm test -- --maxWorkers=2` | 49 passed |
| 前端构建 | `npm run build` | 通过 |
| 前端生产依赖 | `npm audit --omit=dev` | 0 vulnerabilities |
| Rust Host | `cargo test -- --test-threads=2` | 47 passed，2 个 Windows 凭据探针按默认忽略 |
| Rust 构建 | `cargo build` | 通过 |

覆盖重点：

- 负坐标显示器、完全越界、最小可见区域和超大窗口恢复；
- 固定托盘动作 ID、热键语法、冲突、两阶段保存、回滚清理失败和并发串行化；
- 配置迁移、确认状态持久化、剪贴板读写错误脱敏和空内容拒绝；
- 活动生成隔离最近结果，取消下一次生成后仍可恢复上一条完成结果；
- 设置、插件和剪贴板确认覆盖层拦截生成快捷键；
- Tauri 命令 manifest、invoke handler 和 capability 权限一致；
- 开发端口被占用时直接失败，不自动漂移到与 Tauri 开发地址不一致的端口。

## Windows 实机检查

- 启动第二个可执行文件后仍只有一个 Reflex 进程入口和一个主窗口，已有窗口被显示并聚焦。
- 从记事本前台按 `Ctrl+Alt+R` 可唤回 Reflex；关闭主窗口后进程继续存在，再次按快捷键可恢复窗口。
- 设置页显示当前快捷键已启用；尝试保存系统保留组合时只显示固定错误，取消并重开后仍为 `Ctrl+Alt+R`，旧配置和旧注册保持一致。
- 系统剪贴板中的无敏感测试文本可通过宿主命令读入输入框；浏览器回退路径完成复制和首次替换确认；Rust 后端覆盖原样写入、空值拒绝和错误脱敏。
- 托盘初始化成功是关闭到托盘的前置条件；托盘五项菜单和固定动作 ID 由 Rust 合约测试覆盖。当前自动化接口不能直接操作 Windows 通知区域，菜单逐项点击保留为发布前人工检查。
- 退出测试环境后，Reflex、Vite 和 Python Runtime/Sidecar 残留进程均为 0。

## 可见层检查

- `760×540` 和 `680×480` 的空输入、完成、设置和首次替换确认状态无页面级横向或纵向溢出。
- 较小窗口的长内容由视图内部滚动承载；按钮、输入框、设置导航和确认操作无重叠。
- 插件视图只描述内置能力和访问范围，不把静态清单宣称为实时可用状态，并提供设置管理入口。
- 页面和浏览器控制台未出现 Mock、debug、test、TODO、验收、工具名、内部目录或阶段标签；警告和错误日志为 0。

## 安全与边界

- 单实例、托盘、热键、窗口和剪贴板均位于 Rust Host；Tauri WebView 只消费固定命令和 `reflex://host-action` 事件。
- 热键变更在一个事务锁内执行：先注册新值，配置保存成功后才注销旧值；失败时旧值始终保持，清理失败只返回固定状态。
- Provider 错误、桌面错误和剪贴板错误不透传系统后端细节，剪贴板正文不进入日志或配置。
- 生产代码与文档未发现真实 API Key、Bearer 值或 Authorization 值；命中的 `sk-test` 仅存在于脱敏测试夹具。
- `resources\` 保持 27 个文件，聚合 SHA-256 为 `3BAF82F50AA911BBC68DE1851741BD5B14AF06D3D1E6F5B994D90E761A5B236D`，未暂存且不进入提交。

## 回退与恢复

- 热键冲突：保留旧注册和旧配置，从托盘或旧快捷键继续打开应用。
- 托盘初始化失败：不拦截窗口关闭，主窗口可正常退出，避免隐藏后无法恢复。
- 窗口恢复失败：继续显示窗口，不阻塞主链。
- 剪贴板失败：保留输入和结果，仅显示固定错误，不自动重试覆盖。
- 桌面宿主能力可整体回退，不影响 Core、Runtime、Provider 和模板包。
