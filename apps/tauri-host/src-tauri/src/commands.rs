use std::sync::Arc;

use serde_json::Value;
use tauri::{AppHandle, Emitter, State};

use crate::config_store::{AppConfig, ConfigStore};
use crate::runtime_commands::{
    configure_provider_command, validate_command, CommandKind, ValidatedCommand,
};
use crate::secret_store::{CredentialBackend, SecretStatus, SecretStore};
use crate::sidecar::{EventEmitter, RuntimeController};

const CORE_EVENT_NAME: &str = "reflex://core-event";

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
}

struct TauriEventEmitter {
    app: AppHandle,
}

impl EventEmitter for TauriEventEmitter {
    fn emit(&self, payload: Value) {
        let _ = self.app.emit(CORE_EVENT_NAME, payload);
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
pub async fn runtime_available() -> bool {
    runtime_available_value()
}

#[tauri::command]
pub async fn load_app_config(state: State<'_, ConfigStore>) -> Result<AppConfig, String> {
    state.load().map_err(|error| error.to_string())
}

#[tauri::command]
pub async fn save_app_config(
    state: State<'_, ConfigStore>,
    config: AppConfig,
) -> Result<AppConfig, String> {
    state.save(&config).map_err(|error| error.to_string())
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
    let status = state
        .save(&provider_id, &secret)
        .map_err(|error| error.to_string())?;
    runtime_state.runtime.shutdown();
    Ok(status)
}

#[tauri::command]
pub async fn delete_provider_secret(
    state: State<'_, SecretStore>,
    runtime_state: State<'_, TauriRuntimeState>,
    provider_id: String,
) -> Result<SecretStatus, String> {
    let status = state
        .delete(&provider_id)
        .map_err(|error| error.to_string())?;
    runtime_state.runtime.shutdown();
    Ok(status)
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
        return runtime.send(command).map_err(str::to_string);
    }

    let secret = secret_store
        .read(&provider_id)
        .map_err(|error| error.to_string())?;
    let Some(secret) = secret else {
        runtime.emit_provider_unconfigured(&command.request_id);
        return Ok(());
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
        .send_sequence(vec![configure, command])
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
        fn emit(&self, payload: serde_json::Value) {
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
