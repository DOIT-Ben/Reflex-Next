use tauri::AppHandle;

fn runtime_available_value() -> bool {
    false
}

#[tauri::command]
pub async fn read_clipboard_text(app: AppHandle) -> Result<String, String> {
    crate::clipboard::read_clipboard_text(&app).map_err(str::to_string)
}

#[tauri::command]
pub async fn runtime_available() -> bool {
    runtime_available_value()
}

#[cfg(test)]
mod tests {
    #[test]
    fn runtime_capability_stays_disabled_in_task_1() {
        assert!(!super::runtime_available_value());
    }
}
