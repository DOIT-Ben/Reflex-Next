use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use base64::Engine;
use serde_json::Value;
use tauri::{AppHandle, Emitter, LogicalSize, Manager, State, WebviewWindow};
use tauri_plugin_dialog::{DialogExt, MessageDialogButtons, MessageDialogKind};

use crate::config_store::{AppConfig, ConfigStore};
use crate::desktop::{DesktopState, DesktopStatus};
use crate::history_key_store::HistoryKeyStore;
use crate::runtime_commands::{
    configure_history_keyring_command, configure_history_path_command,
    configure_history_policy_command, configure_plugin_command, configure_provider_command,
    list_providers_command, plugin_admin_command, validate_command, CommandKind, ValidatedCommand,
};
use crate::secret_store::{CredentialBackend, SecretStatus, SecretStore};
use crate::sidecar::{
    EventEmitter, PrivateEventStream, PrivateRuntimeGeneration, RuntimeController,
};

pub struct TauriRuntimeState {
    runtime: RuntimeController,
}

pub struct HistoryOperationControl {
    running: AtomicBool,
    cancelled: AtomicBool,
    commit_lock: Mutex<()>,
}

impl HistoryOperationControl {
    pub fn new() -> Self {
        Self {
            running: AtomicBool::new(false),
            cancelled: AtomicBool::new(false),
            commit_lock: Mutex::new(()),
        }
    }

    fn begin(&self) -> Result<(), String> {
        let _guard = self
            .commit_lock
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if self.running.swap(true, Ordering::AcqRel) {
            return Err("历史操作正在进行，请稍候。".to_string());
        }
        self.cancelled.store(false, Ordering::Release);
        Ok(())
    }

    fn finish(&self) {
        let _guard = self
            .commit_lock
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        self.running.store(false, Ordering::Release);
        self.cancelled.store(false, Ordering::Release);
    }

    fn cancel(&self) {
        let _guard = self
            .commit_lock
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if self.running.load(Ordering::Acquire) {
            self.cancelled.store(true, Ordering::Release);
        }
    }

    fn is_cancelled(&self) -> bool {
        self.cancelled.load(Ordering::Acquire)
    }

    fn with_commit<T>(
        &self,
        commit: impl FnOnce() -> Result<T, String>,
    ) -> Result<Option<T>, String> {
        let _guard = self
            .commit_lock
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if self.is_cancelled() {
            return Ok(None);
        }
        commit().map(Some)
    }
}

impl TauriRuntimeState {
    pub fn new(app: AppHandle) -> Self {
        Self {
            runtime: RuntimeController::new(Arc::new(TauriEventEmitter { app })),
        }
    }

    pub fn shutdown(&self) {
        self.runtime.shutdown();
    }

    pub(crate) fn runtime(&self) -> &RuntimeController {
        &self.runtime
    }
}

struct TauriEventEmitter {
    app: AppHandle,
}

impl EventEmitter for TauriEventEmitter {
    fn emit(&self, event_name: &str, payload: Value) {
        let _ = self.app.emit_to("main", event_name, payload);
    }

    fn emit_to(&self, target: &str, event_name: &str, payload: Value) {
        let _ = self.app.emit_to(target, event_name, payload);
    }
}

fn runtime_available_value() -> bool {
    crate::sidecar::resolve_runtime_paths().is_ok()
}

const WINDOW_CONTROL_UNAVAILABLE_MESSAGE: &str = "窗口操作暂不可用，请稍后重试。";

fn window_size_preset(preset: &str) -> Option<(f64, f64)> {
    match preset {
        "compact" => Some((680.0, 480.0)),
        "default" => Some((760.0, 540.0)),
        "wide" => Some((900.0, 640.0)),
        _ => None,
    }
}

#[tauri::command]
pub async fn read_clipboard_text(app: AppHandle) -> Result<String, String> {
    crate::clipboard::read_clipboard_text(&app).map_err(str::to_string)
}

#[tauri::command]
pub async fn write_clipboard_text(app: AppHandle, text: String) -> Result<(), String> {
    crate::clipboard::write_clipboard_text(&app, &text).map_err(str::to_string)
}

#[tauri::command]
pub async fn show_main_window(app: AppHandle) -> Result<(), String> {
    crate::window::show_main_window(&app).map_err(str::to_string)
}

#[tauri::command]
pub async fn hide_main_window(app: AppHandle) -> Result<(), String> {
    crate::window::hide_main_window(&app).map_err(str::to_string)
}

#[tauri::command]
pub async fn show_history_window(app: AppHandle) -> Result<(), String> {
    crate::window::show_history_window(&app).map_err(str::to_string)
}

#[tauri::command]
pub async fn minimize_window(window: WebviewWindow) -> Result<(), String> {
    require_main_window(window.label())?;
    window
        .minimize()
        .map_err(|_| WINDOW_CONTROL_UNAVAILABLE_MESSAGE.to_string())
}

#[tauri::command]
pub async fn toggle_maximize_window(window: WebviewWindow) -> Result<(), String> {
    require_main_window(window.label())?;
    let maximized = window
        .is_maximized()
        .map_err(|_| WINDOW_CONTROL_UNAVAILABLE_MESSAGE.to_string())?;
    if maximized {
        window
            .unmaximize()
            .map_err(|_| WINDOW_CONTROL_UNAVAILABLE_MESSAGE.to_string())
    } else {
        window
            .maximize()
            .map_err(|_| WINDOW_CONTROL_UNAVAILABLE_MESSAGE.to_string())
    }
}

#[tauri::command]
pub async fn set_window_size(window: WebviewWindow, preset: String) -> Result<(), String> {
    require_main_window(window.label())?;
    let Some((width, height)) = window_size_preset(&preset) else {
        return Err(WINDOW_CONTROL_UNAVAILABLE_MESSAGE.to_string());
    };
    window
        .set_size(LogicalSize::new(width, height))
        .map_err(|_| WINDOW_CONTROL_UNAVAILABLE_MESSAGE.to_string())
}

#[tauri::command]
pub async fn runtime_available() -> bool {
    runtime_available_value()
}

#[tauri::command]
pub async fn desktop_status(state: State<'_, DesktopState>) -> Result<DesktopStatus, String> {
    Ok(state.status())
}

#[tauri::command]
pub async fn load_app_config(state: State<'_, ConfigStore>) -> Result<AppConfig, String> {
    state.load().map_err(|error| error.to_string())
}

#[tauri::command]
pub async fn save_app_config(
    app: AppHandle,
    state: State<'_, ConfigStore>,
    desktop_state: State<'_, DesktopState>,
    runtime_state: State<'_, TauriRuntimeState>,
    history_key_store: State<'_, HistoryKeyStore>,
    config: AppConfig,
) -> Result<AppConfig, String> {
    let normalized = AppConfig::from_value(
        serde_json::to_value(config).map_err(|_| "配置存储暂不可用。".to_string())?,
    )
    .map_err(|error| error.to_string())?;
    let requested_hotkey = normalized.hotkey.clone();
    runtime_state.runtime.replace_provider_credentials(|| {
        let previous = state.load().map_err(|error| error.to_string())?;
        let persist = || {
            crate::desktop::replace_hotkey_and_persist(
                &app,
                &desktop_state,
                &requested_hotkey,
                || state.save(&normalized).map_err(|error| error.to_string()),
            )
        };
        with_prepared_history_transition(&previous, &normalized, &history_key_store, persist)
    })
}

#[tauri::command]
pub async fn provider_secret_status(
    state: State<'_, SecretStore>,
    provider_id: String,
) -> Result<SecretStatus, String> {
    state
        .status(&provider_id)
        .map_err(|error| error.to_string())
}

#[tauri::command]
pub async fn save_provider_secret(
    state: State<'_, SecretStore>,
    runtime_state: State<'_, TauriRuntimeState>,
    provider_id: String,
    secret: String,
) -> Result<SecretStatus, String> {
    runtime_state.runtime.replace_provider_credentials(|| {
        state
            .save(&provider_id, &secret)
            .map_err(|error| error.to_string())
    })
}

#[tauri::command]
pub async fn delete_provider_secret(
    state: State<'_, SecretStore>,
    runtime_state: State<'_, TauriRuntimeState>,
    provider_id: String,
) -> Result<SecretStatus, String> {
    runtime_state.runtime.replace_provider_credentials(|| {
        state
            .delete(&provider_id)
            .map_err(|error| error.to_string())
    })
}

#[tauri::command]
pub async fn runtime_optimize(
    app: AppHandle,
    window: tauri::WebviewWindow,
    state: State<'_, TauriRuntimeState>,
    config_store: State<'_, ConfigStore>,
    secret_store: State<'_, SecretStore>,
    history_key_store: State<'_, HistoryKeyStore>,
    command: Value,
) -> Result<(), String> {
    require_main_window(window.label())?;
    let command = validate_command(command, CommandKind::Optimize).map_err(str::to_string)?;
    let history_path = app
        .path()
        .app_data_dir()
        .map(|path| history_database_path(&path))
        .map_err(|_| "应用数据目录不可用。".to_string())?;
    send_configured_optimize_to(
        &state.runtime,
        &config_store,
        &secret_store,
        &history_key_store,
        &history_path,
        window.label(),
        command,
    )
}

#[tauri::command]
pub async fn runtime_cancel(
    window: tauri::WebviewWindow,
    state: State<'_, TauriRuntimeState>,
    command: Value,
) -> Result<(), String> {
    require_main_window(window.label())?;
    forward_runtime_command_to(&state.runtime, window.label(), command, CommandKind::Cancel)
}

#[tauri::command]
pub async fn runtime_list_providers(
    window: tauri::WebviewWindow,
    state: State<'_, TauriRuntimeState>,
) -> Result<(), String> {
    require_main_window(window.label())?;
    state
        .runtime()
        .send_to(list_providers_command(), window.label())
        .map_err(str::to_string)
}

#[tauri::command]
pub async fn runtime_list_plugins(
    window: tauri::WebviewWindow,
    state: State<'_, TauriRuntimeState>,
    command: Value,
) -> Result<(), String> {
    require_main_window(window.label())?;
    let command = validate_command(command, CommandKind::ListPlugins).map_err(str::to_string)?;
    state
        .runtime()
        .send_to(command, window.label())
        .map_err(str::to_string)
}

#[tauri::command]
pub async fn runtime_plugin_call(
    app: AppHandle,
    window: tauri::WebviewWindow,
    state: State<'_, TauriRuntimeState>,
    config_store: State<'_, ConfigStore>,
    secret_store: State<'_, SecretStore>,
    history_key_store: State<'_, HistoryKeyStore>,
    command: Value,
) -> Result<(), String> {
    let command = crate::plugin_commands::validate_authorized_plugin_call(window.label(), command)
        .map_err(str::to_string)?;
    if command.payload.get("plugin_id").and_then(Value::as_str) == Some("history-sqlite") {
        let history_path = app
            .path()
            .app_data_dir()
            .map(|path| history_database_path(&path))
            .map_err(|_| "应用数据目录不可用。".to_string())?;
        return send_configured_plugin_call_to(
            state.runtime(),
            &config_store,
            &secret_store,
            &history_key_store,
            &history_path,
            window.label(),
            command,
        );
    }
    let result = send_configured_plugin_call_to(
        state.runtime(),
        &config_store,
        &secret_store,
        &history_key_store,
        &app.path()
            .app_data_dir()
            .map(|path| history_database_path(&path))
            .map_err(|_| "应用数据目录不可用。".to_string())?,
        window.label(),
        command,
    );
    result
}

#[tauri::command]
pub async fn runtime_plugin_cancel(
    window: tauri::WebviewWindow,
    state: State<'_, TauriRuntimeState>,
    command: Value,
) -> Result<(), String> {
    forward_runtime_command_to(
        state.runtime(),
        window.label(),
        command,
        CommandKind::Cancel,
    )
}

const HISTORY_OPERATION_ERROR_MESSAGE: &str = "历史操作失败，请重试。";

#[derive(serde::Deserialize)]
pub(crate) struct HistoryReuseIntent {
    kind: String,
    history_id: String,
}

const HISTORY_REUSE_EVENT: &str = "reflex://history-reuse";
static HISTORY_REUSE_SEQUENCE: AtomicU64 = AtomicU64::new(0);

fn history_reuse_payload(
    intent: &HistoryReuseIntent,
    detail: &Value,
    sequence: u64,
) -> Result<Value, String> {
    if !crate::window::reuse_intent_is_valid(&intent.kind, &intent.history_id) {
        return Err(HISTORY_OPERATION_ERROR_MESSAGE.to_string());
    }
    let record = detail
        .get("record")
        .and_then(Value::as_object)
        .ok_or_else(|| HISTORY_OPERATION_ERROR_MESSAGE.to_string())?;
    if record.get("id").and_then(Value::as_str) != Some(intent.history_id.as_str()) {
        return Err(HISTORY_OPERATION_ERROR_MESSAGE.to_string());
    }
    let key = if intent.kind == "input" {
        "input"
    } else {
        "output"
    };
    let text = record
        .get(key)
        .and_then(Value::as_str)
        .filter(|text| !text.is_empty())
        .ok_or_else(|| HISTORY_OPERATION_ERROR_MESSAGE.to_string())?;
    if intent.kind == "input" {
        return Ok(
            serde_json::json!({ "version": 1, "sequence": sequence, "history_id": intent.history_id, "kind": intent.kind, "text": text }),
        );
    }

    let optional_text = |key: &str| -> Result<Value, String> {
        match record.get(key) {
            Some(Value::Null) => Ok(Value::Null),
            Some(Value::String(value))
                if !value.is_empty()
                    && value.chars().count() <= 128
                    && !value.chars().any(|character| character < ' ') =>
            {
                Ok(Value::String(value.clone()))
            }
            _ => Err(HISTORY_OPERATION_ERROR_MESSAGE.to_string()),
        }
    };
    let scene = optional_text("scene")?;
    let model = optional_text("model")?;
    let style = record
        .get("style")
        .and_then(Value::as_str)
        .filter(|value| {
            matches!(
                *value,
                "concise" | "balanced" | "detailed" | "creative" | "precise"
            )
        })
        .ok_or_else(|| HISTORY_OPERATION_ERROR_MESSAGE.to_string())?;
    let mode = record
        .get("mode")
        .and_then(Value::as_str)
        .filter(|value| matches!(*value, "content" | "prompt"))
        .ok_or_else(|| HISTORY_OPERATION_ERROR_MESSAGE.to_string())?;
    let provider = record
        .get("provider")
        .and_then(Value::as_str)
        .filter(|value| {
            !value.is_empty()
                && value.len() <= 128
                && value.bytes().enumerate().all(|(index, byte)| {
                    byte.is_ascii_alphanumeric()
                        || (index > 0 && matches!(byte, b'.' | b'_' | b'-'))
                })
        })
        .ok_or_else(|| HISTORY_OPERATION_ERROR_MESSAGE.to_string())?;
    let elapsed_ms = match record.get("elapsed_ms") {
        Some(Value::Null) => Value::Null,
        Some(value)
            if value
                .as_u64()
                .is_some_and(|number| number <= i32::MAX as u64) =>
        {
            value.clone()
        }
        _ => return Err(HISTORY_OPERATION_ERROR_MESSAGE.to_string()),
    };
    let rating = match record.get("rating") {
        Some(Value::Null) => Value::Null,
        Some(value)
            if value
                .as_u64()
                .is_some_and(|number| (1..=5).contains(&number)) =>
        {
            value.clone()
        }
        _ => return Err(HISTORY_OPERATION_ERROR_MESSAGE.to_string()),
    };
    let source_text = record
        .get("input")
        .and_then(Value::as_str)
        .filter(|value| {
            !value.trim().is_empty() && value.chars().count() <= 1_000_000 && !value.contains('\0')
        })
        .map(Value::from)
        .unwrap_or(Value::Null);

    Ok(serde_json::json!({
        "version": 1,
        "sequence": sequence,
        "history_id": intent.history_id,
        "kind": intent.kind,
        "text": text,
        "source_text": source_text,
        "scene": scene,
        "style": style,
        "mode": mode,
        "provider": provider,
        "model": model,
        "elapsed_ms": elapsed_ms,
        "rating": rating
    }))
}

#[tauri::command]
pub async fn history_reuse_intent(
    app: AppHandle,
    window: tauri::WebviewWindow,
    state: State<'_, TauriRuntimeState>,
    config_store: State<'_, ConfigStore>,
    history_key_store: State<'_, HistoryKeyStore>,
    intent: HistoryReuseIntent,
) -> Result<(), String> {
    if window.label() != "history"
        || !crate::window::reuse_intent_is_valid(&intent.kind, &intent.history_id)
    {
        return Err(HISTORY_OPERATION_ERROR_MESSAGE.to_string());
    }
    let reuse_sequence = HISTORY_REUSE_SEQUENCE.fetch_add(1, Ordering::Relaxed) + 1;
    let history_path = app
        .path()
        .app_data_dir()
        .map(|path| history_database_path(&path))
        .map_err(|_| HISTORY_OPERATION_ERROR_MESSAGE.to_string())?;
    let request_id = format!(
        "history-reuse-{}",
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map_err(|_| HISTORY_OPERATION_ERROR_MESSAGE.to_string())?
            .as_nanos()
    );
    let detail_command = ValidatedCommand {
        request_id,
        kind: CommandKind::PluginCall,
        payload: serde_json::json!({ "plugin_id": "history-sqlite", "operation": "detail", "input": { "id": intent.history_id } }),
    };
    let stream = state.runtime().with_lifecycle(|runtime, _| {
        let persisted = config_store
            .load()
            .map_err(|_| HISTORY_OPERATION_ERROR_MESSAGE.to_string())?;
        let mut sequence =
            build_history_config_sequence(&persisted, &history_key_store, &history_path, false)?;
        sequence.push(detail_command);
        runtime
            .send_private_sequence_unlocked(sequence)
            .map_err(|_| HISTORY_OPERATION_ERROR_MESSAGE.to_string())
    })?;
    let detail = match collect_history_admin(stream, &HistoryOperationControl::new(), false)? {
        HistoryAdminOutcome::Completed(response) => response.data,
        HistoryAdminOutcome::Cancelled => return Err(HISTORY_OPERATION_ERROR_MESSAGE.to_string()),
    };
    let payload = history_reuse_payload(&intent, &detail, reuse_sequence)?;
    app.emit_to("main", HISTORY_REUSE_EVENT, payload)
        .map_err(|_| HISTORY_OPERATION_ERROR_MESSAGE.to_string())
}

#[tauri::command]
pub async fn history_export(
    app: AppHandle,
    window: tauri::WebviewWindow,
    state: State<'_, TauriRuntimeState>,
    config_store: State<'_, ConfigStore>,
    history_key_store: State<'_, HistoryKeyStore>,
    control: State<'_, HistoryOperationControl>,
    request: Value,
) -> Result<String, String> {
    crate::plugin_commands::authorize_history_management(window.label(), "export")
        .map_err(str::to_string)?;
    let request =
        crate::history_export::validate_export_request(request).map_err(str::to_string)?;
    let confirmed = app
        .dialog()
        .message("导出的历史记录将以明文保存。请仅保存到可信位置。")
        .title("导出历史记录")
        .kind(MessageDialogKind::Warning)
        .buttons(MessageDialogButtons::OkCancel)
        .blocking_show();
    if !confirmed {
        return Ok("cancelled".to_string());
    }
    let selected = app
        .dialog()
        .file()
        .set_title("导出历史记录")
        .set_file_name(format!("reflex-history.{}", request.format.extension()))
        .add_filter("历史记录", &[request.format.extension()])
        .blocking_save_file();
    let Some(target) = selected.and_then(|path| path.into_path().ok()) else {
        return Ok("cancelled".to_string());
    };
    let app_data_dir = app
        .path()
        .app_data_dir()
        .map_err(|_| HISTORY_OPERATION_ERROR_MESSAGE.to_string())?;
    let history_path = history_database_path(&app_data_dir);
    let export_journal = crate::history_export::pending_export_journal(&app_data_dir);
    let input = serde_json::json!({
        "format": request.format.wire_name(),
        "filters": request.filters,
    });
    control.begin()?;
    let result = run_history_export(
        state.runtime(),
        &config_store,
        &history_key_store,
        &history_path,
        input,
        &control,
        &target,
        &export_journal,
    );
    control.finish();
    Ok(if result? { "completed" } else { "cancelled" }.to_string())
}

#[tauri::command]
pub async fn history_admin_operation(
    app: AppHandle,
    window: tauri::WebviewWindow,
    state: State<'_, TauriRuntimeState>,
    config_store: State<'_, ConfigStore>,
    history_key_store: State<'_, HistoryKeyStore>,
    control: State<'_, HistoryOperationControl>,
    operation: String,
    input: Value,
) -> Result<String, String> {
    crate::plugin_commands::authorize_history_management(window.label(), &operation)
        .map_err(str::to_string)?;
    if !input.is_object() {
        return Err(crate::plugin_commands::PLUGIN_COMMAND_DENIED_MESSAGE.to_string());
    }
    let confirmed = app
        .dialog()
        .message(history_confirmation_message(&operation))
        .title("确认历史操作")
        .kind(MessageDialogKind::Warning)
        .buttons(MessageDialogButtons::OkCancel)
        .blocking_show();
    if !confirmed {
        return Ok("cancelled".to_string());
    }
    let history_path = app
        .path()
        .app_data_dir()
        .map(|path| history_database_path(&path))
        .map_err(|_| HISTORY_OPERATION_ERROR_MESSAGE.to_string())?;
    if operation == "rotate" {
        control.begin()?;
        let result = rotate_history_keys(
            state.runtime(),
            &config_store,
            &history_key_store,
            &history_path,
            &control,
        );
        control.finish();
        if !result? {
            return Ok("cancelled".to_string());
        }
    } else {
        control.begin()?;
        let result = run_history_admin(
            state.runtime(),
            &config_store,
            &history_key_store,
            &history_path,
            &operation,
            input,
            &control,
            true,
        );
        control.finish();
        if matches!(result?, HistoryAdminOutcome::Cancelled) {
            return Ok("cancelled".to_string());
        }
    }
    Ok("completed".to_string())
}

#[tauri::command]
pub async fn history_operation_cancel(
    window: tauri::WebviewWindow,
    control: State<'_, HistoryOperationControl>,
) -> Result<(), String> {
    if window.label() != "history" {
        return Err(crate::plugin_commands::PLUGIN_COMMAND_DENIED_MESSAGE.to_string());
    }
    control.cancel();
    Ok(())
}

struct PrivateAdminResponse {
    data: Value,
    generation: PrivateRuntimeGeneration,
}

enum HistoryAdminOutcome {
    Completed(PrivateAdminResponse),
    Cancelled,
}

fn run_history_admin<H>(
    runtime: &RuntimeController,
    config_store: &ConfigStore,
    history_key_store: &HistoryKeyStore<H>,
    history_path: &Path,
    operation: &str,
    input: Value,
    control: &HistoryOperationControl,
    cancellable: bool,
) -> Result<HistoryAdminOutcome, String>
where
    H: CredentialBackend,
{
    let stream = start_history_admin_stream(
        runtime,
        config_store,
        history_key_store,
        history_path,
        operation,
        input,
    )?;
    collect_history_admin(stream, control, cancellable)
}

fn run_history_admin_for_generation<H>(
    runtime: &RuntimeController,
    config_store: &ConfigStore,
    history_key_store: &HistoryKeyStore<H>,
    history_path: &Path,
    operation: &str,
    input: Value,
    control: &HistoryOperationControl,
    generation: &PrivateRuntimeGeneration,
) -> Result<HistoryAdminOutcome, String>
where
    H: CredentialBackend,
{
    let stream = start_history_admin_stream_for_generation(
        runtime,
        config_store,
        history_key_store,
        history_path,
        operation,
        input,
        generation,
    )?;
    collect_history_admin(stream, control, false)
}

fn collect_history_admin(
    mut stream: PrivateEventStream,
    control: &HistoryOperationControl,
    cancellable: bool,
) -> Result<HistoryAdminOutcome, String> {
    loop {
        if cancellable && control.is_cancelled() {
            stream.cancel();
            return Ok(HistoryAdminOutcome::Cancelled);
        }
        let payload = match stream
            .poll_timeout(Duration::from_millis(250))
            .map_err(|_| HISTORY_OPERATION_ERROR_MESSAGE.to_string())?
        {
            Some(payload) => payload,
            None => continue,
        };
        let status = payload.get("status").and_then(Value::as_str);
        match status {
            Some("started" | "progress") => {}
            Some("chunk") => return Err(HISTORY_OPERATION_ERROR_MESSAGE.to_string()),
            Some("result") => {
                let generation = stream.generation();
                return Ok(HistoryAdminOutcome::Completed(PrivateAdminResponse {
                    data: payload
                        .get("data")
                        .cloned()
                        .unwrap_or_else(|| serde_json::json!({})),
                    generation,
                }));
            }
            Some("cancelled" | "error") | None => {
                return Err(HISTORY_OPERATION_ERROR_MESSAGE.to_string());
            }
            _ => return Err(HISTORY_OPERATION_ERROR_MESSAGE.to_string()),
        }
    }
}

fn run_history_export<H>(
    runtime: &RuntimeController,
    config_store: &ConfigStore,
    history_key_store: &HistoryKeyStore<H>,
    history_path: &Path,
    input: Value,
    control: &HistoryOperationControl,
    target: &Path,
    export_journal: &Path,
) -> Result<bool, String>
where
    H: CredentialBackend,
{
    let mut stream = start_history_admin_stream(
        runtime,
        config_store,
        history_key_store,
        history_path,
        "export",
        input,
    )?;
    let mut writer =
        crate::history_export::AtomicExportWriter::new_registered(target, export_journal)
            .map_err(str::to_string)?;
    loop {
        if control.is_cancelled() {
            stream.cancel();
            return Ok(false);
        }
        let payload = match stream
            .poll_timeout(Duration::from_millis(250))
            .map_err(|_| HISTORY_OPERATION_ERROR_MESSAGE.to_string())?
        {
            Some(payload) => payload,
            None => continue,
        };
        match payload.get("status").and_then(Value::as_str) {
            Some("started" | "progress") => {}
            Some("chunk") => {
                let encoded = payload
                    .pointer("/data/bytes")
                    .and_then(Value::as_str)
                    .ok_or_else(|| HISTORY_OPERATION_ERROR_MESSAGE.to_string())?;
                let decoded = base64::engine::general_purpose::STANDARD
                    .decode(encoded)
                    .map_err(|_| HISTORY_OPERATION_ERROR_MESSAGE.to_string())?;
                writer.write_chunk(&decoded).map_err(str::to_string)?;
            }
            Some("result") => {
                return commit_history_export(writer, control);
            }
            Some("cancelled" | "error") | None => {
                return Err(HISTORY_OPERATION_ERROR_MESSAGE.to_string());
            }
            _ => return Err(HISTORY_OPERATION_ERROR_MESSAGE.to_string()),
        }
    }
}

fn commit_history_export(
    writer: crate::history_export::AtomicExportWriter,
    control: &HistoryOperationControl,
) -> Result<bool, String> {
    control
        .with_commit(|| writer.commit().map_err(str::to_string))
        .map(|committed| committed.is_some())
}

fn start_history_admin_stream<H>(
    runtime: &RuntimeController,
    config_store: &ConfigStore,
    history_key_store: &HistoryKeyStore<H>,
    history_path: &Path,
    operation: &str,
    input: Value,
) -> Result<PrivateEventStream, String>
where
    H: CredentialBackend,
{
    let commands = build_history_admin_sequence(
        config_store,
        history_key_store,
        history_path,
        operation,
        input,
    )?;
    runtime
        .send_private_sequence(commands)
        .map_err(|_| HISTORY_OPERATION_ERROR_MESSAGE.to_string())
}

fn start_history_admin_stream_for_generation<H>(
    runtime: &RuntimeController,
    config_store: &ConfigStore,
    history_key_store: &HistoryKeyStore<H>,
    history_path: &Path,
    operation: &str,
    input: Value,
    generation: &PrivateRuntimeGeneration,
) -> Result<PrivateEventStream, String>
where
    H: CredentialBackend,
{
    let commands = build_history_admin_sequence(
        config_store,
        history_key_store,
        history_path,
        operation,
        input,
    )?;
    runtime
        .send_private_sequence_for_generation(commands, generation)
        .map_err(|_| HISTORY_OPERATION_ERROR_MESSAGE.to_string())
}

fn build_history_admin_sequence<H>(
    config_store: &ConfigStore,
    history_key_store: &HistoryKeyStore<H>,
    history_path: &Path,
    operation: &str,
    input: Value,
) -> Result<Vec<ValidatedCommand>, String>
where
    H: CredentialBackend,
{
    let persisted = config_store
        .load()
        .map_err(|_| HISTORY_OPERATION_ERROR_MESSAGE.to_string())?;
    let mut commands =
        build_history_config_sequence(&persisted, history_key_store, history_path, false)?;
    commands.push(
        plugin_admin_command("history-sqlite", operation, input)
            .map_err(|_| HISTORY_OPERATION_ERROR_MESSAGE.to_string())?,
    );
    Ok(commands)
}

fn rotate_history_keys<H>(
    runtime: &RuntimeController,
    config_store: &ConfigStore,
    history_key_store: &HistoryKeyStore<H>,
    history_path: &Path,
    control: &HistoryOperationControl,
) -> Result<bool, String>
where
    H: CredentialBackend,
{
    if resume_promoted_rotation(history_key_store, |active| {
        match run_history_admin(
            runtime,
            config_store,
            history_key_store,
            history_path,
            "rotate",
            serde_json::json!({"action": "resume", "target_version": format!("v{active}")}),
            control,
            false,
        )? {
            HistoryAdminOutcome::Completed(response) => {
                Ok(response.data.get("resumed").and_then(Value::as_bool) == Some(true))
            }
            HistoryAdminOutcome::Cancelled => Err(HISTORY_OPERATION_ERROR_MESSAGE.to_string()),
        }
    })? {
        return Ok(true);
    }
    let status = history_key_store
        .begin_rotation()
        .map_err(|_| HISTORY_OPERATION_ERROR_MESSAGE.to_string())?;
    let target = status
        .pending_version
        .ok_or_else(|| HISTORY_OPERATION_ERROR_MESSAGE.to_string())?;
    let prepared = run_history_admin(
        runtime,
        config_store,
        history_key_store,
        history_path,
        "rotate",
        serde_json::json!({"action": "prepare", "target_version": format!("v{target}")}),
        control,
        true,
    );
    let Some(prepared) = resolve_rotation_prepare(prepared)? else {
        return Ok(false);
    };
    if prepared
        .data
        .get("promotion_required")
        .and_then(Value::as_bool)
        != Some(true)
    {
        return Err(HISTORY_OPERATION_ERROR_MESSAGE.to_string());
    }
    let generation = prepared.generation;
    promote_history_rotation_or_rollback(history_key_store, || {
        match run_history_admin_for_generation(
            runtime,
            config_store,
            history_key_store,
            history_path,
            "rotate",
            serde_json::json!({"action": "rollback", "target_version": format!("v{target}")}),
            control,
            &generation,
        )? {
            HistoryAdminOutcome::Completed(_) => Ok(()),
            HistoryAdminOutcome::Cancelled => Err(HISTORY_OPERATION_ERROR_MESSAGE.to_string()),
        }
    })?;
    let finalized = run_history_admin(
        runtime,
        config_store,
        history_key_store,
        history_path,
        "rotate",
        serde_json::json!({"action": "finalize", "target_version": format!("v{target}")}),
        control,
        false,
    )?;
    if matches!(finalized, HistoryAdminOutcome::Completed(_)) {
        Ok(true)
    } else {
        Err(HISTORY_OPERATION_ERROR_MESSAGE.to_string())
    }
}

fn resolve_rotation_prepare(
    prepared: Result<HistoryAdminOutcome, String>,
) -> Result<Option<PrivateAdminResponse>, String> {
    match prepared {
        Ok(HistoryAdminOutcome::Completed(response)) => Ok(Some(response)),
        Ok(HistoryAdminOutcome::Cancelled) => Ok(None),
        Err(error) => Err(error),
    }
}

fn resume_promoted_rotation<H>(
    history_key_store: &HistoryKeyStore<H>,
    resume: impl FnOnce(u32) -> Result<bool, String>,
) -> Result<bool, String>
where
    H: CredentialBackend,
{
    let status = history_key_store
        .status()
        .map_err(|_| HISTORY_OPERATION_ERROR_MESSAGE.to_string())?;
    if status.pending_version.is_some() {
        return Ok(false);
    }
    let Some(active) = status.active_version else {
        return Ok(false);
    };
    resume(active)
}

fn promote_history_rotation_or_rollback<H>(
    history_key_store: &HistoryKeyStore<H>,
    rollback_python: impl FnOnce() -> Result<(), String>,
) -> Result<(), String>
where
    H: CredentialBackend,
{
    if history_key_store.promote().is_ok() {
        return Ok(());
    }
    if rollback_python().is_err() {
        return Err(HISTORY_OPERATION_ERROR_MESSAGE.to_string());
    }
    history_key_store
        .rollback()
        .map_err(|_| HISTORY_OPERATION_ERROR_MESSAGE.to_string())?;
    Err(HISTORY_OPERATION_ERROR_MESSAGE.to_string())
}

fn history_confirmation_message(operation: &str) -> &'static str {
    match operation {
        "delete" => "确定删除这条历史记录吗？",
        "clear" => "确定清空全部历史记录吗？此操作不可撤销。",
        "repair" => "确定扫描并修复历史记录吗？操作前会创建备份。",
        "restore" => "确定恢复所选备份吗？当前历史会先备份。",
        "rotate" => "确定轮换历史加密密钥吗？操作期间历史写入会暂停。",
        _ => "确定继续此历史操作吗？",
    }
}

fn require_main_window(window_label: &str) -> Result<(), String> {
    if window_label == "main" {
        Ok(())
    } else {
        Err(crate::plugin_commands::PLUGIN_COMMAND_DENIED_MESSAGE.to_string())
    }
}

fn forward_runtime_command_to(
    runtime: &RuntimeController,
    target: &str,
    command: Value,
    expected_kind: CommandKind,
) -> Result<(), String> {
    let command = validate_command(command, expected_kind).map_err(str::to_string)?;
    runtime.send_to(command, target).map_err(str::to_string)
}

#[cfg(test)]
fn send_configured_optimize<B, H>(
    runtime: &RuntimeController,
    config_store: &ConfigStore,
    secret_store: &SecretStore<B>,
    history_key_store: &HistoryKeyStore<H>,
    history_path: &Path,
    command: ValidatedCommand,
) -> Result<(), String>
where
    B: CredentialBackend,
    H: CredentialBackend,
{
    send_configured_optimize_to(
        runtime,
        config_store,
        secret_store,
        history_key_store,
        history_path,
        "main",
        command,
    )
}

fn send_configured_optimize_to<B, H>(
    runtime: &RuntimeController,
    config_store: &ConfigStore,
    secret_store: &SecretStore<B>,
    history_key_store: &HistoryKeyStore<H>,
    history_path: &Path,
    target: &str,
    command: ValidatedCommand,
) -> Result<(), String>
where
    B: CredentialBackend,
    H: CredentialBackend,
{
    runtime.with_lifecycle(|runtime, _generation| {
        let request_id = command.request_id.clone();
        match build_configured_optimize_sequence(
            config_store,
            secret_store,
            history_key_store,
            history_path,
            command,
        )? {
            Some(commands) => runtime
                .send_sequence_unlocked_to(commands, target)
                .map_err(str::to_string),
            None => runtime
                .emit_provider_unconfigured_unlocked_to(&request_id, target)
                .map_err(str::to_string),
        }
    })
}

fn send_configured_plugin_call_to<B, H>(
    runtime: &RuntimeController,
    config_store: &ConfigStore,
    secret_store: &SecretStore<B>,
    history_key_store: &HistoryKeyStore<H>,
    history_path: &Path,
    target: &str,
    command: ValidatedCommand,
) -> Result<(), String>
where
    B: CredentialBackend,
    H: CredentialBackend,
{
    runtime.with_lifecycle(|runtime, _generation| {
        let commands = build_configured_plugin_call_sequence(
            config_store,
            secret_store,
            history_key_store,
            history_path,
            command,
        )?;
        runtime
            .send_sequence_unlocked_to(commands, target)
            .map_err(str::to_string)
    })
}

fn build_configured_plugin_call_sequence<B, H>(
    config_store: &ConfigStore,
    secret_store: &SecretStore<B>,
    history_key_store: &HistoryKeyStore<H>,
    history_path: &Path,
    command: ValidatedCommand,
) -> Result<Vec<ValidatedCommand>, String>
where
    B: CredentialBackend,
    H: CredentialBackend,
{
    let plugin_id = command
        .payload
        .get("plugin_id")
        .and_then(Value::as_str)
        .ok_or_else(|| crate::plugin_commands::PLUGIN_COMMAND_DENIED_MESSAGE.to_string())?;
    if plugin_id == "history-sqlite" {
        let persisted = config_store.load().map_err(|error| error.to_string())?;
        let mut commands =
            build_history_config_sequence(&persisted, history_key_store, history_path, false)?;
        commands.push(command);
        return Ok(commands);
    }
    let persisted = config_store.load().map_err(|error| error.to_string())?;
    let mut commands = Vec::with_capacity(3);
    if plugin_id == "translator" {
        let input = command
            .payload
            .get("input")
            .and_then(Value::as_object)
            .ok_or_else(|| crate::plugin_commands::PLUGIN_COMMAND_DENIED_MESSAGE.to_string())?;
        let provider_id = input
            .get("provider")
            .and_then(Value::as_str)
            .filter(|value| !value.trim().is_empty())
            .unwrap_or(&persisted.provider)
            .trim()
            .to_ascii_lowercase();
        let model = input
            .get("model")
            .and_then(Value::as_str)
            .filter(|value| !value.trim().is_empty())
            .unwrap_or(&persisted.model);
        if provider_id != "mock" {
            if let Some(secret) = secret_store
                .read(&provider_id)
                .map_err(|error| error.to_string())?
            {
                commands.push(
                    configure_provider_command(
                        &provider_id,
                        &secret,
                        serde_json::json!({
                            "model": model,
                            "tls_verify": persisted.tls_verify,
                            "ca_bundle_path": persisted.ca_bundle_path,
                        }),
                    )
                    .map_err(str::to_string)?,
                );
            }
        }
    }
    let enabled = persisted
        .enabled_plugins
        .iter()
        .any(|configured| configured == plugin_id);
    commands.push(configure_plugin_command(plugin_id, enabled).map_err(str::to_string)?);
    commands.push(command);
    Ok(commands)
}

fn build_configured_optimize_sequence<B, H>(
    config_store: &ConfigStore,
    secret_store: &SecretStore<B>,
    history_key_store: &HistoryKeyStore<H>,
    history_path: &Path,
    command: ValidatedCommand,
) -> Result<Option<Vec<ValidatedCommand>>, String>
where
    B: CredentialBackend,
    H: CredentialBackend,
{
    let persisted = config_store.load().map_err(|error| error.to_string())?;
    let provider_id = command
        .payload
        .get("provider")
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty())
        .unwrap_or(&persisted.provider)
        .trim()
        .to_ascii_lowercase();
    let mut commands = Vec::with_capacity(7);
    if provider_id != "mock" {
        let secret = secret_store
            .read(&provider_id)
            .map_err(|error| error.to_string())?;
        let Some(secret) = secret else {
            return Ok(None);
        };
        let model = command
            .payload
            .get("model")
            .and_then(Value::as_str)
            .filter(|value| !value.trim().is_empty())
            .unwrap_or(&persisted.model);
        commands.push(
            configure_provider_command(
                &provider_id,
                &secret,
                serde_json::json!({
                    "model": model,
                    "tls_verify": persisted.tls_verify,
                    "ca_bundle_path": persisted.ca_bundle_path,
                }),
            )
            .map_err(str::to_string)?,
        );
    }
    for plugin_id in ["translator", "markdown-preview", "batch-runner", "semantic-detector"] {
        let enabled = persisted
            .enabled_plugins
            .iter()
            .any(|configured| configured == plugin_id);
        commands.push(configure_plugin_command(plugin_id, enabled).map_err(str::to_string)?);
    }
    commands.extend(build_history_config_sequence(
        &persisted,
        history_key_store,
        history_path,
        true,
    )?);
    commands.push(command);
    Ok(Some(commands))
}

fn build_history_config_sequence<H>(
    persisted: &AppConfig,
    history_key_store: &HistoryKeyStore<H>,
    history_path: &Path,
    allow_backend_failure: bool,
) -> Result<Vec<ValidatedCommand>, String>
where
    H: CredentialBackend,
{
    let (history_keys, key_status) = match history_key_store.keyring() {
        Ok(value) => value,
        Err(_error) if allow_backend_failure => (
            std::collections::BTreeMap::new(),
            crate::history_key_store::HistoryKeyStatus {
                configured: false,
                active_version: None,
                pending_version: None,
                rotation_pending: false,
            },
        ),
        Err(error) => return Err(error.to_string()),
    };
    Ok(vec![
        configure_history_path_command(history_path).map_err(str::to_string)?,
        configure_history_keyring_command(
            history_keys,
            key_status.active_version,
            key_status.pending_version,
        )
        .map_err(str::to_string)?,
        configure_history_policy_command(
            persisted.history_enabled,
            persisted.privacy_mode,
            &persisted.history_redaction,
        )
        .map_err(str::to_string)?,
    ])
}

pub(crate) fn history_database_path(app_data_dir: &Path) -> PathBuf {
    app_data_dir.join("history").join("history.sqlite3")
}

fn with_prepared_history_transition<B, T>(
    previous: &AppConfig,
    next: &AppConfig,
    history_key_store: &HistoryKeyStore<B>,
    persist: impl FnOnce() -> Result<T, String>,
) -> Result<T, String>
where
    B: CredentialBackend,
{
    if !previous.history_enabled && next.history_enabled {
        history_key_store
            .ensure_active()
            .map_err(|error| error.to_string())?;
    }
    persist()
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;
    use std::path::PathBuf;
    use std::sync::{Arc, Mutex};

    use serde_json::json;

    use crate::config_store::{AppConfig, ConfigStore};
    use crate::history_key_store::{HistoryKeyStore, HISTORY_KEY_STORE_ERROR_MESSAGE};
    use crate::runtime_commands::{CommandKind, ValidatedCommand};
    use crate::secret_store::{CredentialBackend, SecretStore};
    use crate::sidecar::{EventEmitter, RuntimeController};

    #[test]
    fn window_size_presets_are_fixed_and_bounded() {
        assert_eq!(super::window_size_preset("compact"), Some((680.0, 480.0)));
        assert_eq!(super::window_size_preset("default"), Some((760.0, 540.0)));
        assert_eq!(super::window_size_preset("wide"), Some((900.0, 640.0)));
        assert_eq!(super::window_size_preset("1920x1080"), None);
    }

    #[test]
    fn main_only_runtime_commands_reject_other_window_labels() {
        assert!(super::require_main_window("main").is_ok());
        assert!(super::require_main_window("history").is_err());
        assert!(super::require_main_window("forged").is_err());
    }

    struct EmptyCredentialBackend;

    impl CredentialBackend for EmptyCredentialBackend {
        fn get(&self, _service: &str, _account: &str) -> Result<Option<String>, ()> {
            Ok(None)
        }

        fn set(&self, _service: &str, _account: &str, _secret: &str) -> Result<(), ()> {
            Ok(())
        }

        fn delete(&self, _service: &str, _account: &str) -> Result<(), ()> {
            Ok(())
        }
    }

    struct FailingCredentialBackend;

    impl CredentialBackend for FailingCredentialBackend {
        fn get(&self, _service: &str, _account: &str) -> Result<Option<String>, ()> {
            Err(())
        }

        fn set(&self, _service: &str, _account: &str, _secret: &str) -> Result<(), ()> {
            Err(())
        }

        fn delete(&self, _service: &str, _account: &str) -> Result<(), ()> {
            Err(())
        }
    }

    #[derive(Clone, Default)]
    struct MemoryCredentialBackend(Arc<Mutex<HashMap<(String, String), String>>>);

    impl CredentialBackend for MemoryCredentialBackend {
        fn get(&self, service: &str, account: &str) -> Result<Option<String>, ()> {
            Ok(self
                .0
                .lock()
                .unwrap()
                .get(&(service.to_string(), account.to_string()))
                .cloned())
        }

        fn set(&self, service: &str, account: &str, secret: &str) -> Result<(), ()> {
            self.0.lock().unwrap().insert(
                (service.to_string(), account.to_string()),
                secret.to_string(),
            );
            Ok(())
        }

        fn delete(&self, service: &str, account: &str) -> Result<(), ()> {
            self.0
                .lock()
                .unwrap()
                .remove(&(service.to_string(), account.to_string()));
            Ok(())
        }
    }

    #[derive(Clone, Default)]
    struct PromoteFailingCredentialBackend {
        values: Arc<Mutex<HashMap<(String, String), String>>>,
        events: Arc<Mutex<Vec<&'static str>>>,
        failed: Arc<Mutex<bool>>,
    }

    impl CredentialBackend for PromoteFailingCredentialBackend {
        fn get(&self, service: &str, account: &str) -> Result<Option<String>, ()> {
            Ok(self
                .values
                .lock()
                .unwrap()
                .get(&(service.to_string(), account.to_string()))
                .cloned())
        }

        fn set(&self, service: &str, account: &str, secret: &str) -> Result<(), ()> {
            if account == "state" {
                let state: serde_json::Value = serde_json::from_str(secret).unwrap();
                if state["active_version"] == 2
                    && state["pending_version"].is_null()
                    && !*self.failed.lock().unwrap()
                {
                    *self.failed.lock().unwrap() = true;
                    self.events
                        .lock()
                        .unwrap()
                        .push("credential-promote-failed");
                    return Err(());
                }
                if *self.failed.lock().unwrap() && state["active_version"] == 1 {
                    self.events.lock().unwrap().push("credential-rollback");
                }
            }
            self.values.lock().unwrap().insert(
                (service.to_string(), account.to_string()),
                secret.to_string(),
            );
            Ok(())
        }

        fn delete(&self, service: &str, account: &str) -> Result<(), ()> {
            self.values
                .lock()
                .unwrap()
                .remove(&(service.to_string(), account.to_string()));
            Ok(())
        }
    }

    struct RecordingEmitter(Arc<Mutex<Vec<serde_json::Value>>>);

    impl EventEmitter for RecordingEmitter {
        fn emit(&self, _event_name: &str, payload: serde_json::Value) {
            self.0.lock().unwrap().push(payload);
        }
    }

    #[test]
    fn runtime_capability_is_enabled_when_the_development_runtime_layout_resolves() {
        assert!(super::runtime_available_value());
    }

    #[test]
    fn missing_provider_secret_emits_settings_error_without_starting_runtime() {
        let directory =
            std::env::temp_dir().join(format!("reflex-next-command-config-{}", std::process::id()));
        let _ = std::fs::remove_dir_all(&directory);
        let config_store = ConfigStore::new(PathBuf::from(&directory));
        let secret_store = SecretStore::new(EmptyCredentialBackend);
        let events = Arc::new(Mutex::new(Vec::new()));
        let runtime = RuntimeController::new(Arc::new(RecordingEmitter(events.clone())));
        let command = ValidatedCommand {
            request_id: "req-missing".to_string(),
            kind: CommandKind::Optimize,
            payload: json!({
                "text": "待优化内容",
                "provider": "minimax",
                "model": "MiniMax-M2.7-highspeed"
            }),
        };

        let history_key_store = HistoryKeyStore::new(EmptyCredentialBackend);
        let history_path = super::history_database_path(&directory);
        super::send_configured_optimize(
            &runtime,
            &config_store,
            &secret_store,
            &history_key_store,
            &history_path,
            command,
        )
        .unwrap();

        let emitted = events.lock().unwrap();
        assert_eq!(emitted.len(), 1);
        assert_eq!(emitted[0]["request_id"], "req-missing");
        assert_eq!(emitted[0]["event"]["data"]["code"], "provider_unconfigured");
        assert_eq!(emitted[0]["event"]["data"]["action"], "settings");
        let _ = std::fs::remove_dir_all(directory);
    }

    #[test]
    fn configured_optimize_sequence_injects_private_keys_and_policy_before_optimize() {
        let directory = std::env::temp_dir().join(format!(
            "reflex-next-command-sequence-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&directory);
        let config_store = ConfigStore::new(PathBuf::from(&directory));
        let mut config = AppConfig::default();
        config.history_enabled = true;
        config.privacy_mode = true;
        config.history_redaction = "none".to_string();
        config.enabled_plugins = vec!["translator".to_string(), "../unsafe".to_string()];
        config_store.save(&config).unwrap();

        let backend = MemoryCredentialBackend::default();
        let secret_store = SecretStore::new(backend.clone());
        secret_store
            .save("minimax", "history-fixture-provider-key")
            .unwrap();
        let history_store = HistoryKeyStore::new(backend);
        history_store.ensure_active().unwrap();
        let command = ValidatedCommand {
            request_id: "req-sequence".to_string(),
            kind: CommandKind::Optimize,
            payload: json!({
                "text": "待优化内容",
                "provider": "minimax",
                "model": "MiniMax-M2.7-highspeed"
            }),
        };

        let sequence = super::build_configured_optimize_sequence(
            &config_store,
            &secret_store,
            &history_store,
            &super::history_database_path(&directory),
            command,
        )
        .unwrap()
        .unwrap();

        assert_eq!(
            sequence
                .iter()
                .map(|command| command.kind)
                .collect::<Vec<_>>(),
            [
                CommandKind::ConfigureProvider,
                CommandKind::ConfigurePlugin,
                CommandKind::ConfigurePlugin,
                CommandKind::ConfigurePlugin,
                CommandKind::ConfigurePlugin,
                CommandKind::ConfigureHistoryPath,
                CommandKind::ConfigureHistoryKeys,
                CommandKind::ConfigureHistoryPolicy,
                CommandKind::Optimize,
            ]
        );
        assert_eq!(
            sequence[1].payload,
            json!({
                "plugin_id": "translator",
                "enabled": true
            })
        );
        assert_eq!(
            sequence[2].payload,
            json!({
                "plugin_id": "markdown-preview",
                "enabled": false
            })
        );
        assert_eq!(
            sequence[3].payload,
            json!({
                "plugin_id": "batch-runner",
                "enabled": false
            })
        );
        assert_eq!(
            sequence[4].payload,
            json!({
                "plugin_id": "semantic-detector",
                "enabled": false
            })
        );
        assert_eq!(sequence[5].kind, CommandKind::ConfigureHistoryPath);
        assert_eq!(
            sequence[5].payload["database_path"],
            super::history_database_path(&directory)
                .to_string_lossy()
                .as_ref()
        );
        assert!(sequence[6].payload["keys"]["v1"].is_string());
        assert_eq!(sequence[7].payload["history_enabled"], true);
        assert_eq!(sequence[7].payload["privacy_mode"], true);
        assert_eq!(sequence[7].payload["history_redaction"], "none");
        assert!(!sequence.iter().any(|command| {
            command
                .payload
                .get("plugin_id")
                .and_then(|value| value.as_str())
                == Some("../unsafe")
        }));
        assert!(!format!("{sequence:?}").contains("history-fixture-provider-key"));
        let _ = std::fs::remove_dir_all(directory);
    }

    #[test]
    fn fresh_history_calls_sync_private_path_keys_and_policy_before_the_public_call() {
        let directory = std::env::temp_dir().join(format!(
            "reflex-next-command-history-cold-start-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&directory);
        let config_store = ConfigStore::new(PathBuf::from(&directory));
        let mut config = AppConfig::default();
        config.privacy_mode = true;
        config_store.save(&config).unwrap();
        let backend = MemoryCredentialBackend::default();
        let history_store = HistoryKeyStore::new(backend);
        history_store.ensure_active().unwrap();
        let history_path = super::history_database_path(&directory);

        for operation in ["list", "detail", "rate"] {
            let command = ValidatedCommand {
                request_id: format!("history-cold-{operation}"),
                kind: CommandKind::PluginCall,
                payload: json!({
                    "plugin_id": "history-sqlite",
                    "operation": operation,
                    "input": {}
                }),
            };

            let sequence = super::build_configured_plugin_call_sequence(
                &config_store,
                &SecretStore::new(EmptyCredentialBackend),
                &history_store,
                &history_path,
                command,
            )
            .unwrap();

            assert_eq!(
                sequence
                    .iter()
                    .map(|command| command.kind)
                    .collect::<Vec<_>>(),
                [
                    CommandKind::ConfigureHistoryPath,
                    CommandKind::ConfigureHistoryKeys,
                    CommandKind::ConfigureHistoryPolicy,
                    CommandKind::PluginCall,
                ]
            );
            assert_eq!(
                sequence[0].payload["database_path"],
                history_path.to_string_lossy().as_ref()
            );
            assert!(sequence[1].payload["keys"]["v1"].is_string());
            assert_eq!(sequence[2].payload["history_enabled"], false);
            assert_eq!(sequence[2].payload["privacy_mode"], true);
            assert_eq!(sequence[3].payload["operation"], operation);
        }
        let _ = std::fs::remove_dir_all(directory);
    }

    #[test]
    fn history_call_backend_failure_is_safe_and_produces_no_public_sequence() {
        let directory = std::env::temp_dir().join(format!(
            "reflex-next-command-history-call-failure-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&directory);
        let config_store = ConfigStore::new(PathBuf::from(&directory));
        let history_store = HistoryKeyStore::new(FailingCredentialBackend);
        let command = ValidatedCommand {
            request_id: "history-call-failure".to_string(),
            kind: CommandKind::PluginCall,
            payload: json!({
                "plugin_id": "history-sqlite",
                "operation": "list",
                "input": {}
            }),
        };

        let error = super::build_configured_plugin_call_sequence(
            &config_store,
            &SecretStore::new(EmptyCredentialBackend),
            &history_store,
            &super::history_database_path(&directory),
            command,
        )
        .unwrap_err();

        assert_eq!(error, HISTORY_KEY_STORE_ERROR_MESSAGE);
        let _ = std::fs::remove_dir_all(directory);
    }

    #[test]
    fn ordinary_plugin_calls_sync_enablement_without_reading_history_keys() {
        let directory = std::env::temp_dir().join(format!(
            "reflex-next-command-ordinary-plugin-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&directory);
        let config_store = ConfigStore::new(PathBuf::from(&directory));
        let history_store = HistoryKeyStore::new(FailingCredentialBackend);
        let secret_store = SecretStore::new(EmptyCredentialBackend);

        for plugin_id in ["translator", "markdown-preview"] {
            let command = ValidatedCommand {
                request_id: format!("ordinary-{plugin_id}"),
                kind: CommandKind::PluginCall,
                payload: json!({
                    "plugin_id": plugin_id,
                    "operation": if plugin_id == "translator" { "translate" } else { "render" },
                    "input": {}
                }),
            };
            let sequence = super::build_configured_plugin_call_sequence(
                &config_store,
                &secret_store,
                &history_store,
                &super::history_database_path(&directory),
                command.clone(),
            )
            .unwrap();

            assert_eq!(
                sequence.iter().map(|item| item.kind).collect::<Vec<_>>(),
                [CommandKind::ConfigurePlugin, CommandKind::PluginCall]
            );
            assert_eq!(sequence[0].payload["plugin_id"], plugin_id);
            assert_eq!(sequence[0].payload["enabled"], true);
            assert_eq!(sequence[1], command);
        }
        assert!(!directory.exists());
    }

    #[test]
    fn translator_call_configures_the_selected_provider_before_enablement_and_call() {
        let directory = std::env::temp_dir().join(format!(
            "reflex-next-command-translator-provider-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&directory);
        let config_store = ConfigStore::new(PathBuf::from(&directory));
        let backend = MemoryCredentialBackend::default();
        let secret_store = SecretStore::new(backend.clone());
        secret_store
            .save("minimax", "translation-fixture-provider-key")
            .unwrap();
        let history_store = HistoryKeyStore::new(FailingCredentialBackend);
        let command = ValidatedCommand {
            request_id: "translation-call".to_string(),
            kind: CommandKind::PluginCall,
            payload: json!({
                "plugin_id": "translator",
                "operation": "translate",
                "input": {
                    "text": "source",
                    "target": "auto",
                    "provider": "minimax",
                    "model": "MiniMax-M2.7-highspeed"
                }
            }),
        };

        let sequence = super::build_configured_plugin_call_sequence(
            &config_store,
            &secret_store,
            &history_store,
            &super::history_database_path(&directory),
            command.clone(),
        )
        .unwrap();

        assert_eq!(
            sequence.iter().map(|item| item.kind).collect::<Vec<_>>(),
            [
                CommandKind::ConfigureProvider,
                CommandKind::ConfigurePlugin,
                CommandKind::PluginCall
            ]
        );
        assert_eq!(sequence[0].payload["provider_id"], "minimax");
        assert_eq!(
            sequence[0].payload["config"]["model"],
            "MiniMax-M2.7-highspeed"
        );
        assert_eq!(sequence[1].payload["plugin_id"], "translator");
        assert_eq!(sequence[1].payload["enabled"], true);
        assert_eq!(sequence[2], command);
        assert!(!format!("{sequence:?}").contains("translation-fixture-provider-key"));
        let _ = std::fs::remove_dir_all(directory);
    }

    #[test]
    fn app_data_history_path_is_fixed_and_does_not_create_storage() {
        let app_data = std::env::temp_dir().join(format!(
            "reflex-next-app-data-history-{}",
            std::process::id()
        ));

        let path = super::history_database_path(&app_data);

        assert_eq!(path, app_data.join("history").join("history.sqlite3"));
        assert!(!app_data.exists());
    }

    #[test]
    fn export_cancelled_after_result_preserves_target_and_removes_temporary_file() {
        let root = std::env::temp_dir().join(format!(
            "reflex-next-command-export-result-cancel-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&root);
        std::fs::create_dir_all(&root).unwrap();
        let target = root.join("history.json");
        std::fs::write(&target, b"old").unwrap();
        let mut writer = crate::history_export::AtomicExportWriter::new(&target).unwrap();
        writer.write_chunk(b"new private body").unwrap();
        let control = super::HistoryOperationControl::new();
        control.begin().unwrap();
        control.cancel();

        let committed = super::commit_history_export(writer, &control).unwrap();

        assert!(!committed);
        assert_eq!(std::fs::read(&target).unwrap(), b"old");
        assert_eq!(std::fs::read_dir(&root).unwrap().count(), 1);
        let _ = std::fs::remove_dir_all(root);
    }

    #[test]
    fn export_commit_and_cancel_share_one_linearized_critical_section() {
        let control = Arc::new(super::HistoryOperationControl::new());
        control.begin().unwrap();
        let commit_entered = Arc::new(std::sync::Barrier::new(2));
        let release_commit = Arc::new(std::sync::Barrier::new(2));
        let commit_control = control.clone();
        let commit_entered_for_worker = commit_entered.clone();
        let release_commit_for_worker = release_commit.clone();
        let commit = std::thread::spawn(move || {
            commit_control.with_commit(|| {
                commit_entered_for_worker.wait();
                release_commit_for_worker.wait();
                Ok(())
            })
        });
        commit_entered.wait();
        let cancel_returned = Arc::new(std::sync::atomic::AtomicBool::new(false));
        let cancel_control = control.clone();
        let cancel_returned_for_worker = cancel_returned.clone();
        let cancel = std::thread::spawn(move || {
            cancel_control.cancel();
            cancel_returned_for_worker.store(true, std::sync::atomic::Ordering::Release);
        });

        std::thread::sleep(std::time::Duration::from_millis(25));
        assert!(!cancel_returned.load(std::sync::atomic::Ordering::Acquire));
        release_commit.wait();

        assert!(commit.join().unwrap().unwrap().is_some());
        cancel.join().unwrap();
        assert!(cancel_returned.load(std::sync::atomic::Ordering::Acquire));
        control.finish();
    }

    #[test]
    fn credential_promote_failure_rolls_back_python_before_pending_key_state() {
        let backend = PromoteFailingCredentialBackend::default();
        let events = backend.events.clone();
        let store = HistoryKeyStore::new(backend);
        store.ensure_active().unwrap();
        store.begin_rotation().unwrap();
        events.lock().unwrap().clear();

        let result = super::promote_history_rotation_or_rollback(&store, || {
            events.lock().unwrap().push("python-rollback");
            Ok(())
        });

        assert!(result.is_err());
        assert_eq!(store.status().unwrap().active_version, Some(1));
        assert_eq!(store.status().unwrap().pending_version, None);
        assert_eq!(
            *events.lock().unwrap(),
            [
                "credential-promote-failed",
                "python-rollback",
                "credential-rollback"
            ]
        );
    }

    #[test]
    fn credential_promote_failure_preserves_pending_key_when_python_rollback_fails() {
        let backend = PromoteFailingCredentialBackend::default();
        let events = backend.events.clone();
        let store = HistoryKeyStore::new(backend);
        store.ensure_active().unwrap();
        store.begin_rotation().unwrap();
        events.lock().unwrap().clear();

        let result = super::promote_history_rotation_or_rollback(&store, || {
            events.lock().unwrap().push("python-rollback-failed");
            Err(super::HISTORY_OPERATION_ERROR_MESSAGE.to_string())
        });

        assert!(result.is_err());
        assert_eq!(store.status().unwrap().active_version, Some(1));
        assert_eq!(store.status().unwrap().pending_version, Some(2));
        assert_eq!(
            *events.lock().unwrap(),
            ["credential-promote-failed", "python-rollback-failed"]
        );
    }

    #[test]
    fn promoted_rotation_is_resumed_before_allocating_another_pending_key() {
        let store = HistoryKeyStore::new(MemoryCredentialBackend::default());
        store.ensure_active().unwrap();
        store.begin_rotation().unwrap();
        store.promote().unwrap();
        let resumed_target = Arc::new(Mutex::new(None));
        let recorded_target = resumed_target.clone();

        let resumed = super::resume_promoted_rotation(&store, move |target| {
            *recorded_target.lock().unwrap() = Some(target);
            Ok(true)
        })
        .unwrap();

        assert!(resumed);
        assert_eq!(*resumed_target.lock().unwrap(), Some(2));
        assert_eq!(store.status().unwrap().active_version, Some(2));
        assert_eq!(store.status().unwrap().pending_version, None);
    }

    #[test]
    fn unconfirmed_rotation_cancellation_preserves_pending_key_state() {
        let store = HistoryKeyStore::new(MemoryCredentialBackend::default());
        store.ensure_active().unwrap();
        store.begin_rotation().unwrap();

        let resolved =
            super::resolve_rotation_prepare(Ok(super::HistoryAdminOutcome::Cancelled)).unwrap();

        assert!(resolved.is_none());
        assert_eq!(store.status().unwrap().active_version, Some(1));
        assert_eq!(store.status().unwrap().pending_version, Some(2));
    }

    #[test]
    fn disabled_history_preserves_existing_keys_for_read_only_management() {
        let directory = std::env::temp_dir().join(format!(
            "reflex-next-command-disabled-history-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&directory);
        let config_store = ConfigStore::new(PathBuf::from(&directory));
        let backend = MemoryCredentialBackend::default();
        let secret_store = SecretStore::new(backend.clone());
        secret_store
            .save("minimax", "history-fixture-provider-key")
            .unwrap();
        let history_store = HistoryKeyStore::new(backend);
        history_store.ensure_active().unwrap();
        let command = ValidatedCommand {
            request_id: "req-disabled-history".to_string(),
            kind: CommandKind::Optimize,
            payload: json!({ "text": "待优化内容", "provider": "minimax" }),
        };

        let sequence = super::build_configured_optimize_sequence(
            &config_store,
            &secret_store,
            &history_store,
            &super::history_database_path(&directory),
            command,
        )
        .unwrap()
        .unwrap();

        assert_eq!(sequence[6].kind, CommandKind::ConfigureHistoryKeys);
        assert!(sequence[6].payload["keys"]["v1"].is_string());
        assert_eq!(sequence[7].payload["history_enabled"], false);
        assert!(history_store.status().unwrap().configured);
        let _ = std::fs::remove_dir_all(directory);
    }

    #[test]
    fn disabled_history_backend_failure_falls_back_to_empty_keys_and_keeps_optimize() {
        let directory = std::env::temp_dir().join(format!(
            "reflex-next-command-disabled-history-failure-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&directory);
        let config_store = ConfigStore::new(PathBuf::from(&directory));
        let provider_backend = MemoryCredentialBackend::default();
        let secret_store = SecretStore::new(provider_backend.clone());
        secret_store
            .save("minimax", "history-fixture-provider-key")
            .unwrap();
        let history_store = HistoryKeyStore::new(FailingCredentialBackend);
        let command = ValidatedCommand {
            request_id: "req-disabled-history-failure".to_string(),
            kind: CommandKind::Optimize,
            payload: json!({ "text": "待优化内容", "provider": "minimax" }),
        };

        let sequence = super::build_configured_optimize_sequence(
            &config_store,
            &secret_store,
            &history_store,
            &super::history_database_path(&directory),
            command,
        )
        .unwrap()
        .unwrap();

        assert_eq!(sequence[6].payload["keys"], json!({}));
        assert_eq!(sequence[7].payload["history_enabled"], false);
        assert_eq!(sequence.last().unwrap().kind, CommandKind::Optimize);
        let _ = std::fs::remove_dir_all(directory);
    }

    #[test]
    fn enabled_history_backend_failure_falls_back_to_empty_keys_and_keeps_optimize() {
        let directory = std::env::temp_dir().join(format!(
            "reflex-next-command-enabled-history-failure-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&directory);
        let config_store = ConfigStore::new(PathBuf::from(&directory));
        let mut config = AppConfig::default();
        config.history_enabled = true;
        config_store.save(&config).unwrap();
        let provider_backend = MemoryCredentialBackend::default();
        let secret_store = SecretStore::new(provider_backend);
        secret_store
            .save("minimax", "history-fixture-provider-key")
            .unwrap();
        let history_store = HistoryKeyStore::new(FailingCredentialBackend);
        let command = ValidatedCommand {
            request_id: "req-enabled-history-failure".to_string(),
            kind: CommandKind::Optimize,
            payload: json!({ "text": "待优化内容", "provider": "minimax" }),
        };

        let sequence = super::build_configured_optimize_sequence(
            &config_store,
            &secret_store,
            &history_store,
            &super::history_database_path(&directory),
            command,
        )
        .unwrap()
        .unwrap();

        assert_eq!(sequence[0].kind, CommandKind::ConfigureProvider);
        assert_eq!(sequence[5].kind, CommandKind::ConfigureHistoryPath);
        assert_eq!(sequence[6].kind, CommandKind::ConfigureHistoryKeys);
        assert_eq!(sequence[6].payload["keys"], json!({}));
        assert_eq!(sequence[7].kind, CommandKind::ConfigureHistoryPolicy);
        assert_eq!(sequence[7].payload["history_enabled"], true);
        assert_eq!(sequence.last().unwrap().kind, CommandKind::Optimize);
        let _ = std::fs::remove_dir_all(directory);
    }

    #[test]
    fn history_enable_failure_prevents_the_persist_callback() {
        let old = AppConfig::default();
        let mut new = AppConfig::default();
        new.history_enabled = true;
        let store = HistoryKeyStore::new(FailingCredentialBackend);
        let persisted = Arc::new(Mutex::new(false));

        let result = super::with_prepared_history_transition(&old, &new, &store, {
            let persisted = persisted.clone();
            move || {
                *persisted.lock().unwrap() = true;
                Ok(())
            }
        });

        assert!(result.is_err());
        assert!(!*persisted.lock().unwrap());
    }

    #[test]
    fn reuse_payload_binds_the_detail_id_and_selects_only_the_requested_plain_text() {
        let input = super::HistoryReuseIntent {
            kind: "input".to_string(),
            history_id: "history-1".to_string(),
        };
        let detail = json!({ "record": {
            "id": "history-1",
            "input": "plain input",
            "output": "plain output",
            "scene": "email",
            "style": "detailed",
            "mode": "prompt",
            "provider": "minimax",
            "model": "MiniMax-M2.7-highspeed",
            "elapsed_ms": 321,
            "rating": 4,
            "script": "ignored"
        } });
        assert_eq!(
            super::history_reuse_payload(&input, &detail, 1).unwrap(),
            json!({ "version": 1, "sequence": 1, "history_id": "history-1", "kind": "input", "text": "plain input" })
        );
        let result = super::HistoryReuseIntent {
            kind: "result".to_string(),
            history_id: "history-1".to_string(),
        };
        assert_eq!(
            super::history_reuse_payload(&result, &detail, 2).unwrap(),
            json!({
                "version": 1,
                "sequence": 2,
            "history_id": "history-1",
            "kind": "result",
            "text": "plain output",
            "source_text": "plain input",
            "scene": "email",
                "style": "detailed",
                "mode": "prompt",
                "provider": "minimax",
                "model": "MiniMax-M2.7-highspeed",
                "elapsed_ms": 321,
                "rating": 4
            })
        );
        let wrong = super::HistoryReuseIntent {
            kind: "result".to_string(),
            history_id: "other".to_string(),
        };
        assert!(super::history_reuse_payload(&wrong, &detail, 2).is_err());
        let forged = super::HistoryReuseIntent {
            kind: "script".to_string(),
            history_id: "history-1".to_string(),
        };
        assert!(super::history_reuse_payload(&forged, &detail, 3).is_err());
    }
}
