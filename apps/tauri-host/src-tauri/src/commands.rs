use std::sync::Arc;

use serde_json::Value;
use tauri::{AppHandle, Emitter, State};

use crate::config_store::{AppConfig, ConfigStore};
use crate::desktop::{DesktopState, DesktopStatus};
use crate::runtime_commands::{
    configure_provider_command, validate_command, CommandKind, ValidatedCommand,
};
use crate::secret_store::{CredentialBackend, SecretStatus, SecretStore};
use crate::sidecar::{EventEmitter, RuntimeController};

pub struct TauriRuntimeState {
    runtime: RuntimeController,
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
        let _ = self.app.emit(event_name, payload);
    }
}

fn runtime_available_value() -> bool {
    crate::sidecar::resolve_runtime_paths().is_ok()
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
    config: AppConfig,
) -> Result<AppConfig, String> {
    let normalized = AppConfig::from_value(
        serde_json::to_value(config).map_err(|_| "配置存储暂不可用。".to_string())?,
    )
    .map_err(|error| error.to_string())?;
    let requested_hotkey = normalized.hotkey.clone();
    crate::desktop::replace_hotkey_and_persist(&app, &desktop_state, &requested_hotkey, || {
        state.save(&normalized).map_err(|error| error.to_string())
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
    state: State<'_, TauriRuntimeState>,
    config_store: State<'_, ConfigStore>,
    secret_store: State<'_, SecretStore>,
    command: Value,
) -> Result<(), String> {
    let command = validate_command(command, CommandKind::Optimize).map_err(str::to_string)?;
    send_configured_optimize(&state.runtime, &config_store, &secret_store, command)
}

#[tauri::command]
pub async fn runtime_cancel(
    state: State<'_, TauriRuntimeState>,
    command: Value,
) -> Result<(), String> {
    forward_runtime_command(&state.runtime, command, CommandKind::Cancel)
}

#[tauri::command]
pub async fn runtime_list_plugins(
    state: State<'_, TauriRuntimeState>,
    command: Value,
) -> Result<(), String> {
    let command = validate_command(command, CommandKind::ListPlugins).map_err(str::to_string)?;
    state.runtime().send(command).map_err(str::to_string)
}

#[tauri::command]
pub async fn runtime_plugin_call(
    window: tauri::WebviewWindow,
    state: State<'_, TauriRuntimeState>,
    command: Value,
) -> Result<(), String> {
    let command = crate::plugin_commands::validate_authorized_plugin_call(window.label(), command)
        .map_err(str::to_string)?;
    state.runtime().send(command).map_err(str::to_string)
}

#[tauri::command]
pub async fn runtime_plugin_cancel(
    state: State<'_, TauriRuntimeState>,
    command: Value,
) -> Result<(), String> {
    forward_runtime_command(state.runtime(), command, CommandKind::Cancel)
}

fn forward_runtime_command(
    runtime: &RuntimeController,
    command: Value,
    expected_kind: CommandKind,
) -> Result<(), String> {
    let command = validate_command(command, expected_kind).map_err(str::to_string)?;
    runtime.send(command).map_err(str::to_string)
}

fn send_configured_optimize<B>(
    runtime: &RuntimeController,
    config_store: &ConfigStore,
    secret_store: &SecretStore<B>,
    command: ValidatedCommand,
) -> Result<(), String>
where
    B: CredentialBackend,
{
    runtime.with_lifecycle(|runtime, _generation| {
        send_configured_optimize_locked(runtime, config_store, secret_store, command)
    })
}

fn send_configured_optimize_locked<B>(
    runtime: &RuntimeController,
    config_store: &ConfigStore,
    secret_store: &SecretStore<B>,
    command: ValidatedCommand,
) -> Result<(), String>
where
    B: CredentialBackend,
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
    if provider_id == "mock" {
        return runtime.send_unlocked(command).map_err(str::to_string);
    }

    let secret = secret_store
        .read(&provider_id)
        .map_err(|error| error.to_string())?;
    let Some(secret) = secret else {
        return runtime
            .emit_provider_unconfigured_unlocked(&command.request_id)
            .map_err(str::to_string);
    };
    let model = command
        .payload
        .get("model")
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty())
        .unwrap_or(&persisted.model);
    let configure = configure_provider_command(
        &provider_id,
        &secret,
        serde_json::json!({
            "model": model,
            "tls_verify": persisted.tls_verify,
            "ca_bundle_path": persisted.ca_bundle_path,
        }),
    )
    .map_err(str::to_string)?;
    runtime
        .send_sequence_unlocked(vec![configure, command])
        .map_err(str::to_string)
}

#[cfg(test)]
mod tests {
    use std::path::PathBuf;
    use std::sync::{Arc, Mutex};

    use serde_json::json;

    use crate::config_store::ConfigStore;
    use crate::runtime_commands::{CommandKind, ValidatedCommand};
    use crate::secret_store::{CredentialBackend, SecretStore};
    use crate::sidecar::{EventEmitter, RuntimeController};

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

        super::send_configured_optimize(&runtime, &config_store, &secret_store, command).unwrap();

        let emitted = events.lock().unwrap();
        assert_eq!(emitted.len(), 1);
        assert_eq!(emitted[0]["request_id"], "req-missing");
        assert_eq!(emitted[0]["event"]["data"]["code"], "provider_unconfigured");
        assert_eq!(emitted[0]["event"]["data"]["action"], "settings");
        let _ = std::fs::remove_dir_all(directory);
    }
}
