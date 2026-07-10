mod clipboard;
mod commands;
mod config_store;
mod runtime_commands;
mod sidecar;

pub fn run() {
    use tauri::Manager;

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_clipboard_manager::init())
        .setup(|app| {
            app.manage(commands::TauriRuntimeState::new(app.handle().clone()));
            app.manage(config_store::ConfigStore::new(app.path().app_config_dir()?));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::read_clipboard_text,
            commands::load_app_config,
            commands::save_app_config,
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
