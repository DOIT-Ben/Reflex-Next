use std::path::{Path, PathBuf};
use std::sync::Arc;

use serde_json::Value;
use tauri::{AppHandle, Emitter, Manager, State};

use crate::config_store::{AppConfig, ConfigStore};
use crate::desktop::{DesktopState, DesktopStatus};
use crate::history_key_store::HistoryKeyStore;
use crate::runtime_commands::{
    configure_history_keys_command, configure_history_path_command,
    configure_history_policy_command, configure_plugin_command, configure_provider_command,
    validate_command, CommandKind, ValidatedCommand,
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
    state: State<'_, TauriRuntimeState>,
    config_store: State<'_, ConfigStore>,
    secret_store: State<'_, SecretStore>,
    history_key_store: State<'_, HistoryKeyStore>,
    command: Value,
) -> Result<(), String> {
    let command = validate_command(command, CommandKind::Optimize).map_err(str::to_string)?;
    let history_path = app
        .path()
        .app_data_dir()
        .map(|path| history_database_path(&path))
        .map_err(|_| "应用数据目录不可用。".to_string())?;
    send_configured_optimize(
        &state.runtime,
        &config_store,
        &secret_store,
        &history_key_store,
        &history_path,
        command,
    )
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
    app: AppHandle,
    window: tauri::WebviewWindow,
    state: State<'_, TauriRuntimeState>,
    config_store: State<'_, ConfigStore>,
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
        return send_configured_plugin_call(
            state.runtime(),
            &config_store,
            &history_key_store,
            &history_path,
            command,
        );
    }
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
                .send_sequence_unlocked(commands)
                .map_err(str::to_string),
            None => runtime
                .emit_provider_unconfigured_unlocked(&request_id)
                .map_err(str::to_string),
        }
    })
}

fn send_configured_plugin_call<H>(
    runtime: &RuntimeController,
    config_store: &ConfigStore,
    history_key_store: &HistoryKeyStore<H>,
    history_path: &Path,
    command: ValidatedCommand,
) -> Result<(), String>
where
    H: CredentialBackend,
{
    runtime.with_lifecycle(|runtime, _generation| {
        let commands = build_configured_plugin_call_sequence(
            config_store,
            history_key_store,
            history_path,
            command,
        )?;
        runtime
            .send_sequence_unlocked(commands)
            .map_err(str::to_string)
    })
}

fn build_configured_plugin_call_sequence<H>(
    config_store: &ConfigStore,
    history_key_store: &HistoryKeyStore<H>,
    history_path: &Path,
    command: ValidatedCommand,
) -> Result<Vec<ValidatedCommand>, String>
where
    H: CredentialBackend,
{
    if command.payload.get("plugin_id").and_then(Value::as_str) != Some("history-sqlite") {
        return Ok(vec![command]);
    }
    let persisted = config_store.load().map_err(|error| error.to_string())?;
    let mut commands =
        build_history_config_sequence(&persisted, history_key_store, history_path, false)?;
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
    for plugin_id in ["translator", "markdown-preview"] {
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
    let history_keys = match history_key_store.active_keys() {
        Ok(keys) => keys,
        Err(_error) if allow_backend_failure => std::collections::BTreeMap::new(),
        Err(error) => return Err(error.to_string()),
    };
    Ok(vec![
        configure_history_path_command(history_path).map_err(str::to_string)?,
        configure_history_keys_command(history_keys).map_err(str::to_string)?,
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
        assert_eq!(sequence[3].kind, CommandKind::ConfigureHistoryPath);
        assert_eq!(
            sequence[3].payload["database_path"],
            super::history_database_path(&directory)
                .to_string_lossy()
                .as_ref()
        );
        assert!(sequence[4].payload["keys"]["v1"].is_string());
        assert_eq!(sequence[5].payload["history_enabled"], true);
        assert_eq!(sequence[5].payload["privacy_mode"], true);
        assert_eq!(sequence[5].payload["history_redaction"], "none");
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
            &history_store,
            &super::history_database_path(&directory),
            command,
        )
        .unwrap_err();

        assert_eq!(error, HISTORY_KEY_STORE_ERROR_MESSAGE);
        let _ = std::fs::remove_dir_all(directory);
    }

    #[test]
    fn ordinary_plugin_calls_do_not_read_history_keys_or_add_history_configuration() {
        let directory = std::env::temp_dir().join(format!(
            "reflex-next-command-ordinary-plugin-{}",
            std::process::id()
        ));
        let _ = std::fs::remove_dir_all(&directory);
        let config_store = ConfigStore::new(PathBuf::from(&directory));
        let history_store = HistoryKeyStore::new(FailingCredentialBackend);

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
                &history_store,
                &super::history_database_path(&directory),
                command.clone(),
            )
            .unwrap();

            assert_eq!(sequence, [command]);
        }
        assert!(!directory.exists());
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

        assert_eq!(sequence[4].kind, CommandKind::ConfigureHistoryKeys);
        assert!(sequence[4].payload["keys"]["v1"].is_string());
        assert_eq!(sequence[5].payload["history_enabled"], false);
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

        assert_eq!(sequence[4].payload["keys"], json!({}));
        assert_eq!(sequence[5].payload["history_enabled"], false);
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
        assert_eq!(sequence[3].kind, CommandKind::ConfigureHistoryPath);
        assert_eq!(sequence[4].kind, CommandKind::ConfigureHistoryKeys);
        assert_eq!(sequence[4].payload["keys"], json!({}));
        assert_eq!(sequence[5].kind, CommandKind::ConfigureHistoryPolicy);
        assert_eq!(sequence[5].payload["history_enabled"], true);
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
}
