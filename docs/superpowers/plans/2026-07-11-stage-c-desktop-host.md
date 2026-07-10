# Stage C Desktop Host Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不把业务逻辑放入 Tauri Host 的前提下，实现 Windows 单实例、托盘、全局快捷键、窗口恢复和完整剪贴板策略。

**Architecture:** Rust Host 拥有系统级窗口、托盘、快捷键和剪贴板能力，并通过固定命令和 `reflex://host-action` 事件与 Svelte 交互。配置继续由 `ConfigStore` 原子保存；热键替换先注册新值，保存失败时回滚旧注册。前端只维护可见状态、最近结果和首次替换确认，不直接调用系统级快捷键或托盘 API。

**Tech Stack:** Tauri 2、Rust、`tauri-plugin-single-instance`、`tauri-plugin-global-shortcut`、`tauri-plugin-clipboard-manager`、Svelte 5、TypeScript、Vitest。

---

## Engineering Review

- **Stage:** `products-plan-eng-review`
- **Recommendation:** go
- **Architecture boundary:** 单实例、托盘、热键、窗口和剪贴板属于 Host；Core、Runtime、Provider 和模板不修改。
- **Data flow:** `AppConfig.hotkey` 经 Rust 校验和注册后持久化；托盘动作只发送稳定 action ID；剪贴板正文只在用户动作或已确认策略下通过 Tauri 命令传递。
- **Dependencies:** 只增加两个 Tauri 官方插件，并启用 Tauri `tray-icon` feature；不引入前端桌面插件或第二套状态框架。
- **Error handling:** 热键冲突、窗口 API 和剪贴板后端错误映射为固定消息；启动热键失败不退出应用；配置写入失败回滚旧热键。
- **Testability:** 几何恢复、热键状态机、Host action、剪贴板策略和配置迁移自动测试；单实例、托盘、跨应用热键和多显示器由 Windows 实机验证。
- **Key risk:** 系统热键状态与持久配置不一致。
- **Smallest correction:** 使用“注册新热键 -> 原子保存 -> 保存失败恢复旧热键”的事务顺序，并保留安全状态查询。
- **Gate:** continue

## Scope

包含：

- 单实例，第二次启动只显示并聚焦主窗口；
- 托盘打开、最近结果、插件、设置和退出入口；
- 可配置全局快捷键、冲突提示和失败回退；
- 显示、隐藏、聚焦、关闭到托盘和多显示器越界恢复；
- 剪贴板显式读取、复制、首次替换确认、启动读取和确认后的自动替换；
- 最近结果内存入口和最小插件状态视图；
- 阶段测试、Windows 实机证据、可见层审计、独立提交和推送。

不包含：

- 历史数据库或最近结果持久化；
- Provider、模板或场景业务修改；
- 第三方插件安装市场；
- 发布态 Sidecar 打包和安装器；
- 真实 Provider 付费调用。

### Task 1: Freeze Desktop Contracts

**Files:**
- Create: `apps/tauri-host/src-tauri/src/window.rs`
- Create: `apps/tauri-host/src-tauri/src/desktop.rs`
- Create: `apps/tauri-host/src/domain/desktopBridge.ts`
- Create: `apps/tauri-host/src/domain/desktopBridge.test.ts`

- [ ] **Step 1: Write failing Rust geometry tests**

测试负坐标多显示器、完全越界、窗口大于工作区和至少 64×64 可见区域。

- [ ] **Step 2: Verify RED**

Run: `cargo test window::tests -- --test-threads=2`

Expected: FAIL because `window` contract does not exist.

- [ ] **Step 3: Implement pure geometry and safe action/status types**

固定 action ID：`open`、`recent`、`plugins`、`settings`、`quit`。窗口错误和热键错误只返回固定中文消息，不包含系统 API 原始错误。

- [ ] **Step 4: Write and run failing/passing TypeScript contract tests**

Run: `$env:VITEST_MAX_WORKERS='2'; npm test -- --maxWorkers=2 src/domain/desktopBridge.test.ts`

- [ ] **Step 5: Commit**

`feat: 冻结桌面宿主行为契约 | v0.4.0-c1 | YYYY-MM-DD HH:MM`

### Task 2: Implement Window, Single Instance and Tray

**Files:**
- Modify: `apps/tauri-host/src-tauri/Cargo.toml`
- Modify: `apps/tauri-host/src-tauri/Cargo.lock`
- Modify: `apps/tauri-host/src-tauri/src/lib.rs`
- Modify: `apps/tauri-host/src-tauri/src/window.rs`
- Modify: `apps/tauri-host/src-tauri/src/desktop.rs`
- Modify: `apps/tauri-host/src-tauri/tauri.conf.json`

- [ ] **Step 1: Add official Tauri dependencies**

Use `tauri-plugin-single-instance = "2.4.2"`, `tauri-plugin-global-shortcut = "2.3.2"`, and `tauri = { version = "2.11.5", features = ["tray-icon"] }`.

- [ ] **Step 2: Register single-instance plugin first**

Secondary launches call one shared `show_main_window` helper; no second WebView or Sidecar is created.

- [ ] **Step 3: Build tray with stable menu IDs**

Menu labels: `打开 Reflex`、`最近结果`、`插件`、`设置`、`退出`。Open uses the window helper; recent/plugins/settings emit `reflex://host-action`; quit calls `app.exit(0)`.

- [ ] **Step 4: Close to tray and recover window bounds**

`CloseRequested` prevents destruction and hides `main`; show restores minimized state, clamps an off-screen position to a monitor work area, shows and focuses.

- [ ] **Step 5: Verify**

Run: `cargo test -- --test-threads=2; cargo build`

- [ ] **Step 6: Commit**

`feat: 实现单实例托盘与窗口管理 | v0.4.0-c2 | YYYY-MM-DD HH:MM`

### Task 3: Implement Transactional Global Hotkey

**Files:**
- Modify: `apps/tauri-host/src-tauri/src/desktop.rs`
- Modify: `apps/tauri-host/src-tauri/src/commands.rs`
- Modify: `apps/tauri-host/src-tauri/src/config_store.rs`
- Modify: `apps/tauri-host/src-tauri/src/lib.rs`
- Modify: `apps/tauri-host/src-tauri/capabilities/default.json`

- [ ] **Step 1: Write failing parser and replacement-state tests**

覆盖默认 `Ctrl+Alt+R`、空值、无修饰键、超长输入、冲突失败保留旧值和保存失败恢复旧值。

- [ ] **Step 2: Verify RED**

Run: `cargo test desktop::tests -- --test-threads=2`

- [ ] **Step 3: Implement DesktopState and plugin handler**

只在 `ShortcutState::Pressed` 显示窗口；启动注册失败只更新安全状态，不中止应用。公开 `desktop_status`，不向 WebView 暴露任意注册/注销命令。

- [ ] **Step 4: Make config save transactional**

标准化新配置，替换热键，原子保存；保存失败时尽力恢复旧热键。前端只收到固定的“快捷键不可用”或“配置存储暂不可用”消息。

- [ ] **Step 5: Verify**

Run: `cargo test -- --test-threads=2; cargo build`

- [ ] **Step 6: Commit**

`feat: 接入可回滚全局快捷键 | v0.4.0-c3 | YYYY-MM-DD HH:MM`

### Task 4: Complete Clipboard Write and Policy

**Files:**
- Modify: `apps/tauri-host/src-tauri/src/clipboard.rs`
- Modify: `apps/tauri-host/src-tauri/src/commands.rs`
- Modify: `apps/tauri-host/src-tauri/src/config_store.rs`
- Modify: `apps/tauri-host/src-tauri/src/lib.rs`
- Modify: `apps/tauri-host/src-tauri/capabilities/default.json`
- Modify: `apps/tauri-host/src/domain/clipboardBridge.ts`
- Modify: `apps/tauri-host/src/domain/clipboardBridge.test.ts`
- Modify: `apps/tauri-host/src/domain/settingsApi.ts`
- Modify: `apps/tauri-host/src/domain/settingsApi.test.ts`

- [ ] **Step 1: Write failing Rust writer and config migration tests**

覆盖原样写入、空结果拒绝、后端错误脱敏，以及缺失 `clipboard_replace_confirmed` 时安全回退 `false`。

- [ ] **Step 2: Verify RED and implement minimal Rust path**

公开 `write_clipboard_text`；正文不进入日志或错误。新增确认布尔字段并保持旧配置可迁移。

- [ ] **Step 3: Write failing frontend bridge tests**

覆盖 Tauri 优先、浏览器回退、写入失败固定消息和空文本拒绝。

- [ ] **Step 4: Implement bridge and verify GREEN**

Run: `$env:VITEST_MAX_WORKERS='2'; npm test -- --maxWorkers=2 src/domain/clipboardBridge.test.ts src/domain/settingsApi.test.ts`

- [ ] **Step 5: Commit**

`feat: 补齐剪贴板写入与确认配置 | v0.4.0-c4 | YYYY-MM-DD HH:MM`

### Task 5: Wire Desktop UX

**Files:**
- Modify: `apps/tauri-host/src/domain/hostState.ts`
- Modify: `apps/tauri-host/src/domain/hostState.test.ts`
- Modify: `apps/tauri-host/src/App.svelte`
- Modify: `apps/tauri-host/src/styles.css`

- [ ] **Step 1: Write failing state and policy tests**

覆盖 Host action、最近结果、插件覆盖层、启动读取一次、复制、首次替换确认、确认后直接替换和自动替换。

- [ ] **Step 2: Verify RED**

Run: `$env:VITEST_MAX_WORKERS='2'; npm test -- --maxWorkers=2`

- [ ] **Step 3: Implement desktop event handling and settings**

真实产品默认空输入；设置增加快捷键及状态；插件覆盖层只展示已接入插件、权限和管理入口；移除主界面的可见快捷键说明。

- [ ] **Step 4: Implement clipboard policy**

`startup` 只在宿主初始化后读取一次；`manual` 只响应明确动作；`auto_replace` 首次仍确认，确认后生成完成可自动替换。所有失败显示固定消息。

- [ ] **Step 5: Verify frontend and build**

Run: `$env:VITEST_MAX_WORKERS='2'; npm test -- --maxWorkers=2; npm run build`

- [ ] **Step 6: Commit**

`feat: 打通桌面动作与剪贴板策略 | v0.4.0-c5 | YYYY-MM-DD HH:MM`

### Task 6: Windows Evidence, Audit and Push

**Files:**
- Create: `docs/verification/stage-c-verification.md`
- Modify: `README.md`
- Modify: `workbench/readme.md`

- [ ] **Step 1: Run all automated checks**

```powershell
cd packages\reflex-core
uv run --python 3.12 --with pytest pytest -q

cd ..\reflex-runtime
uv run --python 3.12 --with pytest --with httpx pytest -q

cd ..\..\plugins\provider-minimax
uv run --python 3.12 --with pytest --with httpx pytest -q

cd ..\..\apps\tauri-host
$env:VITEST_MAX_WORKERS='2'
npm test -- --maxWorkers=2
npm run build
npm audit --omit=dev

cd src-tauri
cargo test -- --test-threads=2
cargo build
```

- [ ] **Step 2: Run Windows lifecycle checks**

真实验证第二实例、托盘五项、跨应用快捷键、快捷键冲突、关闭到托盘、Esc 隐藏、负坐标显示器恢复、剪贴板四条路径和退出无 Sidecar 残留。

- [ ] **Step 3: Run visible-layer and security audit**

检查 760×540、680×480、Empty、Complete、确认、设置和插件覆盖层；不得出现 Mock、debug、test、TODO、验收、工具名、内部目录或阶段标签。扫描生产凭据、权限、待推送路径和 `resources\` 基线。

- [ ] **Step 4: Code review and documentation commit**

`docs: 记录阶段 C 验证与回退 | v0.4.0-c6 | YYYY-MM-DD HH:MM`

- [ ] **Step 5: Push**

推送 `codex/full-feature-parity`；若远端前进则先停止并整合，不强推。

## Recovery

- 热键冲突：保留旧注册和旧配置，应用继续运行并从托盘打开。
- 托盘初始化失败：主窗口继续可用，记录不含系统原始错误的诊断。
- 窗口恢复失败：回退中心显示，不阻塞应用启动。
- 剪贴板失败：保留输入和结果，只显示固定错误，不自动重试覆盖。
- 桌面插件回归：按 C5 -> C4 -> C3 -> C2 逆序回退，不影响 Core、Runtime、Provider 和模板包。
