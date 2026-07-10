mod clipboard;
mod commands;
mod runtime_commands;
mod sidecar;

pub fn run() {
    use tauri::Manager;

    let app = tauri::Builder::default()
        .plugin(tauri_plugin_clipboard_manager::init())
        .setup(|app| {
            app.manage(commands::TauriRuntimeState::new(app.handle().clone()));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::read_clipboard_text,
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
