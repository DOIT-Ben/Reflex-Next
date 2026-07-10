# Stage A Secure MiniMax Mainline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不让密钥进入前端持久状态、进程参数、环境变量、日志或仓库的前提下，交付可持久化配置、Windows 凭据存储、Runtime 插件注册和 MiniMax 真实流式主链。

**Architecture:** Rust Host 拥有非敏感配置和 Windows Credential Manager，并在每次 MiniMax 请求前通过已拥有的 Sidecar stdin 发送私有 `configure_provider` 命令。Python Runtime 通过生产 entry point 或开发态固定白名单加载 Provider 工厂，在内存中配置并按请求选择 Provider；MiniMax 插件独立负责 HTTP、SSE/JSON 解析、取消、错误分类和有限重试。Svelte 只保存瞬时密钥输入，只能读取“是否已配置”和掩码尾部。

**Tech Stack:** Rust 1.77.2、Tauri 2、Serde、`keyring` Windows native backend、Python 3.11+、`importlib.metadata`、`httpx`、Svelte 5、TypeScript、Vitest、pytest。

---

## File Map

- Create `apps/tauri-host/src-tauri/src/config_store.rs`: 版本化配置、校验、迁移、原子写入和最近有效备份。
- Create `apps/tauri-host/src-tauri/src/secret_store.rs`: 可替换 SecretStore trait、Windows Credential Manager 适配器和状态掩码。
- Modify `apps/tauri-host/src-tauri/src/lib.rs`: 注册配置、密钥和 Runtime 状态及公开命令。
- Modify `apps/tauri-host/src-tauri/src/commands.rs`: 配置读写、密钥保存/状态/删除和优化前私有注入。
- Modify `apps/tauri-host/src-tauri/src/runtime_commands.rs`: 允许宿主内部构造 `configure_provider`，但不暴露为 Tauri command。
- Modify `apps/tauri-host/src-tauri/src/sidecar.rs`: 开发态固定插件路径和配置命令发送。
- Modify `apps/tauri-host/src-tauri/Cargo.toml`: 增加凭据库和测试临时目录依赖。
- Create `packages/reflex-runtime/src/reflex_runtime/plugin_manager.py`: 生产 entry point 和开发态白名单插件发现。
- Create `packages/reflex-runtime/src/reflex_runtime/provider_registry.py`: Provider 工厂注册、内存配置、按请求解析和旧实例替换。
- Create `packages/reflex-runtime/src/reflex_runtime/provider_errors.py`: 稳定 Provider 错误码和安全文案。
- Modify `packages/reflex-runtime/src/reflex_runtime/protocol.py`: 增加私有 `configure_provider` 命令契约。
- Modify `packages/reflex-runtime/src/reflex_runtime/context.py`: 处理配置命令并为每次请求构造使用所选 Provider 的 UseCase。
- Create `packages/reflex-runtime/tests/test_plugin_manager.py`: 插件发现隔离和失败容错。
- Create `packages/reflex-runtime/tests/test_provider_registry.py`: 配置、替换、未配置和请求选择。
- Modify `packages/reflex-runtime/tests/test_protocol.py`: 私有命令解析和校验。
- Modify `packages/reflex-runtime/tests/test_cli.py`: 进程级配置、MiniMax 夹具流、取消和脱敏。
- Replace `plugins/provider-minimax/src/reflex_provider_minimax/__init__.py`: 插件元数据、工厂和公开入口。
- Create `plugins/provider-minimax/src/reflex_provider_minimax/provider.py`: 请求映射、流式处理、取消和错误映射。
- Create `plugins/provider-minimax/src/reflex_provider_minimax/sse.py`: SSE/JSON 增量解析。
- Create `plugins/provider-minimax/tests/fixtures/*.jsonl`: 无密钥离线响应夹具。
- Create `plugins/provider-minimax/tests/test_provider.py`: 请求、重试、错误、取消和泄漏契约。
- Create `plugins/provider-minimax/tests/test_sse.py`: SSE/JSON 解析契约。
- Modify `plugins/provider-minimax/pyproject.toml`: 增加 `httpx` 和 pytest 配置。
- Create `apps/tauri-host/src/domain/settingsApi.ts`: 设置和密钥状态的 Tauri 适配层。
- Create `apps/tauri-host/src/domain/settingsApi.test.ts`: 瞬时输入、状态和命令参数测试。
- Modify `apps/tauri-host/src/domain/coreBridge.ts`: 优化请求继续只传非敏感 Provider/model。
- Modify `apps/tauri-host/src/domain/hostState.ts`: 加载持久设置和密钥状态，不增加 `apiKey` 字段。
- Modify `apps/tauri-host/src/domain/hostState.test.ts`: 默认模型和无密钥状态契约。
- Modify `apps/tauri-host/src/App.svelte`: 真实密钥输入、保存、状态、删除、保存中和错误状态。
- Modify `apps/tauri-host/src/styles.css`: 设置页输入与状态布局。
- Modify `packages/reflex-runtime/README.md` and `plugins/provider-minimax/README.md`: 开发、离线测试和显式 smoke 流程。

## Stable Contracts

Rust 侧非敏感配置使用：

```rust
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct AppConfig {
    pub version: u32,
    pub provider: String,
    pub model: String,
    pub mode: String,
    pub style: String,
    pub scene_policy: String,
    pub clipboard_policy: String,
    pub history_enabled: bool,
    pub privacy_mode: bool,
    pub language: String,
    pub theme: String,
    pub hotkey: String,
    pub tls_verify: bool,
    pub ca_bundle_path: Option<String>,
    #[serde(flatten)]
    pub extensions: serde_json::Map<String, serde_json::Value>,
}
```

公开 Tauri 命令仅包含：

```text
load_app_config() -> AppConfig
save_app_config(config: AppConfig) -> AppConfig
provider_secret_status(provider_id: String) -> SecretStatus
save_provider_secret(provider_id: String, secret: String) -> SecretStatus
delete_provider_secret(provider_id: String) -> SecretStatus
runtime_optimize(command: Value) -> ()
runtime_cancel(command: Value) -> ()
```

私有 Runtime 命令只由 Rust 构造：

```json
{"version":1,"request_id":"host-config-minimax","type":"configure_provider","payload":{"provider_id":"minimax","secret":"<memory-only>","config":{"model":"MiniMax-M2.7-highspeed","tls_verify":true,"ca_bundle_path":null}}}
```

Python 插件契约使用：

```python
@dataclass(frozen=True)
class ProviderConfig:
    model: str
    base_url: str
    timeout_seconds: float = 60.0
    tls_verify: bool = True
    ca_bundle_path: str | None = None

class ProviderFactory(Protocol):
    id: str
    display_name: str
    version: str
    models: tuple[str, ...]
    default_model: str
    required_secret: str
    permissions: tuple[str, ...]

    def create(self, secret: str, config: ProviderConfig): ...
```

---

### Task 1: Versioned ConfigStore

**Files:**
- Create: `apps/tauri-host/src-tauri/src/config_store.rs`
- Modify: `apps/tauri-host/src-tauri/src/lib.rs`
- Modify: `apps/tauri-host/src-tauri/src/commands.rs`
- Modify: `apps/tauri-host/src-tauri/Cargo.toml`

- [ ] **Step 1: Write failing Rust tests for defaults, invalid-value fallback, unknown-field preservation, atomic save, backup and v0 migration**

```rust
#[test]
fn invalid_values_fall_back_without_dropping_unknown_fields() {
    let raw = json!({"version": 1, "provider": "minimax", "model": "", "mode": "unsafe", "future_flag": true});
    let config = AppConfig::from_value(raw).unwrap();
    assert_eq!(config.mode, "content");
    assert_eq!(config.model, "MiniMax-M2.7-highspeed");
    assert_eq!(config.extensions.get("future_flag"), Some(&json!(true)));
}

#[test]
fn save_replaces_primary_and_keeps_previous_valid_backup() {
    let store = ConfigStore::new(tempdir().unwrap().path().to_path_buf());
    store.save(&AppConfig::default()).unwrap();
    let changed = AppConfig { style: "concise".into(), ..AppConfig::default() };
    store.save(&changed).unwrap();
    assert_eq!(store.load().unwrap().style, "concise");
    assert!(store.backup_path().is_file());
}
```

- [ ] **Step 2: Run the focused tests and confirm they fail because ConfigStore does not exist**

Run: `cargo test config_store -- --test-threads=2`

Expected: compilation failure naming missing module/types.

- [ ] **Step 3: Implement `AppConfig`, v0-to-v1 migration, safe normalization and same-directory temp-file replacement**

```rust
impl ConfigStore {
    pub fn load(&self) -> Result<AppConfig, ConfigStoreError>;
    pub fn save(&self, config: &AppConfig) -> Result<AppConfig, ConfigStoreError>;
}

impl AppConfig {
    fn normalized(mut self) -> Self {
        self.version = 1;
        if !matches!(self.mode.as_str(), "content" | "prompt") { self.mode = "content".into(); }
        if !matches!(self.style.as_str(), "concise" | "balanced" | "detailed" | "creative") { self.style = "balanced".into(); }
        if self.model.trim().is_empty() { self.model = "MiniMax-M2.7-highspeed".into(); }
        self.tls_verify = true;
        self
    }
}
```

Write UTF-8 JSON to `config.json.tmp`, call `sync_all`, rename valid `config.json` to `config.json.bak`, then rename temp to primary. On a corrupt primary, load the valid backup; if neither exists, return safe defaults.

- [ ] **Step 4: Register `ConfigStore` with Tauri and expose load/save commands**

`save_app_config` must return the normalized persisted config. It must never accept or serialize secret-like fields; reject flattened keys matching `api_key`, `token`, `secret`, `authorization` or `password` case-insensitively.

- [ ] **Step 5: Run focused and full Rust tests**

Run: `cargo test config_store -- --test-threads=2`

Expected: all ConfigStore tests pass.

Run: `cargo test -- --test-threads=2`

Expected: all Rust tests pass with no secret values printed.

- [ ] **Step 6: Commit the ConfigStore slice**

```powershell
git add apps\tauri-host\src-tauri\Cargo.toml apps\tauri-host\src-tauri\Cargo.lock apps\tauri-host\src-tauri\src\config_store.rs apps\tauri-host\src-tauri\src\commands.rs apps\tauri-host\src-tauri\src\lib.rs
git commit -m "conf: 增加版本化安全配置存储 | v0.2.0-a1 | 2026-07-10 HH:MM"
```

### Task 2: Windows Credential Manager SecretStore

**Files:**
- Create: `apps/tauri-host/src-tauri/src/secret_store.rs`
- Modify: `apps/tauri-host/src-tauri/src/commands.rs`
- Modify: `apps/tauri-host/src-tauri/src/lib.rs`
- Modify: `apps/tauri-host/src-tauri/Cargo.toml`

- [ ] **Step 1: Write failing tests against an injectable in-memory backend**

```rust
#[test]
fn save_status_and_delete_never_return_the_full_secret() {
    let backend = MemoryCredentialBackend::default();
    let store = SecretStore::new(backend);
    let status = store.save("minimax", "sk-stage-a-secret").unwrap();
    assert_eq!(status.provider_id, "minimax");
    assert!(status.configured);
    assert_eq!(status.masked_tail, Some("cret".into()));
    assert!(!serde_json::to_string(&status).unwrap().contains("sk-stage-a-secret"));
    assert!(!store.delete("minimax").unwrap().configured);
}

#[test]
fn provider_ids_and_empty_secrets_are_rejected() {
    assert!(validate_provider_id("../minimax").is_err());
    assert!(validate_secret("   ").is_err());
}
```

- [ ] **Step 2: Run focused tests and confirm the missing SecretStore failure**

Run: `cargo test secret_store -- --test-threads=2`

Expected: compilation failure naming missing module/types.

- [ ] **Step 3: Implement backend trait and Windows adapter**

```rust
pub trait CredentialBackend: Send + Sync + 'static {
    fn get(&self, service: &str, account: &str) -> Result<Option<String>, SecretStoreError>;
    fn set(&self, service: &str, account: &str, secret: &str) -> Result<(), SecretStoreError>;
    fn delete(&self, service: &str, account: &str) -> Result<(), SecretStoreError>;
}

pub struct SecretStatus {
    pub provider_id: String,
    pub configured: bool,
    pub masked_tail: Option<String>,
}
```

Use service `com.reflex-next.provider` and normalized account `provider:<lowercase-id>`. Map backend failures to fixed Chinese messages; never include backend debug text or the secret.

- [ ] **Step 4: Expose status/save/delete commands and keep raw reads private**

Only `TauriRuntimeState::prepare_provider(provider_id, config)` may call `SecretStore::read`. The invoke handler must not register any command that returns a raw secret.

- [ ] **Step 5: Run Rust tests and scan the Rust source for accidental secret output**

Run: `cargo test secret_store -- --test-threads=2`

Run: `rg -n "println!|dbg!|Authorization|api[_-]?key|secret" apps\tauri-host\src-tauri\src`

Expected: tests pass; matches are declarations, validation or fixed-field handling only, with no secret formatting or logging.

- [ ] **Step 6: Commit the SecretStore slice**

```powershell
git add apps\tauri-host\src-tauri\Cargo.toml apps\tauri-host\src-tauri\Cargo.lock apps\tauri-host\src-tauri\src\secret_store.rs apps\tauri-host\src-tauri\src\commands.rs apps\tauri-host\src-tauri\src\lib.rs
git commit -m "feat: 接入 Windows 凭据安全存储 | v0.2.0-a2 | 2026-07-10 HH:MM"
```

### Task 3: Runtime PluginManager and ProviderRegistry

**Files:**
- Create: `packages/reflex-runtime/src/reflex_runtime/provider_errors.py`
- Create: `packages/reflex-runtime/src/reflex_runtime/plugin_manager.py`
- Create: `packages/reflex-runtime/src/reflex_runtime/provider_registry.py`
- Create: `packages/reflex-runtime/tests/test_plugin_manager.py`
- Create: `packages/reflex-runtime/tests/test_provider_registry.py`

- [ ] **Step 1: Write failing plugin discovery and registry tests**

```python
def test_entry_point_failure_does_not_block_other_provider_factories():
    manager = PluginManager(entry_points_loader=lambda: [BrokenEntryPoint(), GoodEntryPoint()])
    result = manager.discover_provider_factories()
    assert tuple(result.factories) == ("minimax",)
    assert result.failures[0].plugin_id == "broken"
    assert "traceback" not in result.failures[0].safe_message.lower()

def test_registry_replaces_configured_instance_without_retaining_secret():
    registry = ProviderRegistry({"minimax": RecordingFactory()})
    registry.configure("minimax", "first-secret", {"model": "m1"})
    registry.configure("minimax", "second-secret", {"model": "m2"})
    provider = registry.resolve("minimax", "m2")
    assert provider.model == "m2"
    assert "first-secret" not in repr(registry)
    assert "second-secret" not in repr(registry)
```

- [ ] **Step 2: Run tests and confirm missing modules**

Run: `uv run --python 3.12 --with pytest pytest tests/test_plugin_manager.py tests/test_provider_registry.py -q`

Expected: collection errors for missing runtime modules.

- [ ] **Step 3: Implement stable errors, discovery result and registry**

```python
class ProviderRuntimeError(RuntimeError):
    def __init__(self, code: str, safe_message: str, *, recoverable: bool, action: str | None = None): ...

class PluginManager:
    def discover_provider_factories(self) -> PluginDiscoveryResult: ...

class ProviderRegistry:
    def configure(self, provider_id: str, secret: str, raw_config: dict[str, object]) -> None: ...
    def resolve(self, provider_id: str, model: str | None): ...
```

Production discovery uses `importlib.metadata.entry_points(group="reflex.providers")`. Development loading accepts only module names passed by the Rust launch spec, initially `reflex_provider_minimax`; it does not scan arbitrary paths. Duplicate IDs fail closed and remain unavailable.

- [ ] **Step 4: Map registry errors to the approved provider codes**

Use `provider_unconfigured`, `provider_invalid_response`, and `provider_service_error` with fixed safe messages. Exception `repr` and tracebacks never cross stdout.

- [ ] **Step 5: Run Runtime tests**

Run: `uv run --python 3.12 --with pytest pytest tests/test_plugin_manager.py tests/test_provider_registry.py -q`

Expected: focused tests pass.

Run: `uv run --python 3.12 --with pytest pytest -q`

Expected: all Runtime tests pass.

- [ ] **Step 6: Commit the registry slice**

```powershell
git add packages\reflex-runtime\src\reflex_runtime packages\reflex-runtime\tests
git commit -m "feat: 增加 Runtime Provider 插件注册 | v0.2.0-a3 | 2026-07-10 HH:MM"
```

### Task 4: MiniMax Provider with Offline HTTP Contracts

**Files:**
- Replace: `plugins/provider-minimax/src/reflex_provider_minimax/__init__.py`
- Create: `plugins/provider-minimax/src/reflex_provider_minimax/provider.py`
- Create: `plugins/provider-minimax/src/reflex_provider_minimax/sse.py`
- Create: `plugins/provider-minimax/tests/fixtures/stream_success.jsonl`
- Create: `plugins/provider-minimax/tests/fixtures/json_success.json`
- Create: `plugins/provider-minimax/tests/test_sse.py`
- Create: `plugins/provider-minimax/tests/test_provider.py`
- Modify: `plugins/provider-minimax/pyproject.toml`

- [ ] **Step 1: Write failing SSE and JSON parser tests**

```python
def test_parse_sse_ignores_keepalive_and_stops_on_done():
    lines = [": ping", "", 'data: {"choices":[{"delta":{"content":"第一段"}}]}', "", "data: [DONE]"]
    assert list(iter_content_chunks(lines)) == ["第一段"]

def test_extract_json_content_accepts_message_content():
    payload = {"choices": [{"message": {"content": "完整结果"}}]}
    assert extract_json_content(payload) == "完整结果"
```

- [ ] **Step 2: Write failing Provider tests with `httpx.MockTransport`**

```python
def test_stream_maps_request_without_leaking_authorization(recording_transport):
    provider = MiniMaxProvider(secret="sk-fixture-only", config=test_config(), transport=recording_transport)
    chunks = list(provider.stream({"system": "规则", "user": "内容"}, request(), CancellationToken()))
    assert chunks == ["第一段", "第二段"]
    sent = recording_transport.request
    assert sent.headers["Authorization"] == "Bearer sk-fixture-only"
    assert "sk-fixture-only" not in repr(provider)

@pytest.mark.parametrize("status,code", [(401,"provider_auth_failed"),(429,"provider_rate_limited"),(500,"provider_service_error")])
def test_http_statuses_map_to_safe_codes(status, code): ...

def test_cancel_closes_stream_before_next_chunk(): ...
```

- [ ] **Step 3: Run focused tests and confirm the placeholder implementation fails**

Run: `uv run --python 3.12 --with pytest --with httpx pytest tests -q`

Expected: failures for missing parser and Provider implementation.

- [ ] **Step 4: Implement metadata, request mapping and response parsing**

```python
DEFAULT_BASE_URL = "https://api.minimaxi.com/v1/chat/completions"
DEFAULT_MODEL = "MiniMax-M2.7-highspeed"

payload = {
    "model": request.model or self.model,
    "messages": [
        {"role": "system", "content": rendered_request["system"]},
        {"role": "user", "content": rendered_request["user"]},
    ],
    "stream": request.stream,
}
```

Accept both OpenAI-compatible SSE and complete JSON. Treat missing choices/content, invalid JSON and a successful empty stream as `provider_invalid_response` or `provider_empty_response` without including response bodies.

- [ ] **Step 5: Implement cancellation, timeout and conservative retry**

Retry connection failures, timeout before first content, 429 and 5xx at most twice with 0.25s/0.5s backoff. Do not retry 401/403, invalid responses, cancellations, or any request after yielding content. Check `CancellationToken` before send and before each yielded chunk; close the response on cancellation.

- [ ] **Step 6: Run Provider tests and a secret leak scan**

Run: `uv run --python 3.12 --with pytest --with httpx pytest tests -q`

Run: `rg -n "sk-[A-Za-z0-9_-]{12,}|Authorization|response\.text|response\.content" plugins\provider-minimax`

Expected: all Provider tests pass; only fixture-only short sentinel/header construction matches, with no production logging or response-body diagnostics.

- [ ] **Step 7: Commit the MiniMax plugin slice**

```powershell
git add plugins\provider-minimax
git commit -m "feat: 实现 MiniMax 流式 Provider | v0.2.0-a4 | 2026-07-10 HH:MM"
```

### Task 5: Private Configure Command and Per-Request Provider Selection

**Files:**
- Modify: `packages/reflex-runtime/src/reflex_runtime/protocol.py`
- Modify: `packages/reflex-runtime/src/reflex_runtime/context.py`
- Modify: `packages/reflex-runtime/src/reflex_runtime/cli.py`
- Modify: `packages/reflex-runtime/tests/test_protocol.py`
- Modify: `packages/reflex-runtime/tests/test_cli.py`
- Modify: `apps/tauri-host/src-tauri/src/runtime_commands.rs`
- Modify: `apps/tauri-host/src-tauri/src/commands.rs`
- Modify: `apps/tauri-host/src-tauri/src/sidecar.rs`

- [ ] **Step 1: Write failing Runtime protocol tests for `configure_provider`**

```python
def test_parse_private_provider_configuration_command():
    command = parse_command({
        "version": 1,
        "request_id": "host-config-minimax",
        "type": "configure_provider",
        "payload": {"provider_id": "minimax", "secret": "fixture-secret", "config": {"model": "m1"}},
    })
    assert command.type == "configure_provider"
```

Reject unknown provider IDs, blank secrets, non-object config and extra top-level payload shapes with a generic protocol error that contains no submitted values.

- [ ] **Step 2: Write failing process-level tests for configure then optimize, unconfigured selection and reconfiguration**

Use a development fixture Provider module, not real network. Assert `configure_provider` emits a completed status, optimize emits request/chunk/done, unknown Provider emits `provider_unconfigured`, and stderr/stdout contain neither fixture secret.

- [ ] **Step 3: Run focused Runtime tests and observe expected failures**

Run: `uv run --python 3.12 --with pytest pytest tests/test_protocol.py tests/test_cli.py -q`

Expected: configure command is rejected or unhandled.

- [ ] **Step 4: Implement Runtime command handling and request-scoped UseCase creation**

```python
if command.type == "configure_provider":
    self._registry.configure(
        command.payload["provider_id"],
        command.payload["secret"],
        command.payload["config"],
    )
    self.emit_status(command.request_id, StatusPhase.COMPLETED, "provider_configured")
    return True

provider = self._registry.resolve(request.provider or "minimax", request.model)
use_case = OptimizeUseCase(
    scene_detector=self._scene_detector,
    template_resolver=self._template_resolver,
    provider=provider,
)
```

Keep Mock available only when explicitly selected in test/development configuration. Never auto-fallback from MiniMax to Mock.

- [ ] **Step 5: Add a Rust internal constructor and optimize preflight**

```rust
pub fn configure_provider_command(provider_id: &str, secret: &str, config: Value) -> ValidatedCommand;
```

`runtime_optimize` validates the public optimize envelope, obtains the selected Provider from its payload/config store, reads the corresponding credential, then calls a new `RuntimeController::send_sequence` that holds one controller lock while sending `configure_provider` and optimize to the same Sidecar instance. Add a concurrency test whose fake process records complete command lines and asserts each configure command is immediately followed by its matching optimize command. `configure_provider` is not added to `tauri::generate_handler!`.

- [ ] **Step 6: Extend development Sidecar launch paths with the fixed MiniMax plugin source**

`RuntimePaths` gains `provider_plugin_src`, validated exactly as `<repo>\plugins\provider-minimax\src`; `PYTHONPATH` contains only Core, Runtime and this fixed built-in source path.

- [ ] **Step 7: Run Runtime and Rust integration tests**

Run: `uv run --python 3.12 --with pytest pytest -q`

Run: `cargo test -- --test-threads=2`

Expected: all tests pass, configure is private at Tauri boundary, and the process fixtures show no secret in stdout/stderr.

- [ ] **Step 8: Commit the private pipeline slice**

```powershell
git add packages\reflex-runtime apps\tauri-host\src-tauri
git commit -m "feat: 打通 Provider 私有配置与请求选择 | v0.2.0-a5 | 2026-07-10 HH:MM"
```

### Task 6: Settings UI and Transient Secret Input

**Files:**
- Create: `apps/tauri-host/src/domain/settingsApi.ts`
- Create: `apps/tauri-host/src/domain/settingsApi.test.ts`
- Modify: `apps/tauri-host/src/domain/hostState.ts`
- Modify: `apps/tauri-host/src/domain/hostState.test.ts`
- Modify: `apps/tauri-host/src/App.svelte`
- Modify: `apps/tauri-host/src/styles.css`

- [ ] **Step 1: Write failing settings API tests**

```typescript
it("sends the secret once and returns only status", async () => {
  const calls: unknown[] = [];
  const api = createSettingsApi({ invoke: async (command, args) => {
    calls.push({ command, args });
    return { provider_id: "minimax", configured: true, masked_tail: "9xyz" };
  }});
  await expect(api.saveProviderSecret("minimax", "temporary-value")).resolves.toEqual({
    providerId: "minimax", configured: true, maskedTail: "9xyz"
  });
  expect(calls).toEqual([{ command: "save_provider_secret", args: { providerId: "minimax", secret: "temporary-value" } }]);
});
```

- [ ] **Step 2: Write failing host-state tests for persisted config and secret status without an API key field**

Assert the default model is `MiniMax-M2.7-highspeed`, loaded config normalizes provider ID to `minimax`, and `JSON.stringify(state)` never includes the transient test secret.

- [ ] **Step 3: Run focused Vitest tests and observe failures**

Run: `$env:VITEST_MAX_WORKERS='2'; npm test -- --maxWorkers=2 src/domain/settingsApi.test.ts src/domain/hostState.test.ts`

Expected: missing settings API/default model mismatch failures.

- [ ] **Step 4: Implement typed settings API and state mapping**

```typescript
export interface SecretStatus {
  providerId: string;
  configured: boolean;
  maskedTail: string | null;
}

export interface SettingsApi {
  loadConfig(): Promise<AppConfig>;
  saveConfig(config: AppConfig): Promise<AppConfig>;
  getProviderSecretStatus(providerId: string): Promise<SecretStatus>;
  saveProviderSecret(providerId: string, secret: string): Promise<SecretStatus>;
  deleteProviderSecret(providerId: string): Promise<SecretStatus>;
}
```

Keep `secretInput` as an `App.svelte` local variable only. Do not add it to `HostState`, localStorage, URL, event payloads or diagnostics.

- [ ] **Step 5: Replace the read-only mask with complete save/status/delete controls**

On settings open, load config and status. The password input uses `autocomplete="off"`, never pre-fills, and clears in a `finally` block after save. Display `已安全保存 · 尾号 9xyz` or `尚未配置`; expose `保存密钥` and `删除密钥`. Do not provide a reveal-existing-secret action. Disable actions while saving and show fixed safe errors.

- [ ] **Step 6: Persist non-sensitive settings before closing the dialog**

Save `AppConfig` through Rust first, then apply the normalized response to HostState. A failed save keeps the dialog and draft open with a fixed retry message.

- [ ] **Step 7: Run frontend tests and build**

Run: `$env:VITEST_MAX_WORKERS='2'; npm test -- --maxWorkers=2`

Run: `npm run build`

Expected: all frontend tests and production build pass.

- [ ] **Step 8: Commit the settings slice**

```powershell
git add apps\tauri-host\src apps\tauri-host\package-lock.json
git commit -m "feat: 完成设置与密钥状态交互 | v0.2.0-a6 | 2026-07-10 HH:MM"
```

### Task 7: Offline Integration, Leakage Audit and Documentation

**Files:**
- Modify: `packages/reflex-runtime/README.md`
- Modify: `plugins/provider-minimax/README.md`
- Create: `docs/verification/stage-a-verification.md`

- [ ] **Step 1: Add a repository-level leakage test/script assertion to the Runtime integration test**

After configure, stream, cancel, auth failure and shutdown fixture runs, concatenate captured stdout/stderr and assert none of the sentinel secrets, `Authorization: Bearer`, request body or response body appears.

- [ ] **Step 2: Run all Stage A automated verification sequentially with bounded workers**

```powershell
Set-Location packages\reflex-core
uv run --python 3.12 --with pytest pytest -q
Set-Location ..\reflex-runtime
uv run --python 3.12 --with pytest --with httpx pytest -q
Set-Location ..\..\plugins\provider-minimax
uv run --python 3.12 --with pytest --with httpx pytest -q
Set-Location ..\..\apps\tauri-host
$env:VITEST_MAX_WORKERS='2'
npm test -- --maxWorkers=2
npm run build
Set-Location src-tauri
cargo test -- --test-threads=2
cargo build
```

Expected: every command exits 0. Do not run the suites concurrently.

- [ ] **Step 3: Run dependency and user-visible leakage scans**

```powershell
rg -n "PyQt5|PySide|torch|sentence_transformers|huggingface_hub|sqlite3" packages\reflex-core
rg -n "sk-[A-Za-z0-9_-]{12,}|Bearer\s+[A-Za-z0-9._~+\/=\-]{12,}" -g '!resources/**' -g '!docs/superpowers/**' .
rg -n "Mock|debug|test|TO[D]O|AI生成|生成器|验收|uv|Tauri|Runtime|Sidecar" apps\tauri-host\src
```

Expected: Core prohibited-import scan has no imports; secret scan has no real credential; visible-source matches are reviewed and removed from rendered UI text.

- [ ] **Step 4: Start the Tauri app and perform offline visual QA**

Use the fixture Provider first. Verify 760×540 and 680×480 at 100%, then 125%/150% scaling: settings opens, password field is blank, status is visible, long model names wrap without overlap, save/delete errors remain inside the dialog, generation/cancel/error/recovery still work. Capture screenshots for review but do not commit them.

- [ ] **Step 5: Document verification evidence and rollback**

Record exact commands, counts and observed UI states in `docs/verification/stage-a-verification.md`; do not include inputs, outputs, secret tails, account names, machine paths, raw exceptions or screenshots. Rollback is: disable `minimax`, restore `config.json.bak`, delete the `provider:minimax` credential, and retain Mock only under explicit development mode.

- [ ] **Step 6: Commit documentation separately**

```powershell
git add packages\reflex-runtime\README.md plugins\provider-minimax\README.md docs\verification\stage-a-verification.md
git commit -m "docs: 记录阶段 A 验证与回滚流程 | v0.2.0-a7 | 2026-07-10 HH:MM"
```

### Task 8: Explicit Real MiniMax Smoke and Stage A Release Gate

**Files:**
- Modify: `docs/verification/stage-a-verification.md`

- [ ] **Step 1: Verify current official MiniMax endpoint and model immediately before the paid call**

Use official MiniMax documentation only. Update configurable defaults if the documented endpoint/model differs; repeat Tasks 4-7 tests after any change. Do not paste the credential into a shell, URL, source file or environment variable.

- [ ] **Step 2: Have the user save the credential through the running settings page**

The front-end input must clear after save. Confirm status shows configured without exposing the full value. Because the credential appeared in chat, advise rotation after the smoke.

- [ ] **Step 3: Execute one minimal paid streaming request through the complete UI path**

Use a short non-sensitive input. Record only Provider ID, model, status category, first-token latency, total latency and cancellation result; do not record request/response text or credential details. Do not automatically retry a paid call after content begins.

- [ ] **Step 4: Execute one cancellation smoke**

Start one short request and cancel after streaming begins. Confirm the UI returns to Ready, Runtime stops yielding chunks for that request, and the app remains usable for a new offline fixture request.

- [ ] **Step 5: Run the full fresh Stage A verification again**

Repeat the exact commands from Task 7 Step 2 and review `git diff --check`, `git status --short`, and `git diff --stat`. Confirm `resources\` remains untracked and absent from all staged paths.

- [ ] **Step 6: Update verification evidence without sensitive values**

Append the smoke outcome categories and timings to `docs/verification/stage-a-verification.md`. Do not record the model response, prompt, key, key tail or credential account.

- [ ] **Step 7: Commit and push the Stage A gate**

```powershell
git add docs\verification\stage-a-verification.md
git commit -m "docs: 完成阶段 A 真实链路验收 | v0.2.0-a | 2026-07-10 HH:MM"
git push origin codex/full-feature-parity
```

Expected: push succeeds; remote branch points to the verification commit; `resources\` remains local and untracked.

## Release Risks and Recovery

- Windows Credential Manager unavailable: keep the settings dialog open, show a fixed retry message, do not fall back to plaintext files.
- Config write interrupted: recover from `config.json.bak`; never overwrite both primary and backup in one operation.
- Plugin load failure: keep Runtime alive and return `provider_unconfigured` for the selected Provider; never auto-switch to Mock.
- Provider protocol drift: fail with `provider_invalid_response`; fixture updates require official documentation evidence.
- Paid request ambiguity: do not retry after the first yielded chunk; record only anonymous timing/category evidence.
- Runtime crash after configuration: Rust reads the credential again and re-sends private configuration to the fresh Sidecar before optimize.
- Rollback: revert Stage A commits in reverse order, restore last valid config backup, and delete the Windows credential entry; user data under `resources\` is untouched.
