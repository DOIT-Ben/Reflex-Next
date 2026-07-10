mod clipboard;
mod commands;
mod config_store;
mod runtime_commands;
mod secret_store;
mod sidecar;

pub fn run() {
    use tauri::Manager;

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_clipboard_manager::init())
        .setup(|app| {
            app.manage(commands::TauriRuntimeState::new(app.handle().clone()));
            app.manage(config_store::ConfigStore::new(app.path().app_config_dir()?));
            app.manage(secret_store::SecretStore::windows());
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::read_clipboard_text,
            commands::load_app_config,
            commands::save_app_config,
            commands::provider_secret_status,
            commands::save_provider_secret,
            commands::delete_provider_secret,
            commands::runtime_available,
            commands::runtime_optimize,
            commands::runtime_cancel
        ])
        .build(tauri::generate_context!())
        .expect("error while building Reflex host");

    app.run(|app, event| {
        if matches!(event, tauri::RunEvent::Exit) {
            app.state::<commands::TauriRuntimeState>().shutdown();
        }
    })
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
            "allow-load-app-config",
            "allow-save-app-config",
            "allow-provider-secret-status",
            "allow-save-provider-secret",
            "allow-delete-provider-secret",
        ] {
            assert!(permissions.contains(&permission), "missing {permission}");
        }
        assert!(!permissions.contains(&"allow-configure-provider"));
    }
}
