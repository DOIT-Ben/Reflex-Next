mod clipboard;
mod commands;
mod config_store;
mod desktop;
mod history_export;
mod history_key_store;
mod plugin_commands;
mod runtime_commands;
mod secret_store;
mod sidecar;
mod window;

pub fn run() {
    use tauri::Manager;
    use tauri_plugin_global_shortcut::ShortcutState;

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            let _ = window::show_main_window(app);
        }))
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, _shortcut, event| {
                    if event.state == ShortcutState::Pressed {
                        let _ = window::show_main_window(app);
                    }
                })
                .build(),
        )
        .plugin(tauri_plugin_clipboard_manager::init())
        .plugin(tauri_plugin_dialog::init())
        .setup(|app| {
            configure_bundled_runtime(app);
            let app_data_dir = app.path().app_data_dir()?;
            history_export::cleanup_pending_export(&history_export::pending_export_journal(
                &app_data_dir,
            ))
            .map_err(std::io::Error::other)?;
            let config_store = config_store::ConfigStore::new(app.path().app_config_dir()?);
            let config = config_store.load().unwrap_or_default();
            let desktop_state = desktop::DesktopState::new(config.hotkey.clone());
            let _ = desktop::register_hotkey(app.handle(), &desktop_state, &config.hotkey);
            if desktop::setup_tray(app).is_ok() {
                desktop_state.mark_tray_available();
            }
            app.manage(commands::TauriRuntimeState::new(app.handle().clone()));
            app.manage(config_store);
            app.manage(desktop_state);
            app.manage(secret_store::SecretStore::windows());
            app.manage(history_key_store::HistoryKeyStore::windows());
            app.manage(commands::HistoryOperationControl::new());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::read_clipboard_text,
            commands::write_clipboard_text,
            commands::show_main_window,
            commands::hide_main_window,
            commands::show_history_window,
            commands::desktop_status,
            commands::load_app_config,
            commands::save_app_config,
            commands::provider_secret_status,
            commands::save_provider_secret,
            commands::delete_provider_secret,
            commands::runtime_available,
            commands::runtime_optimize,
            commands::runtime_cancel,
            commands::runtime_list_plugins,
            commands::runtime_plugin_call,
            commands::runtime_plugin_cancel,
            commands::history_export,
            commands::history_admin_operation,
            commands::history_operation_cancel,
            commands::history_reuse_intent
        ])
        .build(tauri::generate_context!())
        .expect("error while building Reflex host");

    app.run(|app, event| match event {
        tauri::RunEvent::WindowEvent { label, event, .. } if label == "main" => {
            if let tauri::WindowEvent::CloseRequested { api, .. } = event {
                if app.state::<desktop::DesktopState>().tray_available() {
                    api.prevent_close();
                    let _ = window::hide_main_window(app);
                }
            }
        }
        tauri::RunEvent::Exit => {
            app.state::<commands::TauriRuntimeState>().shutdown();
        }
        _ => {}
    })
}

fn configure_bundled_runtime(app: &tauri::App) {
    use tauri::Manager;

    if cfg!(debug_assertions) {
        return;
    }
    let Ok(resource_dir) = app.path().resource_dir() else {
        return;
    };
    let executable = resource_dir.join("runtime").join("reflex-runtime.exe");
    if executable.is_file() {
        std::env::set_var("REFLEX_RUNTIME_EXECUTABLE", executable);
    }
}

#[cfg(test)]
mod tests {
    use serde_json::Value;

    #[test]
    fn main_capability_exposes_public_settings_commands_but_not_private_configuration() {
        let capability: Value =
            serde_json::from_str(include_str!("../capabilities/default.json")).unwrap();
        let permissions = capability["permissions"].as_array().unwrap();
        let permissions = permissions
            .iter()
            .filter_map(Value::as_str)
            .collect::<Vec<_>>();

        for permission in [
            "allow-show-main-window",
            "allow-hide-main-window",
            "allow-load-app-config",
            "allow-save-app-config",
            "allow-provider-secret-status",
            "allow-save-provider-secret",
            "allow-delete-provider-secret",
            "allow-runtime-list-plugins",
            "allow-runtime-plugin-call",
            "allow-runtime-plugin-cancel",
            "allow-show-history-window",
        ] {
            assert!(permissions.contains(&permission), "missing {permission}");
        }
        assert!(!permissions.contains(&"allow-configure-provider"));
        for permission in [
            "allow-configure-plugin",
            "allow-configure-history-keys",
            "allow-configure-history-policy",
            "allow-plugin-admin-call",
        ] {
            assert!(!permissions.contains(&permission));
        }
    }

    #[test]
    fn history_capability_is_window_scoped_and_exposes_no_private_runtime_builder() {
        let capability: Value =
            serde_json::from_str(include_str!("../capabilities/history.json")).unwrap();
        assert_eq!(capability["windows"], serde_json::json!(["history"]));
        let permissions = capability["permissions"].as_array().unwrap();
        let permissions = permissions
            .iter()
            .filter_map(Value::as_str)
            .collect::<Vec<_>>();
        for permission in [
            "allow-history-export",
            "allow-history-admin-operation",
            "allow-history-operation-cancel",
        ] {
            assert!(permissions.contains(&permission));
        }
        for forbidden in [
            "allow-show-history-window",
            "allow-configure-history-keys",
            "allow-configure-history-policy",
            "allow-plugin-admin-call",
            "dialog:allow-message",
            "dialog:allow-save",
        ] {
            assert!(!permissions.contains(&forbidden));
        }
        let config: Value = serde_json::from_str(include_str!("../tauri.conf.json")).unwrap();
        assert_eq!(
            config["app"]["security"]["capabilities"],
            serde_json::json!(["main-capability", "history-capability"])
        );
        let csp = config["app"]["security"]["csp"].as_str().unwrap();
        for directive in [
            "object-src 'none'",
            "frame-src 'none'",
            "form-action 'none'",
        ] {
            assert!(csp.contains(directive));
        }
        assert!(!csp.contains("https://"));
    }
}
