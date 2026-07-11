fn main() {
    tauri_build::try_build(tauri_build::Attributes::new().app_manifest(
        tauri_build::AppManifest::new().commands(&[
            "read_clipboard_text",
            "write_clipboard_text",
            "show_main_window",
            "hide_main_window",
            "desktop_status",
            "runtime_available",
            "runtime_optimize",
            "runtime_cancel",
            "runtime_list_plugins",
            "runtime_plugin_call",
            "runtime_plugin_cancel",
            "history_export",
            "history_admin_operation",
            "history_operation_cancel",
            "load_app_config",
            "save_app_config",
            "provider_secret_status",
            "save_provider_secret",
            "delete_provider_secret",
        ]),
    ))
    .expect("failed to build Tauri application");
}
