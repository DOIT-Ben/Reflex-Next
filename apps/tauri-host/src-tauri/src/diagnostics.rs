use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};

use serde_json::{Map, Value};

const DEFAULT_MAX_FILE_BYTES: u64 = 1_000_000;
const DEFAULT_MAX_FILES: usize = 3;
const DEFAULT_MAX_TOTAL_BYTES: u64 = 3_000_000;
const MAX_RECORD_BYTES: usize = 16 * 1024;

#[derive(Clone)]
pub struct HostDiagnostics {
    inner: Arc<Mutex<DiagnosticState>>,
}

struct DiagnosticState {
    directory: PathBuf,
    active_path: PathBuf,
    enabled: bool,
    available: bool,
    closed: bool,
    max_file_bytes: u64,
    max_files: usize,
    max_total_bytes: u64,
}

impl HostDiagnostics {
    pub fn from_environment(app_data_dir: &Path) -> Self {
        let enabled = std::env::var("REFLEX_DIAGNOSTICS_ENABLED").ok().as_deref() == Some("1");
        Self::new(app_data_dir.join("diagnostics"), enabled)
    }

    pub fn new(directory: PathBuf, enabled: bool) -> Self {
        Self::with_limits(
            directory,
            enabled,
            DEFAULT_MAX_FILE_BYTES,
            DEFAULT_MAX_FILES,
            DEFAULT_MAX_TOTAL_BYTES,
        )
    }

    fn with_limits(
        directory: PathBuf,
        enabled: bool,
        max_file_bytes: u64,
        max_files: usize,
        max_total_bytes: u64,
    ) -> Self {
        let active_path = directory.join("host-diagnostics.jsonl");
        let mut state = DiagnosticState {
            directory,
            active_path,
            enabled,
            available: false,
            closed: false,
            max_file_bytes,
            max_files,
            max_total_bytes,
        };
        if enabled {
            state.available = state.prepare().is_ok();
        }
        Self {
            inner: Arc::new(Mutex::new(state)),
        }
    }

    pub fn enabled(&self) -> bool {
        let state = self
            .inner
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        state.enabled
    }

    pub fn emit_lifecycle(&self, event: &str, status: &str) {
        let mut fields = Map::new();
        insert_identifier(&mut fields, "component", "host", 64);
        insert_identifier(&mut fields, "status", status, 64);
        self.emit(event, fields);
    }

    pub fn emit_recovery(&self, event: &str, status: &str, code: Option<&str>) {
        let mut fields = Map::new();
        insert_identifier(&mut fields, "component", "host", 64);
        insert_identifier(&mut fields, "status", status, 64);
        insert_optional_identifier(&mut fields, "code", code, 128);
        self.emit(event, fields);
    }

    pub fn observe_runtime_event(&self, event_name: &str, payload: &Value) {
        if !self.enabled() {
            return;
        }
        if event_name == crate::sidecar::CORE_EVENT_NAME {
            let Some(event) = payload.get("event").and_then(Value::as_object) else {
                return;
            };
            let Some(event_type) = event.get("type").and_then(Value::as_str) else {
                return;
            };
            let data = event.get("data").and_then(Value::as_object);
            match event_type {
                "error" => {
                    let mut fields = self.base_runtime_fields();
                    if let Some(data) = data {
                        insert_optional_identifier(
                            &mut fields,
                            "code",
                            data.get("code").and_then(Value::as_str),
                            128,
                        );
                        insert_optional_identifier(
                            &mut fields,
                            "diagnostic_id",
                            data.get("diagnostic_id").and_then(Value::as_str),
                            128,
                        );
                    }
                    insert_identifier(&mut fields, "status", "error", 64);
                    self.emit("runtime_error", fields);
                }
                "status" => {
                    let phase = data
                        .and_then(|value| value.get("phase"))
                        .and_then(Value::as_str);
                    if matches!(phase, Some("cancelled" | "completed")) {
                        let mut fields = self.base_runtime_fields();
                        insert_optional_identifier(&mut fields, "phase", phase, 64);
                        insert_optional_identifier(&mut fields, "status", phase, 64);
                        self.emit("runtime_status", fields);
                    }
                }
                "metric" => {
                    let mut fields = self.base_runtime_fields();
                    if let Some(seconds) = data
                        .and_then(|value| value.get("elapsed_seconds"))
                        .and_then(Value::as_f64)
                        .filter(|value| value.is_finite() && *value >= 0.0)
                    {
                        fields.insert(
                            "duration_ms".to_string(),
                            Value::from((seconds * 1000.0).round() as u64),
                        );
                    }
                    insert_identifier(&mut fields, "status", "completed", 64);
                    self.emit("runtime_metric", fields);
                }
                _ => {}
            }
            return;
        }

        if event_name == crate::sidecar::PLUGIN_EVENT_NAME {
            let status = payload.get("status").and_then(Value::as_str);
            if !matches!(status, Some("error" | "cancelled" | "result")) {
                return;
            }
            let mut fields = self.base_runtime_fields();
            insert_optional_identifier(
                &mut fields,
                "plugin_id",
                payload.get("plugin_id").and_then(Value::as_str),
                64,
            );
            insert_optional_identifier(
                &mut fields,
                "operation",
                payload.get("operation").and_then(Value::as_str),
                64,
            );
            insert_optional_identifier(&mut fields, "status", status, 64);
            insert_optional_identifier(
                &mut fields,
                "code",
                payload.get("code").and_then(Value::as_str),
                128,
            );
            self.emit("plugin_terminal", fields);
        }
    }

    pub fn close(&self) {
        let mut state = self
            .inner
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        state.closed = true;
        state.available = false;
    }

    fn base_runtime_fields(&self) -> Map<String, Value> {
        let mut fields = Map::new();
        insert_identifier(&mut fields, "component", "runtime", 64);
        fields
    }

    fn emit(&self, event: &str, fields: Map<String, Value>) {
        if !safe_identifier(event, 128) {
            return;
        }
        let mut state = self
            .inner
            .lock()
            .unwrap_or_else(|poisoned| poisoned.into_inner());
        if !state.enabled || !state.available || state.closed {
            return;
        }
        let mut record = Map::new();
        record.insert(
            "timestamp_unix_ms".to_string(),
            Value::from(
                SystemTime::now()
                    .duration_since(UNIX_EPOCH)
                    .map(|duration| duration.as_millis() as u64)
                    .unwrap_or(0),
            ),
        );
        record.insert("event".to_string(), Value::from(event));
        record.extend(fields);
        if state.append(Value::Object(record)).is_err() {
            state.available = false;
        }
    }
}

impl DiagnosticState {
    fn prepare(&mut self) -> std::io::Result<()> {
        fs::create_dir_all(&self.directory)?;
        let mut paths = vec![self.active_path.clone()];
        paths.extend((1..self.max_files).map(|index| self.backup_path(index)));
        for path in paths {
            if !path.exists() {
                continue;
            }
            if fs::metadata(&path)?.len() > self.max_file_bytes || !valid_jsonl(&path) {
                fs::remove_file(path)?;
            }
        }
        self.prune_total(0)
    }

    fn append(&mut self, record: Value) -> std::io::Result<()> {
        let mut payload = serde_json::to_vec(&record)?;
        payload.push(b'\n');
        if payload.len() > MAX_RECORD_BYTES || payload.len() as u64 > self.max_file_bytes {
            return Err(std::io::Error::other("diagnostic record is too large"));
        }
        let current_size = fs::metadata(&self.active_path)
            .map(|metadata| metadata.len())
            .unwrap_or(0);
        if current_size > 0 && current_size + payload.len() as u64 > self.max_file_bytes {
            self.rotate()?;
        }
        self.prune_total(payload.len() as u64)?;
        let mut file = OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.active_path)?;
        file.write_all(&payload)?;
        file.flush()
    }

    fn rotate(&self) -> std::io::Result<()> {
        if self.max_files <= 1 {
            if self.active_path.exists() {
                fs::remove_file(&self.active_path)?;
            }
            return Ok(());
        }
        let oldest = self.backup_path(self.max_files - 1);
        if oldest.exists() {
            fs::remove_file(oldest)?;
        }
        for index in (1..self.max_files - 1).rev() {
            let source = self.backup_path(index);
            if source.exists() {
                fs::rename(source, self.backup_path(index + 1))?;
            }
        }
        if self.active_path.exists() {
            fs::rename(&self.active_path, self.backup_path(1))?;
        }
        Ok(())
    }

    fn prune_total(&self, incoming: u64) -> std::io::Result<()> {
        let mut total = self.total_size();
        for index in (1..self.max_files).rev() {
            if total + incoming <= self.max_total_bytes {
                break;
            }
            let path = self.backup_path(index);
            if path.exists() {
                let size = fs::metadata(&path)?.len();
                fs::remove_file(path)?;
                total = total.saturating_sub(size);
            }
        }
        if total + incoming > self.max_total_bytes {
            Err(std::io::Error::other("diagnostic storage limit reached"))
        } else {
            Ok(())
        }
    }

    fn total_size(&self) -> u64 {
        let active = fs::metadata(&self.active_path)
            .map(|metadata| metadata.len())
            .unwrap_or(0);
        active
            + (1..self.max_files)
                .map(|index| {
                    fs::metadata(self.backup_path(index))
                        .map(|metadata| metadata.len())
                        .unwrap_or(0)
                })
                .sum::<u64>()
    }

    fn backup_path(&self, index: usize) -> PathBuf {
        self.directory
            .join(format!("host-diagnostics.{index}.jsonl"))
    }
}

fn insert_identifier(fields: &mut Map<String, Value>, key: &str, value: &str, limit: usize) {
    if safe_identifier(value, limit) {
        fields.insert(key.to_string(), Value::from(value));
    }
}

fn insert_optional_identifier(
    fields: &mut Map<String, Value>,
    key: &str,
    value: Option<&str>,
    limit: usize,
) {
    if let Some(value) = value {
        insert_identifier(fields, key, value, limit);
    }
}

fn safe_identifier(value: &str, limit: usize) -> bool {
    !value.is_empty()
        && value.len() <= limit
        && value.bytes().all(|byte| {
            byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b':' | b'@' | b'/')
        })
}

fn valid_jsonl(path: &Path) -> bool {
    let Ok(content) = fs::read_to_string(path) else {
        return false;
    };
    content.lines().all(|line| {
        line.trim().is_empty()
            || serde_json::from_str::<Value>(line).is_ok_and(|value| value.is_object())
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_directory(suffix: &str) -> PathBuf {
        std::env::temp_dir().join(format!(
            "reflex-host-diagnostics-{}-{suffix}",
            std::process::id()
        ))
    }

    fn records(directory: &Path) -> Vec<Value> {
        let mut records = Vec::new();
        let Ok(entries) = fs::read_dir(directory) else {
            return records;
        };
        for entry in entries.flatten() {
            if !entry
                .file_name()
                .to_string_lossy()
                .starts_with("host-diagnostics")
            {
                continue;
            }
            let content = fs::read_to_string(entry.path()).unwrap();
            records.extend(
                content
                    .lines()
                    .map(|line| serde_json::from_str(line).unwrap()),
            );
        }
        records
    }

    #[test]
    fn disabled_diagnostics_do_not_create_storage() {
        let directory = temp_directory("disabled");
        let _ = fs::remove_dir_all(&directory);
        let diagnostics = HostDiagnostics::new(directory.clone(), false);

        diagnostics.emit_lifecycle("host_started", "ready");

        assert!(!directory.exists());
    }

    #[test]
    fn runtime_observer_drops_bodies_and_keeps_safe_terminal_fields() {
        let directory = temp_directory("terminal");
        let _ = fs::remove_dir_all(&directory);
        let diagnostics = HostDiagnostics::new(directory.clone(), true);
        diagnostics.observe_runtime_event(
            crate::sidecar::CORE_EVENT_NAME,
            &serde_json::json!({
                "request_id": format!("{}{}", "sk-", "cp-private-request-id-must-not-be-logged"),
                "event": {
                    "type": "error",
                    "data": {
                        "code": "provider_unavailable",
                        "diagnostic_id": "diag-123",
                        "message": "private body must not be logged",
                        "text": "private output must not be logged"
                    }
                }
            }),
        );
        diagnostics.close();

        let records = records(&directory);
        assert_eq!(records.len(), 1);
        assert_eq!(records[0]["code"], "provider_unavailable");
        assert_eq!(records[0]["diagnostic_id"], "diag-123");
        let serialized = serde_json::to_string(&records).unwrap();
        assert!(!serialized.contains("private-request-id"));
        assert!(!serialized.contains("private body"));
        assert!(!serialized.contains("private output"));
        let _ = fs::remove_dir_all(directory);
    }

    #[test]
    fn plugin_observer_keeps_operation_but_drops_result_data_and_request_id() {
        let directory = temp_directory("plugin-terminal");
        let _ = fs::remove_dir_all(&directory);
        let diagnostics = HostDiagnostics::new(directory.clone(), true);
        diagnostics.observe_runtime_event(
            crate::sidecar::PLUGIN_EVENT_NAME,
            &serde_json::json!({
                "request_id": "private-history-request",
                "plugin_id": "history-sqlite",
                "operation": "restore",
                "status": "result",
                "data": {
                    "backup_id": "private-backup-id",
                    "path": "C:/private/history.sqlite3"
                }
            }),
        );
        diagnostics.close();

        let records = records(&directory);
        assert_eq!(records.len(), 1);
        assert_eq!(records[0]["event"], "plugin_terminal");
        assert_eq!(records[0]["plugin_id"], "history-sqlite");
        assert_eq!(records[0]["operation"], "restore");
        assert_eq!(records[0]["status"], "result");
        let serialized = serde_json::to_string(&records).unwrap();
        assert!(!serialized.contains("private-history-request"));
        assert!(!serialized.contains("private-backup-id"));
        assert!(!serialized.contains("private/history.sqlite3"));
        let _ = fs::remove_dir_all(directory);
    }

    #[test]
    fn bounded_files_rotate_and_remain_valid_jsonl() {
        let directory = temp_directory("rotation");
        let _ = fs::remove_dir_all(&directory);
        let diagnostics = HostDiagnostics::with_limits(directory.clone(), true, 256, 3, 700);
        for index in 0..100 {
            diagnostics.observe_runtime_event(
                crate::sidecar::CORE_EVENT_NAME,
                &serde_json::json!({
                    "request_id": format!("request-{index}"),
                    "event": {"type": "status", "data": {"phase": "completed"}}
                }),
            );
        }
        diagnostics.close();

        let files = fs::read_dir(&directory).unwrap().count();
        assert!((2..=3).contains(&files));
        assert!(!records(&directory).is_empty());
        assert!(
            fs::read_dir(&directory)
                .unwrap()
                .flatten()
                .map(|entry| entry.metadata().unwrap().len())
                .sum::<u64>()
                <= 700
        );
        let _ = fs::remove_dir_all(directory);
    }

    #[test]
    fn corrupt_active_file_is_discarded_before_new_records() {
        let directory = temp_directory("corrupt");
        let _ = fs::remove_dir_all(&directory);
        fs::create_dir_all(&directory).unwrap();
        fs::write(directory.join("host-diagnostics.jsonl"), b"not-json\xff\n").unwrap();

        let diagnostics = HostDiagnostics::new(directory.clone(), true);
        diagnostics.emit_lifecycle("host_started", "ready");
        diagnostics.close();

        let records = records(&directory);
        assert_eq!(records.len(), 1);
        assert_eq!(records[0]["event"], "host_started");
        let _ = fs::remove_dir_all(directory);
    }
}
