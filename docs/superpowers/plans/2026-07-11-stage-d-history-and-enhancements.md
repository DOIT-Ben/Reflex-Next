# Stage D History and Result Enhancements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不扩张 Core 和主浮窗职责的前提下，交付可恢复的加密历史、流式翻译与安全 Markdown 预览，并让用户能从独立工作视图管理这些能力。

**Architecture:** Runtime 增加独立于 Core 事件的受限能力插件通道；Rust Host 独占历史主密钥、应用数据路径和文件选择；三个增强插件分别拥有存储、翻译和 Markdown 逻辑。Core 只新增历史保存前的纯脱敏策略，不感知数据库或插件。Svelte 主浮窗只保留结构化当前结果与按需动作，历史使用独立 Tauri 窗口，所有插件事件按 `request_id` 隔离。

**Tech Stack:** Python 3.12、Runtime NDJSON、Python entry points、SQLite、`cryptography` AES-GCM、`markdown-it-py`、`bleach`、Tauri 2、Rust、Windows Credential Manager、Svelte 5、TypeScript、Vitest、pytest。

---

## Product Planning Gate

- **Stage:** `products-writing-plans`
- **Goal:** 完整实现阶段 D 的历史、翻译与 Markdown 结果增强，同时保持 Core 零桌面/零 SQLite 依赖。
- **Included:** 插件发现与状态、受限 RPC、配置 v2、安全密钥、历史全生命周期、独立历史窗口、结果动作、翻译、Markdown、导出、修复、验证和回退。
- **Excluded:** 旧数据库自动改写、第三方插件市场、批处理、语义模型、安装器、真实 Provider 付费冒烟。
- **Gate:** continue
- **Next:** `products-plan-eng-review`

## Engineering Review

- **Stage:** `products-plan-eng-review`
- **Recommendation:** go
- **Architecture boundary:** SQLite、AES-GCM 和 Markdown 依赖只进入各自插件；Runtime 只拥有插件契约、任务调度和 Provider 网关；Rust Host 拥有凭据、路径、窗口和文件选择；Core 只提供无 I/O 的可配置历史脱敏纯函数。
- **Data flow:** WebView 只提交受限 `plugin_id + operation + payload`；Rust 校验并补充私有配置；Runtime 按白名单分派并通过 `reflex://plugin-event` 返回结构化事件。历史密钥只沿 Rust 内存到 Runtime stdin 的私有命令传递。
- **Dependencies:** Runtime 默认依赖不增加 SQLite、加密或 Markdown 包；三个插件分别声明依赖，Runtime 只提供 `builtins` 可选依赖用于开发与发布打包。
- **Error handling:** 插件发现失败不阻止 Runtime；历史不可用不影响优化结果；坏密文降级并可隔离；翻译取消不污染主结果；Markdown 清洗失败只返回固定错误。
- **Testability:** 协议、注册表、加密仓库、迁移、恢复、翻译流、清洗、窗口单实例和前端状态均可自动测试；真实窗口、导出文件和 Windows Credential Manager 做实机验证。
- **Key risk:** 历史密钥、数据库和多代备份在轮换中失去一致性。
- **Smallest correction:** 使用 Credential Manager 版本化密钥环、SQLite Online Backup API、分阶段轮换日志和写入冻结；成功后提升新版本但保留仍被备份引用的旧 key，启动时恢复或继续未完成轮换。
- **Gate:** continue
- **Next:** `products-test-driven-development`

## Security Review

- 历史输入和输出分别使用 256-bit AES-GCM、独立 96-bit 随机 nonce。AAD 固定为 domain、schema_version、key_version、field_role(input/output) 和 canonical_metadata_hash；每个字段带类型与 null 标记，字符串使用长度前缀 UTF-8，整数使用大端编码，禁止直接拼接。
- SQL 只使用参数绑定；排序、筛选字段和导出格式只接受固定枚举。
- 数据库、配置、备份、日志、事件错误和修复摘要不得包含密钥；列表摘要不得返回正文。
- v1 中的 `history_enabled=true` 从未产生真实历史写入，不能作为用户同意；迁移 v2 时强制设为 `false`，之后仅保存用户显式开关。
- 默认历史脱敏策略为 `secrets`，在加密前由 Core 隐藏 API Key、Bearer Token 等已知敏感模式；用户只有显式选择 `none` 才保存未经该策略处理的正文。
- 历史关闭或隐私模式开启时，Runtime 必须拒绝 `save`，前端判断不能成为唯一防线。
- Markdown 禁止原始 HTML、脚本、事件属性、危险 URI、图片和远程嵌入；WebView 拦截预览链接导航。
- Rust 不向 WebView 暴露 `configure_plugin`、历史密钥、数据库路径、备份路径或任意文件写入命令。删除、清空、恢复和轮换由 Rust 按窗口标签授权并显示原生确认，前端布尔值不构成授权。
- 所有插件错误、Provider 错误和诊断只输出固定分类、`request_id` 和不含正文的计数。
- Runtime CLI 在导入插件前用 OS `dup` 保存协议 fd，再以 `dup2` 重定向进程 fd 1/2，并同步替换 `sys.stdout/sys.stderr/sys.__stdout__/sys.__stderr__`；协议 writer 只持有复制后的私有 fd。插件事件只能由 Runtime 构造，无法归属的协议污染使全部活动请求失败并重启 Sidecar。
- Tauri 使用显式 CSP 和导航策略：只加载本地应用资源，拒绝远程页面、frame、object、form、任意新窗口和非白名单导航；外链不得由 WebView 自行打开。

## Stable Contracts

### Runtime command envelope

所有命令继续使用：

```json
{"version":1,"request_id":"req-id","type":"plugin_call","payload":{}}
```

新增 wire command：

- `list_plugins`：公开只读，payload 必须为空对象；
- `plugin_call`：公开但经 Rust 窗口/操作授权矩阵与 Runtime 白名单双重校验；
- `configure_plugin`：仅 Rust 内部构造，配置启停和非敏感路径；
- `configure_history_keys`：仅 Rust 内部构造，传入当前数据库或备份所需的版本化 key map，payload 不实现 `Debug` 明文；
- `configure_history_policy`：仅 Rust 内部构造，传入持久化的 history_enabled、privacy_mode 和 history_redaction，WebView payload 不能覆盖；
- `plugin_admin_call`：仅 Rust 内部构造，承载删除、清空、恢复和轮换等已经宿主确认的操作；
- 现有 `cancel` 同时取消主生成和插件任务，request ID 在两类任务间全局唯一。

`plugin_call` 不反射调用 Python 对象方法。Runtime 固定分派表按 public/admin 分级。WebView public 矩阵只允许：

```text
main:    history-sqlite.rate, translator.translate, markdown-preview.preview
history: history-sqlite.list, history-sqlite.detail, history-sqlite.rate,
         history-sqlite.backups, history-sqlite.scan
```

导出由 Rust 文件选择器和私有流式响应处理；以下完整 Runtime 分派表中的破坏性操作只能经 `plugin_admin_call`：

```text
history-sqlite: save, list, detail, rate, delete, clear, export,
                scan, repair, backups, restore, rotate
translator:     translate
markdown-preview: preview, export
```

### Plugin event envelope

插件事件不伪装为 Core `EventEnvelope`：

```json
{
  "version": 1,
  "request_id": "req-id",
  "plugin_id": "translator",
  "operation": "translate",
  "status": "started|chunk|progress|result|cancelled|error",
  "data": {}
}
```

Rust 只把满足完整 schema、已知插件、已知操作和已知状态的公开事件发送到 `reflex://plugin-event`。Host-private request ID 的事件由 Rust 内部 waiter 消费，不发送给 WebView。带可信 request ID 的非法 envelope 终止对应任务；无可信归属的 stdout 污染使所有活动请求失败并强制重启 Sidecar，不回显原文。

`list_plugins` 使用独立信封和事件名 `reflex://capability-list`，避免伪造某个插件事件：

```json
{
  "version": 1,
  "request_id": "req-id",
  "type": "capability_list",
  "plugins": [
    {"id":"translator","kind":"transformer","enabled":true,"available":true,"permissions":["network-via-provider"]}
  ]
}
```

列表条目只允许已验证 descriptor 的公开字段和固定安全 failure code，不包含 Python 模块名、路径或原始异常。

### Result and save snapshot

Rust 在转发 `optimize` 前从持久配置构造 host-private history policy，Runtime 收到后在生成开始时按 request ID 创建可信且不可变的 `HistorySaveSnapshot`，包含 input、mode、style、scene、provider、model、开始时间、`history_enabled`、`privacy_mode` 和 `history_redaction`。完成时 Runtime 只把 output、elapsed 和最终 scene 合入该快照，并通过内部 registry 调用保存；WebView 不拥有公开 `history-sqlite.save`。开始时处于隐私模式或关闭保存的请求永不追补。

主窗口 `CurrentResult` 固定包含 requestId、historyId、output、scene、style、mode、provider、model、elapsedMs 和 saveStatus。历史原文仅存在于短生命周期 save snapshot，不放入列表摘要或最近结果展示状态。

### History capability state

历史能力状态固定为 `absent/read_only/writable/private/unavailable`：

- `absent`：没有 key/数据库，不创建目录；
- `read_only`：已有 key，但 `history_enabled=false`，可查询、导出、删除和修复，拒绝新写；
- `writable`：已有 key，显式开启保存且非隐私模式；
- `private`：已有 key且隐私模式开启，可管理旧记录但拒绝新写；
- `unavailable`：key、数据库或插件失败，只返回固定恢复提示。

`enabled_plugins` 只控制 translator 和 markdown-preview；history-sqlite 使用上述独立状态机，避免两个启停来源冲突。

### History schema

`history-sqlite` schema v1 至少包含：

```text
history_records(
  id TEXT PRIMARY KEY,
  created_at TEXT NOT NULL,
  input_nonce BLOB NOT NULL,
  input_ciphertext BLOB NOT NULL,
  output_nonce BLOB NOT NULL,
  output_ciphertext BLOB NOT NULL,
  key_version INTEGER NOT NULL,
  mode TEXT NOT NULL,
  style TEXT NOT NULL,
  scene TEXT,
  provider TEXT NOT NULL,
  model TEXT,
  elapsed_ms INTEGER,
  status TEXT NOT NULL,
  rating INTEGER,
  tags_json TEXT NOT NULL DEFAULT '[]'
)
schema_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL)
repair_quarantine(id TEXT PRIMARY KEY, reason TEXT NOT NULL, quarantined_at TEXT NOT NULL)
rotation_checkpoint(
  id INTEGER PRIMARY KEY CHECK(id = 1),
  rotation_id TEXT NOT NULL,
  source_version INTEGER NOT NULL,
  target_version INTEGER NOT NULL,
  phase TEXT NOT NULL,
  backup_id TEXT,
  high_water_mark TEXT,
  last_record_id TEXT
)
```

索引仅覆盖 `created_at/provider/scene/style/rating/status`，不建立输入或输出明文索引。全文搜索按元数据和游标分块读取候选记录，在插件内解密并匹配，直至收满当前页或候选结束。

## Scope

包含：

- 三类内置能力插件的发现、描述、状态、权限和安全启停；
- 独立插件任务表、取消、迟到事件过滤和 Runtime 插件事件；
- 配置 v2、历史默认关闭、隐私模式和内置插件启停；
- Core 历史保存前 `none/secrets` 脱敏策略和不可变生成快照；
- Windows Credential Manager 版本化历史密钥环与 active/pending 状态；
- 历史加密存储、分页、搜索、筛选、排序、评分、详情、删除、清空；
- JSON、CSV、Markdown 导出；完整性扫描、坏记录隔离、索引重建、备份恢复；
- 密钥轮换、分批重加密和中断恢复；
- 独立历史窗口、结果保存状态、评分和复用；
- 翻译自动方向、指定目标语言、流式显示、取消、复制和作为当前结果；
- Markdown 源码、分栏和预览视图，以及安全 HTML 导出；
- 自动化、Windows 实机、可见层、安全、依赖和回退验证。

不包含：

- 自动读取或修改旧 Reflex 数据库；
- 明文全文索引或云端历史同步；
- 在主浮窗嵌入完整历史/批处理工作台；
- 插件任意方法调用、任意路径扫描或任意文件写入；
- 使用聊天中出现过的密钥进行联调；
- 修改或提交未跟踪 `resources\`。

## File Map

Runtime：

- Create `packages/reflex-runtime/src/reflex_runtime/plugin_contracts.py`：描述符、事件和严格字段校验。
- Create `packages/reflex-runtime/src/reflex_runtime/capability_registry.py`：启停、配置、操作白名单和实例生命周期。
- Create `packages/reflex-runtime/src/reflex_runtime/task_registry.py`：主生成与插件任务的统一 ID/取消/清理。
- Modify `protocol.py`、`plugin_manager.py`、`context.py`、`cli.py` 和对应测试。
- Modify `packages/reflex-runtime/pyproject.toml`、`uv.lock`：只增加 `builtins` 可选依赖和本地源。

Core：

- Create `packages/reflex-core/src/reflex_core/safety/history.py`：`HistoryRedactionPolicy` 和无 I/O 的 `redact_for_history`。
- Modify `packages/reflex-core/src/reflex_core/safety/__init__.py` 及测试：导出策略并覆盖 secrets/none、幂等和不改变非敏感正文。

插件：

- Create `plugins/history-sqlite/`：契约、加密、SQLite 仓库、导出、修复、轮换和独立测试。
- Create `plugins/translator/`：翻译请求、方向选择、Provider 网关调用和独立测试。
- Create `plugins/markdown-preview/`：确定性渲染、清洗、导出和独立测试。

Rust Host：

- Create `apps/tauri-host/src-tauri/src/history_key_store.rs`：版本化凭据、active/pending 状态和随机密钥。
- Create `apps/tauri-host/src-tauri/src/plugin_commands.rs`：私有配置、公开操作白名单和敏感 payload 脱敏。
- Create `apps/tauri-host/src-tauri/src/history_window.rs`：历史窗口单实例、尺寸和位置恢复。
- Modify `sidecar.rs`：Core/插件事件分流、全部活动请求失败处理和三个插件开发路径。
- Modify `commands.rs`、`runtime_commands.rs`、`config_store.rs`、`desktop.rs`、`lib.rs`、`tauri.conf.json`、capability 和 Cargo 文件。

Frontend：

- Create `apps/tauri-host/src/domain/capabilityBridge.ts` 和测试：插件列表、调用、事件队列和取消。
- Create `apps/tauri-host/src/domain/historyState.ts`、`historyBridge.ts` 和测试：分页、筛选、详情、修复和复用状态。
- Create `apps/tauri-host/src/HistoryApp.svelte`：独立历史工作视图。
- Create `apps/tauri-host/src/components/ResultActions.svelte`、`TranslationView.svelte`、`MarkdownPreview.svelte` 及测试所需状态函数。
- Modify `main.ts`、`App.svelte`、`styles.css`、`hostState.ts`、`settingsApi.ts`、`desktopBridge.ts` 和对应测试。

文档：

- Create `docs/verification/stage-d-verification.md`。
- Modify `README.md`、`apps/tauri-host/README.md`、`packages/reflex-runtime/README.md`、`workbench/readme.md`、`workbench/known-pitfalls.md`。

## Task 1: Freeze Capability Protocol and Discovery

**Files:** Runtime contracts, plugin manager, protocol and tests.

- [ ] **Step 1: Write failing protocol tests**

覆盖全部新增命令、严格字段、64 字符安全 ID、未知操作、非对象 payload、密钥/admin 命令不出现在公开能力、独立 capability-list 响应 schema，以及 Runtime 协议版本不依赖 Core 常量。

- [ ] **Step 2: Verify RED**

Workdir: `packages\reflex-runtime`

Run: `uv run --python 3.12 --with pytest --with httpx pytest -q tests/test_protocol.py tests/test_plugin_manager.py`

Expected: FAIL because capability contracts and commands do not exist.

- [ ] **Step 3: Implement descriptors and discovery**

发现组固定为 `reflex.storage`、`reflex.transformers`、`reflex.commands`；先按 entry point 名称检查内置 allowlist，再 `load()`。描述符固定 `id/display_name/version/kind/permissions/operations`，未知插件默认不加载。

- [ ] **Step 4: Implement non-reflective registry and task registry**

注册表只调用统一 `invoke(operation, payload, services, cancellation)`；操作必须同时存在于描述符和 Runtime allowlist。translator/markdown-preview 服从 `enabled_plugins`；history-sqlite 服从 `absent/read_only/writable/private/unavailable` 独立状态机，写权限由 Runtime 私有配置强制。任务表拒绝重复活动 ID、取消对应 token，并在任何退出路径清理。

- [ ] **Step 5: Verify GREEN and Core boundary**

Workdir: `packages\reflex-runtime`

Run: `uv run --python 3.12 --with pytest --with httpx pytest -q`

Workdir: `packages\reflex-core`

Run: `uv run --python 3.12 --with pytest pytest -q tests/test_import_boundaries.py`

- [ ] **Step 6: Commit**

`feat: 建立受限能力插件通道 | v0.5.0-d1 | YYYY-MM-DD HH:MM`

## Task 2: Route Plugin Events Through Rust Host

**Files:** Rust runtime commands, sidecar, commands, capability, TypeScript bridge and tests.

- [ ] **Step 1: Write failing Rust command/event tests**

覆盖公开操作白名单、按窗口授权、私有配置/admin 命令、`Debug` 脱敏、Core/插件/capability-list stdout 分流、host-private waiter、非法插件事件、Core 与插件活动请求同时失败、重复 ID 和取消。并发注入普通 `print`、traceback、伪造 envelope 和无 request ID 污染；后者必须使全部活动请求失败并重启。

- [ ] **Step 2: Verify RED**

Workdir: `apps\tauri-host\src-tauri`

Run: `cargo test -- --test-threads=2`

- [ ] **Step 3: Implement Rust routing**

`TauriEventEmitter` 根据 envelope 类型发到 `reflex://core-event`、`reflex://plugin-event` 或 `reflex://capability-list`。`runtime_plugin_call` 读取调用窗口 label 并只接收其 public 矩阵字段；Rust 内部按配置补充 plugin enable、Provider 配置、历史路径和版本化密钥命令。每次 `runtime_optimize` 在 optimize 前发送 host-private `configure_history_policy`，Runtime 据此冻结可信快照并在成功后内部保存。`RuntimeController` 增加 host-private waiter/stream sink，私有 request ID 的内容不 emit 到 WebView。CLI 在插件导入前复制协议 OS fd，并用 `dup2` 重定向 fd 1/2 及四个 Python 标准流对象；插件的 `print`、`sys.__stdout__` 和 `os.write(1, ...)` 都不能写入协议流。

- [ ] **Step 4: Write failing frontend bridge tests**

覆盖 listener 先注册、事件按 request/plugin/operation 三重过滤、`result/error/cancelled` 关闭队列、AbortSignal 只取消自身、迟到事件丢弃和安全错误回退。Rust 测试还要覆盖 `main/history` 窗口授权矩阵、public/admin 分离、host-private waiter 不向 WebView emit。

- [ ] **Step 5: Implement `CapabilityBridge` and verify GREEN**

Workdir: `apps\tauri-host`

Run: `$env:VITEST_MAX_WORKERS='2'; npm test -- --maxWorkers=2 src/domain/capabilityBridge.test.ts`

- [ ] **Step 6: Commit**

`feat: 打通宿主插件事件桥接 | v0.5.0-d2 | YYYY-MM-DD HH:MM`

## Task 3: Add History Redaction, Config v2 and Versioned Keys

**Files:** Core safety, Rust config/key store/commands, frontend settings and tests.

- [ ] **Step 1: Write failing Core history-redaction tests**

覆盖 `secrets` 隐藏 API Key/Bearer Token、`none` 保留正文、幂等、非敏感文本不变、非法策略拒绝，以及返回值不修改调用方输入。

- [ ] **Step 2: Verify RED and implement the pure safety function**

Workdir: `packages\reflex-core`

Run: `uv run --python 3.12 --with pytest pytest -q tests/test_safety.py`

- [ ] **Step 3: Write failing config migration tests**

覆盖新安装默认历史关闭和 `history_redaction=secrets`；任何 v1 配置迁移后历史关闭；v2 显式 true/none 保留；未知非敏感字段保留；`enabled_plugins` 只允许 translator/markdown-preview；隐私模式布尔回退。

- [ ] **Step 4: Verify RED**

Workdir: `apps\tauri-host\src-tauri`

Run: `cargo test config_store::tests -- --test-threads=2`

- [ ] **Step 5: Implement config v2**

默认 `history_enabled=false`、`privacy_mode=false`、`history_redaction=secrets`、`enabled_plugins=["translator","markdown-preview"]`。保存时继续使用原子替换和最近有效备份；v1 迁移不承接历史 true。`history_enabled` 只控制新记录写入，不等同于删除或锁住既有历史。

- [ ] **Step 6: Write failing key lifecycle tests**

使用内存凭据后端覆盖 32-byte 随机 key、base64 编码、版本化 key account、active/pending 分离、ensure 幂等、promote、rollback、旧 key 保留、状态不暴露 key，以及后端失败的固定错误。

- [ ] **Step 7: Implement `HistoryKeyStore`**

使用 OS CSPRNG；每个 key 以 `key:vN` 独立保存，Credential Manager 状态记录 active/pending version，不含数据库正文。`Debug`、序列化和前端状态只返回 `configured/active_version/rotation_pending`。新安装只有用户显式开启保存历史时才生成 active key；关闭保存不删除现有 key。阶段 D 对旧 key 只保留、不实现自动或手动回收，避免跨 Rust Credential Manager 与 Python 数据库的清理竞态。

- [ ] **Step 8: Add frontend settings tests and controls**

“安全与隐私”增加“保存历史”“隐私模式”和“保存前隐藏疑似密钥”控件；插件页控制 translator 与 markdown-preview。保存、取消和失败恢复必须保持草稿与持久值一致。

- [ ] **Step 9: Verify and commit**

Workdir: `apps\tauri-host\src-tauri`

Run: `cargo test -- --test-threads=2`

Workdir: `apps\tauri-host`

Run: `$env:VITEST_MAX_WORKERS='2'; npm test -- --maxWorkers=2 src/domain/settingsApi.test.ts src/domain/hostState.test.ts`

Commit: `feat: 升级隐私配置与历史密钥 | v0.5.0-d3 | YYYY-MM-DD HH:MM`

## Task 4: Implement Encrypted History Storage

**Files:** `plugins/history-sqlite/**` and Runtime development wiring.

- [ ] **Step 1: Scaffold plugin metadata without database side effects**

entry point `history-sqlite = "reflex_history_sqlite:plugin"`，kind `storage`，permissions `("storage",)`。导入模块和发现描述符不得创建目录、数据库或备份。

- [ ] **Step 2: Write and verify failing crypto/repository tests**

覆盖 Core `redact_for_history` 在加密前执行、ciphertext 不含原文或被隐藏的 secret、同文不同 nonce、nonce 长度拒绝、AAD 域/长度编码无歧义、input/output 整组调换、schema/key version 调换、null 与空字符串替换、不可变元数据篡改、错误 key 失败、参数化保存、摘要不解密正文、详情解密、坏密文占位、评分范围、游标分页稳定和插件关闭不建库。

Workdir: `plugins\history-sqlite`

Run: `uv run --python 3.12 --with pytest --with cryptography pytest -q`

- [ ] **Step 3: Implement AES-GCM codec and schema v1**

每个正文 blob 使用独立随机 nonce；密钥环只存内存。canonical metadata 固定为 id、created_at、mode、style、scene、provider、model、elapsed_ms 和 status；每项编码 type/null marker，字符串再编码 UTF-8 长度和值，整数编码大端，最后计算 SHA-256。每个 blob 的 AAD 再编码 domain、schema_version、key_version、field_role 和 metadata hash；可变 rating/tags 不进入 AAD。连接启用 foreign keys、busy timeout 和 WAL；schema 迁移前用 SQLite Online Backup API 生成一致快照，失败时回滚并进入只读恢复模式。没有历史 key 时不得创建目录或数据库；已有 key 且关闭保存时允许只读管理既有历史。

- [ ] **Step 4: Implement save/list/detail/rate/delete/clear**

save 只接受 Runtime 内部从 optimize 主链冻结的 `HistorySaveSnapshot`，不属于 public operation；开始时关闭保存或处于隐私模式的请求永不追补。筛选支持 provider、scene、style、date_from、date_to、rating；排序只允许 created_at/rating 且方向固定枚举；分页 cursor 绑定 created_at 和 id。delete/clear 只接受 Rust `plugin_admin_call`，不读取前端 `confirmed` 字段；不存在记录不得返回成功。

- [ ] **Step 5: Implement encrypted keyword search**

按 metadata 条件和游标分块读取候选，逐条解密输入/输出并做 Unicode casefold 包含匹配；不得创建明文 FTS 表、临时明文文件或正文日志。

- [ ] **Step 6: Verify focused and package tests**

Workdir: `plugins\history-sqlite`

Run: `uv run --python 3.12 --with pytest --with cryptography pytest -q`

- [ ] **Step 7: Commit**

`feat: 实现加密历史存储与查询 | v0.5.0-d4 | YYYY-MM-DD HH:MM`

## Task 5: Implement History Export, Repair, Backup and Rotation

**Files:** History plugin export/maintenance/key rotation modules and tests.

- [ ] **Step 1: Write failing export safety tests**

覆盖 JSON/CSV/Markdown UTF-8、字段顺序、CSV 公式注入转义、Markdown 正文惰性代码块编码、嵌套脱敏、host-private 分块响应、用户取消不创建文件、失败信息不含正文/路径/密钥。

- [ ] **Step 2: Implement host-selected export**

WebView 只提交 format/filter；Rust 原生对话框明确提示导出为明文，选择目标后创建同目录受控临时文件。Runtime 通过 host-private waiter 分块返回导出 bytes，Rust 写入自有句柄、flush+fsync 后原子替换；路径和文件句柄不进入 Runtime/WebView，取消或失败删除临时文件。历史 Markdown 的原文/结果写入动态安全长度的 fenced code block，避免主动 HTML、链接或远程嵌入。

- [ ] **Step 3: Write failing maintenance tests**

覆盖 `PRAGMA quick_check`、SQLite Online Backup 一致快照、备份 fsync 与 AEAD 验证、备份先于修复、坏记录隔离、索引重建、无正文摘要、带 key_versions 的备份清单、恢复前再备份、恢复失败保持原库、只读恢复模式。对轮换的每个 phase 并发注入 save/rate/delete/clear/repair/restore/rotate，只有当前维护任务可写，其余统一返回可恢复 busy。

- [ ] **Step 4: Implement scan/repair/backups/restore**

Runtime 与仓库共享一个 maintenance mutex/state，互斥 repair、restore 和 rotate；从维护前快照开始直到成功提升或回滚结束，save/rate/delete/clear 以及其他 admin 写操作全部返回 busy。只读操作仅在连接状态安全时允许。阶段 D 不提供 key cleanup。修复顺序固定：quick_check -> SQLite Online Backup -> 快照 quick_check/AEAD 验证/fsync -> 逐条认证解密 -> 隔离 -> 重建索引 -> 摘要。backup manifest 记录 schema 和全部 key_versions。restore 只接受插件列出的 backup ID：先关闭连接，在暂存位置验证 quick_check、schema、所需 key 和全部 AEAD，再原子替换；保留原库直至新库成功打开。

- [ ] **Step 5: Write failing interrupted rotation tests**

覆盖版本化 keyring、连续两次轮换后恢复每一代备份、完整 phase 检查点、混合 key_version 读取、每个阶段崩溃注入、进程中断后继续、成功提升 pending、失败恢复备份、pending 回滚和旧 key 引用保留。

- [ ] **Step 6: Implement rotation and verify**

轮换顺序固定：创建 pending key -> 冻结新历史写入 -> Online Backup -> 写入 rotation metadata/high-water mark -> 分批重加密 -> 全库 AEAD 验证 -> 提升 active version -> 解除写入冻结 -> 按引用保留旧 key。任何阶段失败按 phase 恢复；轮换期间 `save` 返回可恢复 busy，不采用双写。

Workdir: `plugins\history-sqlite`

Run: `uv run --python 3.12 --with pytest --with cryptography pytest -q`

- [ ] **Step 7: Commit**

`feat: 补齐历史导出修复与轮换 | v0.5.0-d5 | YYYY-MM-DD HH:MM`

## Task 6: Build the Independent History Window

**Files:** Rust history window/Desktop action, frontend history state/bridge/view/styles and tests.

- [ ] **Step 1: Write failing Rust window tests**

覆盖 `history` label 单实例、重复打开聚焦、主窗口不被强制打开、关闭独立处理、最小尺寸、越界恢复和窗口级命令授权。托盘新增“历史记录”，保留“最近结果”。

- [ ] **Step 2: Implement `show_history_window`**

按需创建 `index.html?view=history`，默认 1040×720、最小 760×560；重复打开复用 label。capability 仅授权 `main` 与 `history` 两个已知窗口，并为两者配置不同命令权限。Tauri CSP 固定本地资源和 IPC 所需最小源，禁止 object/frame/form/remote connect；window builder 的 navigation/new-window handler 拒绝所有非本地 URL。

- [ ] **Step 3: Write failing history state tests**

覆盖 loading/empty/error/ready、搜索和筛选重置 cursor、下一页去重、详情、评分、删除后选中恢复、清空确认、导出进度、扫描/修复/恢复和迟到响应。

- [ ] **Step 4: Implement history work view**

左侧分页列表只显示时间、场景、风格、Provider 和评分；右侧按需详情。顶部提供搜索和筛选；导出与修复放入菜单；删除、清空、恢复和轮换调用独立 Rust 命令，由宿主原生确认后生成一次性 admin request，前端确认弹层仅作说明而不授予权限。

- [ ] **Step 5: Emit typed reuse intents**

历史窗口把“载入原文/使用结果”转换为带 history ID 的窄 `HistoryReuseIntent`，Rust 只转发 Runtime 当前详情对应的纯文本 payload，不接受任意脚本或 URL。本任务不修改主窗口结果状态，消费接线在 Task 7 完成。

- [ ] **Step 6: Verify frontend/Rust and commit**

Workdir: `apps\tauri-host`

Run: `$env:VITEST_MAX_WORKERS='2'; npm test -- --maxWorkers=2`

Workdir: `apps\tauri-host\src-tauri`

Run: `cargo test -- --test-threads=2; cargo build`

Commit: `feat: 交付独立历史工作视图 | v0.5.0-d6 | YYYY-MM-DD HH:MM`

## Task 7: Add Result Save State and Rating

**Files:** Host state, result actions, main app and tests.

- [ ] **Step 1: Write failing structured result tests**

按前述稳定契约实现前端 `CurrentResult`，并消费 Runtime 内部可信 `HistorySaveSnapshot` 保存后的状态事件。覆盖 done 后内部异步保存、开始时历史关闭、开始时隐私模式、关闭隐私模式不追补、运行中修改脱敏策略不影响 Runtime 快照、保存失败不影响结果、迟到 history ID 丢弃和评分只针对已保存记录。

- [ ] **Step 2: Replace flat recent output safely**

保留阶段 C 的最近结果行为，但内部改用 `CurrentResult`；活动生成期间仍忽略最近结果动作，取消后可恢复最近结果。

- [ ] **Step 3: Consume history reuse intents**

“载入原文”更新主窗口输入；“使用结果”使用已定义的 `CurrentResult` 契约更新当前结果。只消费 Rust 已校验且对应当前 history detail 的 intent，迟到或未知 history ID 丢弃。

- [ ] **Step 4: Build one More Actions menu**

Complete 只平铺“复制结果”主按钮和一个“更多操作”图标按钮。菜单包含替换剪贴板、重新生成、调整、翻译、Markdown 预览、评分和查看历史；进行中动作禁用冲突项，Esc 关闭并恢复焦点。

- [ ] **Step 5: Show privacy/save state**

只显示用户需要的“已保存到本机 / 未保存 / 隐私模式”状态，不展示插件 ID、请求 ID、阶段标签或调试文字。

- [ ] **Step 6: Verify and commit**

Workdir: `apps\tauri-host`

Run: `$env:VITEST_MAX_WORKERS='2'; npm test -- --maxWorkers=2 src/domain/hostState.test.ts`

Commit: `feat: 接入结果保存状态与评分 | v0.5.0-d7 | YYYY-MM-DD HH:MM`

## Task 8: Implement Streaming Translator

**Files:** Translator plugin, Runtime Provider gateway, frontend translation view and tests.

- [ ] **Step 1: Write failing translator tests**

覆盖空内容拒绝、自动方向、显式中文/English、Provider 未配置、Provider gateway 注入、chunk 清洗、取消后无 result、空响应、安全错误和绝不读取密钥/发 HTTP。

- [ ] **Step 2: Implement provider gateway**

Runtime 从现有 `ProviderRegistry` 解析 Provider；translator 只构造受控 system/user messages 并调用注入的 stream callable。输入使用 Core 校验，chunk 使用 Core 清洗，Provider 异常使用现有安全映射。

- [ ] **Step 3: Implement translation UI**

结果覆盖层提供目标语言 segmented control、原文/译文对照、流式状态、取消、复制译文和“作为当前结果”。翻译使用独立 AbortController 和状态，不修改主 `activeRequestId`。

- [ ] **Step 4: Verify package and frontend tests**

Workdir: `plugins\translator`

Run: `uv run --python 3.12 --with pytest pytest -q`

Workdir: `apps\tauri-host`

Run: `$env:VITEST_MAX_WORKERS='2'; npm test -- --maxWorkers=2`

- [ ] **Step 5: Commit**

`feat: 接入流式结果翻译 | v0.5.0-d8 | YYYY-MM-DD HH:MM`

## Task 9: Implement Safe Markdown Preview

**Files:** Markdown plugin, preview component, save command and tests.

- [ ] **Step 1: Write failing XSS and rendering tests**

覆盖标题、列表、表格、围栏代码、空内容、原始 HTML、script、事件属性、javascript/data/file URI、远程图片、畸形标签和清洗幂等。断言输出不含脚本、远程嵌入和可执行属性。

- [ ] **Step 2: Implement deterministic renderer**

使用 `MarkdownIt("commonmark", {"html": False})` 并显式启用 table；`bleach` 使用最小 tag/attribute/protocol allowlist；移除图片；链接保留安全文本与 URL。除前端 click 拦截外，Rust WebView navigation/new-window handler 统一拒绝非本地 URL，防止键盘、`window.open` 或脚本绕过。

- [ ] **Step 3: Build source/split/preview UI**

同一覆盖层提供三个 tab；预览只渲染 Runtime 返回的 sanitized HTML。无论插件状态如何，前端均不直接把原始 Markdown 当 HTML 注入。

- [ ] **Step 4: Implement standalone HTML export**

导出文档使用 `default-src 'none'`，`style-src` 值在构建文档时由固定 stylesheet 精确字节计算 base64 SHA-256 hash；已清洗 body 不使用 style attribute，不包含脚本、远程字体、远程图片、内部路径或生成工具说明。HTML 与历史导出复用 Rust 原生文件选择、明文提示、host-private 分块响应、受控临时句柄、fsync 和原子替换契约。

- [ ] **Step 5: Verify and commit**

Workdir: `plugins\markdown-preview`

Run: `uv run --python 3.12 --with pytest --with markdown-it-py --with bleach pytest -q`

Workdir: `apps\tauri-host`

Run: `$env:VITEST_MAX_WORKERS='2'; npm test -- --maxWorkers=2; npm run build`

Commit: `feat: 交付安全 Markdown 预览 | v0.5.0-d9 | YYYY-MM-DD HH:MM`

## Task 10: Full Verification, Visible Audit and Push

**Files:** Verification and handoff documentation.

- [ ] **Step 1: Run all automated checks with bounded workers**

```powershell
cd packages\reflex-core
uv run --python 3.12 --with pytest pytest -q

cd ..\reflex-runtime
uv run --python 3.12 --extra builtins --with pytest pytest -q

cd ..\..\plugins\provider-minimax
uv run --python 3.12 --with pytest --with httpx pytest -q

cd ..\history-sqlite
uv run --python 3.12 --with pytest --with cryptography pytest -q

cd ..\translator
uv run --python 3.12 --with pytest pytest -q

cd ..\markdown-preview
uv run --python 3.12 --with pytest --with markdown-it-py --with bleach pytest -q

cd ..\..\apps\tauri-host
$env:VITEST_MAX_WORKERS='2'
npm test -- --maxWorkers=2
npm run build
npm audit --omit=dev

cd src-tauri
cargo test -- --test-threads=2
cargo build
```

- [ ] **Step 2: Run security and boundary gates**

验证 `import reflex_core` 不导入 sqlite3/cryptography/markdown/bleach；插件禁用不创建数据库；数据库不含正文/key；SQL 无拼接；Markdown XSS corpus；日志、事件、导出失败和 Debug 不含测试密钥或完整输入。并发注入插件 `print`、`sys.__stdout__.write`、`os.write(1, ...)`、traceback、伪造 envelope、敏感 stderr 和无 request ID stdout，确认 OS fd 级协议隔离、private 事件不外发、污染时全部活动任务失败并重启。解析 `tauri.conf.json` 断言 CSP/remote IPC 最小化；表驱动验证 navigation/new-window 拒绝 http/https/file/data/javascript 等非本地 URL；从导出 HTML 提取 stylesheet 精确字节，重新计算 SHA-256 base64 并与 CSP `style-src` hash 比对。

- [ ] **Step 3: Run Windows lifecycle evidence**

在专用临时数据目录验证：首次启用、写入、搜索、筛选、评分、导出三格式、坏记录修复、备份恢复、轮换中断继续、关闭历史、隐私模式、重启解密、禁用后不写入、独立窗口复用和退出无 Runtime 残留。

- [ ] **Step 4: Run visible-layer audit**

截图并检查主窗 760×540 和 680×480 的 Complete、更多菜单、翻译、Markdown、设置；历史窗 1040×720 和 760×560 的 empty/loading/list/detail/error/confirm。逐项覆盖 100%/125%/150% DPI、中英文、浅色/深色、长文本、无空格长单词和超长 Provider/模型名称；文本不得重叠或撑破容器。不得出现 debug、test、TODO、Mock、验收、阶段名、插件内部 ID、工具名、内部路径或工作流标签。

- [ ] **Step 5: Run independent code/security/UI review**

要求无剩余 P0-P2；P3 必须记录理由。复核线程安全、SQLite 锁、轮换恢复、stdout 分流、事件迟到、XSS、焦点、键盘和窗口边界。

- [ ] **Step 6: Verify repository integrity**

Workdir: repository root.

Run: `git diff --check`

Run: `git status --short`

按既有算法复算 `resources\`：27 文件且 digest 必须为 `3BAF82F50AA911BBC68DE1851741BD5B14AF06D3D1E6F5B994D90E761A5B236D`，并确认该目录未暂存。

- [ ] **Step 7: Document and commit**

`docs: 记录阶段 D 验证与回退 | v0.5.0-d10 | YYYY-MM-DD HH:MM`

- [ ] **Step 8: Push without force**

推送 `codex/full-feature-parity`。若远端前进，先 fetch、审阅并整合；禁止强推。阶段 D 完成后继续阶段 E，不把阶段 D 完成误报为 A-G 全部完成。

## Commit Plan

1. `docs: 制定阶段 D 历史与增强计划 | v0.5.0-d0 | YYYY-MM-DD HH:MM`
2. `feat: 建立受限能力插件通道 | v0.5.0-d1 | YYYY-MM-DD HH:MM`
3. `feat: 打通宿主插件事件桥接 | v0.5.0-d2 | YYYY-MM-DD HH:MM`
4. `feat: 升级隐私配置与历史密钥 | v0.5.0-d3 | YYYY-MM-DD HH:MM`
5. `feat: 实现加密历史存储与查询 | v0.5.0-d4 | YYYY-MM-DD HH:MM`
6. `feat: 补齐历史导出修复与轮换 | v0.5.0-d5 | YYYY-MM-DD HH:MM`
7. `feat: 交付独立历史工作视图 | v0.5.0-d6 | YYYY-MM-DD HH:MM`
8. `feat: 接入结果保存状态与评分 | v0.5.0-d7 | YYYY-MM-DD HH:MM`
9. `feat: 接入流式结果翻译 | v0.5.0-d8 | YYYY-MM-DD HH:MM`
10. `feat: 交付安全 Markdown 预览 | v0.5.0-d9 | YYYY-MM-DD HH:MM`
11. `docs: 记录阶段 D 验证与回退 | v0.5.0-d10 | YYYY-MM-DD HH:MM`

每次提交只暂存列出的职责文件，不使用 `git add .`，不暂存 `resources\`。

## Recovery

- 插件协议回归：回退 d2/d1，现有 Core 优化和阶段 C 桌面能力继续工作。
- 历史插件不可用：保持优化、翻译和 Markdown 可用，UI 显示历史暂不可用且不写明文替代。
- Credential Manager 不可用：不创建新历史库、不覆盖现有 key、不尝试弱密钥或配置文件回退。
- 数据库迁移失败：恢复升级前备份并进入只读恢复模式。
- 修复失败：原库与修复前备份保持不变，摘要只报告计数。
- 轮换中断：保留版本化 keyring、完整 phase 检查点和轮换前一致快照，下一次启动继续；无法继续时恢复快照。阶段 D 永不回收旧 key。
- 翻译失败或取消：主结果保持不变，可重试或关闭覆盖层。
- Markdown 清洗失败：只显示固定错误，不回退到原始 HTML 渲染。
- 前端回归：可依次回退 d9、d8、d7、d6，不影响已加密历史数据；数据库 schema 不做破坏性降级。
