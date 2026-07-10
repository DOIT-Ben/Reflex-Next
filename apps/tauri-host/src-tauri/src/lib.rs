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
