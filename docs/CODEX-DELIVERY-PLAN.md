# Reflex Next Codex 分阶段交付计划

更新时间：2026-07-09  
状态：待评审基线  
关联 Issue：#1  
前置规格：`docs/UI-IMPLEMENTATION-SPEC.md`

## 1. 执行原则

本计划用于指导 Codex 按小 PR 实施 Reflex Next，不允许一次性生成完整产品。

固定原则：

1. 先冻结契约，再写实现。
2. 先跑通无网络 Mock，再接真实 Provider。
3. Python Core、Runtime、Provider、Rust Host、Svelte UI 各守边界。
4. 每阶段独立 Issue、独立分支、独立 PR、独立验收。
5. 后续阶段不得偷偷补做前一阶段未通过的验收项。
6. 真实 API Key、付费调用、安装包发布和不可逆剪贴板策略必须显式确认。

## 2. 阶段总览

| 阶段 | Goal | 主要产物 | 是否调用真实网络 |
|---|---|---|---:|
| 0 | 规格冻结 | UI 契约、交付计划 | 否 |
| 1 | Core 事件与用例骨架 | 稳定事件协议、状态枚举、取消契约 | 否 |
| 2 | Runtime Sidecar 与 Mock 链路 | NDJSON CLI、Mock Provider/模板/事件 | 否 |
| 3 | Tauri/Svelte 主浮窗 | Figma Current 全状态、Mock 交互 | 否 |
| 4 | 桌面宿主能力 | 托盘、热键、剪贴板、设置、SecretStore | 否 |
| 5 | MiniMax 集成与发布前验收 | Provider 插件、真实流式联调、打包证据 | 是，需批准 |

依赖关系：

```text
阶段 0
  -> 阶段 1
      -> 阶段 2
          -> 阶段 3
              -> 阶段 4
                  -> 阶段 5
```

阶段 3 的纯视觉组件可以在阶段 2 后半段并行开发，但不得自行发明 Core 协议。

---

## 3. 阶段 0：规格冻结

### Goal

建立 Figma、Core 模型、事件流和 Tauri Host 之间的唯一实现契约。

### 允许修改

- `docs/UI-IMPLEMENTATION-SPEC.md`
- `docs/CODEX-DELIVERY-PLAN.md`
- 必要时更新 `workbench/readme.md` 的文档索引

### 禁止修改

- `packages/**` 业务代码
- `plugins/**`
- `template-packs/**`
- `apps/tauri-host/**` 实现代码
- CI、发布、密钥和 Provider 配置

### 验收

- 与 README、AGENTS、ARCHITECTURE、MIGRATION 一致；
- Figma Current 是唯一 UI 真值；
- 阶段 1–5 的边界可独立验收；
- 文档中不包含真实密钥和用户数据。

### Codex 指令

```text
任务：冻结 Reflex Next Figma 到 Tauri 的实现契约。

先读取：
- AGENTS.md
- README.md
- docs/ARCHITECTURE.md
- docs/MIGRATION.md
- docs/UI-IMPLEMENTATION-SPEC.md
- docs/CODEX-DELIVERY-PLAN.md

本任务只做 docs-only 审查和修正。不得创建 Tauri 工程，不得修改 Python Core，不得调用 Provider。
逐项核对 Figma 状态、Host/Core 边界、事件协议、窗口规则、剪贴板权限和阶段验收。
发现冲突时优先修正文档，不自行扩大范围。
```

---

## 4. 阶段 1：Core 事件与优化用例骨架

### Goal

让 `reflex-core` 具备稳定、无 UI、无网络的请求模型、事件协议、场景回退和取消语义，为 Host 提供不可歧义的契约。

### 必须完成

- `OptimizeRequest` 字段验证与规范化；
- 稳定 `EventType` / `StatusPhase` 枚举或等价常量；
- `status/scene/request/chunk/done/error/metric` 事件构造器；
- `request_id`、协议 `version` 和事件信封模型；
- `CancellationToken` 的最小抽象；
- `OptimizeUseCase` 骨架，可注入假的 SceneDetector、TemplateResolver、Provider；
- L0 场景识别失败回退 `general`；
- 输入校验、输出清洗、错误脱敏纯函数；
- 禁止依赖检查。

### 建议目录

```text
packages/reflex-core/src/reflex_core/
  protocol.py
  events.py
  models.py
  cancellation.py
  safety/
  scene/
  template/
  usecases/optimize.py
```

### 允许修改

- `packages/reflex-core/**`
- 对应测试
- 必要的架构文档勘误

### 禁止修改

- `apps/tauri-host/**`
- 真实 Provider
- SecretStore
- 剪贴板、托盘、快捷键
- SQLite、torch、sentence-transformers

### 自动验收

建议命令：

```bash
python -m pip install -e "packages/reflex-core[dev]"
python -m pytest packages/reflex-core/tests -q
```

必须覆盖：

- 默认请求规范化；
- 无效 mode/style/scene_policy；
- 正常事件顺序；
- 场景检测异常回退；
- 取消后不再产生有效 done；
- error 事件不包含模拟密钥；
- `import reflex_core` 后 `sys.modules` 不出现 PyQt、torch、sentence_transformers、sqlite3。

### 完成定义

无需网络即可用 Fake Provider 跑完：

```text
status -> scene -> request -> chunk -> done -> metric
```

### Codex 指令

```text
任务：实现 Reflex Core 的稳定事件协议和无网络优化用例骨架。

范围仅限 packages/reflex-core 与对应测试。
不要实现 MiniMax，不要创建 Tauri，不要导入桌面或重模型依赖。
先写失败测试，再实现：协议 version、request_id、状态 phase、事件信封、取消、场景回退、安全纯函数和依赖边界。
Fake Provider 必须可控地产生 chunk、error、cancel 和迟到事件。
完成后运行完整 core 测试并报告命令、结果、改动文件和剩余风险。
```

---

## 5. 阶段 2：Runtime Sidecar 与 Mock 链路

### Goal

建立 Rust Host 未来可稳定消费的 Python Sidecar 协议，但仍不连接真实 Provider。

### 必须完成

- 新建最小 `reflex-runtime` 或等价包；
- NDJSON stdin/stdout 协议；
- `optimize`、`cancel`、`ping`、`shutdown` 命令；
- 每条消息带 `version` 和 `request_id`；
- stdout 只输出协议事件，诊断写 stderr；
- Mock Provider、Mock Template Pack 和 Mock Event 场景；
- 进程级取消和迟到事件过滤；
- 非法消息、Sidecar 异常退出和协议版本不匹配处理；
- 生成可供 Tauri 测试启动的 CLI 入口。

### 建议目录

```text
packages/reflex-runtime/
  pyproject.toml
  src/reflex_runtime/
    cli.py
    protocol.py
    context.py
    mock_provider.py
    mock_template_pack.py
  tests/
```

### 允许修改

- `packages/reflex-runtime/**`
- 为支持协议而进行的最小 `packages/reflex-core/**` 调整
- 对应测试和文档

### 禁止修改

- Tauri 视觉界面
- MiniMax 真实 HTTP
- 系统 SecretStore
- 托盘、热键、剪贴板

### 自动验收

- 启动 Sidecar，写入一条 optimize NDJSON，收到完整事件链；
- 发送 cancel 后无有效 done；
- 混入非法 JSON 时返回脱敏协议错误，进程不泄露堆栈到 stdout；
- 两个 request_id 不串流；
- Mock error 覆盖未配置、不可用、超时和空结果。

### 手工证据

提交一份脱敏终端会话：

```text
command -> status -> scene -> request -> chunk -> done
```

### Codex 指令

```text
任务：实现 Reflex Runtime 的 NDJSON Sidecar 与 Mock Event Source。

先读取 UI-IMPLEMENTATION-SPEC 的 IPC 和事件映射章节。
只允许无网络 Mock；不得接真实 MiniMax。
stdout 必须保持机器可解析，不输出普通日志或堆栈；stderr 只输出脱敏诊断。
实现 optimize/cancel/ping/shutdown，并补多请求、取消、非法消息、协议版本和进程退出测试。
```

---

## 6. 阶段 3：Tauri/Svelte 主浮窗

### Goal

基于 Mock Sidecar 实现 Figma `Current` 全部状态，形成可点击、可流式、可取消的主体验。

### 必须完成

- 初始化 Tauri 2 + Svelte + TypeScript；
- 实现统一视觉令牌；
- 实现：Empty、Default、Adjust、Generating、Complete、Copied、Clipboard Confirm；
- 实现 Host 状态机与 Event Mapper；
- 实现 Mock Sidecar 桥接；
- `Ctrl+Enter`、`Esc` 和焦点行为；
- `request_id` 过滤迟到事件；
- Provider/模型状态只作摘要，不在默认页铺开参数；
- 错误状态包含重试和前往设置动作；
- 不实现真实托盘、热键、SecretStore 和 Provider。

### 允许修改

- `apps/tauri-host/**`
- Mock 契约适配所需的小范围 runtime 测试修正
- UI 文档勘误

### 禁止修改

- Core Prompt 业务
- 真实 Provider
- 历史数据库
- 大工作台功能
- 本地语义模型

### 自动验收

建议命令根据初始化工具确定，至少包括：

```bash
npm run test
npm run check
npm run build
cargo test --manifest-path apps/tauri-host/src-tauri/Cargo.toml
```

必须覆盖：

- 空输入禁用；
- 调整字段映射；
- status/scene/request/chunk/done/error；
- cancel；
- 迟到 chunk；
- Copy Toast；
- Clipboard Confirm；
- Error Recovery。

### 视觉证据

- 760×540：100%、125%、150%；
- 680×480 最小尺寸；
- 7 个 Figma Current 状态截图；
- 一段完整 Mock 流式录屏。

### Codex 指令

```text
任务：用 Tauri 2 + Svelte + TypeScript 实现 Reflex Next 当前 Figma 主浮窗。

必须以 docs/UI-IMPLEMENTATION-SPEC.md 为准。
默认页只保留输入、配置摘要、调整入口和唯一主按钮；禁止重新铺开表单或加入旧工作台功能。
先用 Mock Sidecar 完成全部状态和交互，不调用真实 Provider。
完成后运行前端、Rust 测试与构建，并交付 DPI/最小尺寸截图和流式录屏证据。
```

---

## 7. 阶段 4：桌面宿主能力

### Goal

补齐真正的轻量桌面体验：托盘、全局快捷键、剪贴板、设置和 SecretStore。

### 必须完成

- 单实例窗口显示、隐藏和聚焦；
- Tauri 全局快捷键注册、冲突和失败回退；
- 托盘菜单：打开、最近结果、插件管理、设置、退出；
- 剪贴板显式读取、复制和首次替换确认；
- 设置：默认 Provider/模型/模式/风格/场景策略/剪贴板策略；
- 平台安全 SecretStore 适配；
- Secret 仅通过匿名管道内存传给 Sidecar；
- 最近一次结果只保留轻量本地状态，不建大历史库；
- 权限声明与错误转换。

### 允许修改

- `apps/tauri-host/**`
- `packages/reflex-runtime/**` 的 Secret 注入协议
- 配置与权限文档

### 禁止修改

- Provider 请求实现
- 模板和场景业务
- SQLite 大历史
- 自动替换剪贴板默认开启
- 复杂插件市场

### 自动验收

- 单实例；
- 热键注册成功和冲突；
- 托盘入口；
- 剪贴板读写错误；
- Secret 不进入前端 store、localStorage、命令行和日志；
- 设置迁移和非法值回退。

### 手工验收

Windows 实机验证：

1. 从托盘打开和隐藏；
2. 全局快捷键从其他应用呼出；
3. 多显示器和窗口越界恢复；
4. 复制与首次替换确认；
5. 未配置 Provider 时进入可恢复错误；
6. 退出后无残留 Sidecar 进程。

### Codex 指令

```text
任务：实现 Reflex Next 的 Tauri 桌面宿主能力。

仅处理窗口、托盘、全局快捷键、剪贴板、设置和 SecretStore。
不得实现 Provider、模板、场景识别或历史数据库。
API Key 不得进入命令行、环境日志、前端 store 或 localStorage；只允许通过匿名管道内存传递给 Sidecar。
必须提交 Windows 实机手工验收证据。
```

---

## 8. 阶段 5：MiniMax Provider 集成与发布前验收

### 前置人工门禁

开始前必须获得用户明确批准，因为该阶段可能涉及：

- 真实 API Key；
- 付费 Provider；
- 外部网络；
- 安装包和发布产物。

### Goal

实现 MiniMax Provider 插件并完成端到端真实流式联调，不破坏 Mock 和 Core 边界。

### 必须完成

- ProviderPlugin 协议实现；
- MiniMax 请求字段映射；
- 流式解析和取消；
- 超时、限流、鉴权、网络和服务端错误分类；
- Provider 错误统一脱敏；
- 内置模板包最小场景；
- Host/Core/Runtime/Provider 端到端联调；
- Mock 模式继续可用；
- 安装包启动、关闭和 Sidecar 生命周期验证。

### 禁止事项

- 测试中硬编码真实密钥；
- CI 调用付费 API；
- 记录完整 Prompt；
- 用 Provider 原始异常直接展示给用户；
- 为赶进度把 Prompt 或场景逻辑塞进 Provider。

### 自动验收

默认 CI 只使用 Mock/录制夹具，不调用真实网络。

真实 smoke 由人工环境执行，并记录：

- Provider/模型；
- 请求时间；
- 首包时间；
- 完成时间；
- 取消行为；
- 脱敏错误样例；
- 安装包版本和系统环境。

### Codex 指令

```text
任务：实现 MiniMax Provider 插件并完成受控真实联调。

这是带外部调用的高风险阶段。开始前确认已获批准，且密钥只存在平台安全存储。
CI 只能使用 Mock 或脱敏夹具；真实 smoke 单独运行。
Provider 只负责协议适配和流式解析，不负责模板、场景、历史或 UI。
交付完整测试、脱敏日志、取消证据、真实 smoke 记录和安装包生命周期证据。
```

---

## 9. PR 通用模板

每个阶段 PR 至少写明：

```markdown
## Goal

## Linked Issue

## Scope

## Explicit Non-goals

## Changed Files

## Test Commands and Results

## Manual Evidence

## Security / Privacy Impact

## Remaining Risks

## Rollback
```

不得只写“已完成”或“测试通过”。

## 10. 独立 QA 清单

独立 QA 不接受开发者自证，至少核对：

- diff 是否突破 Issue 边界；
- 规格、代码、测试是否一致；
- Mock 与真实协议是否漂移；
- Host 是否偷偷承载 Core 业务；
- API Key、Prompt、Provider 错误是否可能泄露；
- 取消、错误、迟到事件和进程退出是否有覆盖；
- Figma 默认页是否重新退化成多参数表单；
- CI 命令和手工证据是否真实可复现。

只有独立 QA 给出 PASS，阶段才允许合并。