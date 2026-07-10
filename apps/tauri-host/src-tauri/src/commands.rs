use std::sync::Arc;

use serde_json::Value;
use tauri::{AppHandle, Emitter, State};

use crate::config_store::{AppConfig, ConfigStore};
use crate::runtime_commands::{validate_command, CommandKind};
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
pub async fn runtime_optimize(
    state: State<'_, TauriRuntimeState>,
    command: Value,
) -> Result<(), String> {
    forward_runtime_command(&state.runtime, command, CommandKind::Optimize)
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

#[cfg(test)]
mod tests {
    #[test]
    fn runtime_capability_is_enabled_when_the_development_runtime_layout_resolves() {
        assert!(super::runtime_available_value());
    }
}
