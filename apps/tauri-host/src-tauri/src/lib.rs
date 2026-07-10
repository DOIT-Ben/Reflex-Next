mod clipboard;
mod commands;

pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_clipboard_manager::init())
        .invoke_handler(tauri::generate_handler![
            commands::read_clipboard_text,
            commands::runtime_available
        ])
        .run(tauri::generate_context!())
        .expect("error while running Reflex host");
}
