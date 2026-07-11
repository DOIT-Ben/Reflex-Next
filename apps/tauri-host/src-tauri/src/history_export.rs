use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};
use serde_json::Value;

pub const HISTORY_EXPORT_ERROR_MESSAGE: &str = "历史导出失败，请重试。";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExportFormat {
    Json,
    Csv,
    Markdown,
}

impl ExportFormat {
    pub fn extension(self) -> &'static str {
        match self {
            Self::Json => "json",
            Self::Csv => "csv",
            Self::Markdown => "md",
        }
    }

    pub fn wire_name(self) -> &'static str {
        match self {
            Self::Json => "json",
            Self::Csv => "csv",
            Self::Markdown => "markdown",
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct ExportRequest {
    pub format: ExportFormat,
    pub filters: Value,
}

#[cfg(test)]
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExportOutcome {
    Cancelled,
    Written,
}

pub struct AtomicExportWriter {
    target: PathBuf,
    temporary: PathBuf,
    journal: Option<PathBuf>,
    stream: Option<File>,
    committed: bool,
}

impl AtomicExportWriter {
    #[cfg(test)]
    pub fn new(target: &Path) -> Result<Self, &'static str> {
        Self::new_internal(target, None)
    }

    pub fn new_registered(target: &Path, journal: &Path) -> Result<Self, &'static str> {
        cleanup_pending_export(journal)?;
        Self::new_internal(target, Some(journal))
    }

    fn new_internal(target: &Path, journal: Option<&Path>) -> Result<Self, &'static str> {
        let temporary = temporary_path(target)?;
        let stream = open_private_temporary(&temporary)?;
        if let Some(journal) = journal {
            if write_pending_export(journal, &temporary).is_err() {
                drop(stream);
                let _ = fs::remove_file(&temporary);
                return Err(HISTORY_EXPORT_ERROR_MESSAGE);
            }
        }
        Ok(Self {
            target: target.to_path_buf(),
            temporary,
            journal: journal.map(Path::to_path_buf),
            stream: Some(stream),
            committed: false,
        })
    }

    pub fn write_chunk(&mut self, body: &[u8]) -> Result<(), &'static str> {
        self.stream
            .as_mut()
            .ok_or(HISTORY_EXPORT_ERROR_MESSAGE)?
            .write_all(body)
            .map_err(|_| HISTORY_EXPORT_ERROR_MESSAGE)
    }

    #[cfg(test)]
    fn abandon_without_drop(mut self) {
        self.stream.take();
        std::mem::forget(self);
    }

    pub fn commit(mut self) -> Result<(), &'static str> {
        let mut stream = self.stream.take().ok_or(HISTORY_EXPORT_ERROR_MESSAGE)?;
        stream.flush().map_err(|_| HISTORY_EXPORT_ERROR_MESSAGE)?;
        stream
            .sync_all()
            .map_err(|_| HISTORY_EXPORT_ERROR_MESSAGE)?;
        drop(stream);
        replace_file(&self.temporary, &self.target)?;
        sync_parent(&self.target)?;
        if let Some(journal) = self.journal.as_deref() {
            clear_pending_export(journal)?;
        }
        self.committed = true;
        Ok(())
    }
}

impl Drop for AtomicExportWriter {
    fn drop(&mut self) {
        if !self.committed {
            self.stream.take();
            let _ = fs::remove_file(&self.temporary);
            if let Some(journal) = self.journal.as_deref() {
                let _ = clear_pending_export(journal);
            }
        }
    }
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct PendingExport {
    version: u8,
    temporary: PathBuf,
}

pub fn pending_export_journal(app_data_dir: &Path) -> PathBuf {
    app_data_dir.join("history").join("pending-export.json")
}

pub fn cleanup_pending_export(journal: &Path) -> Result<(), &'static str> {
    if !journal.is_file() {
        return Ok(());
    }
    let body = match fs::read(journal) {
        Ok(body) => body,
        Err(_) => {
            discard_invalid_journal(journal);
            return Ok(());
        }
    };
    if body.len() > 4096 {
        discard_invalid_journal(journal);
        return Ok(());
    }
    let pending: PendingExport = match serde_json::from_slice(&body) {
        Ok(pending) => pending,
        Err(_) => {
            discard_invalid_journal(journal);
            return Ok(());
        }
    };
    if pending.version != 1 || !valid_temporary_path(&pending.temporary) {
        discard_invalid_journal(journal);
        return Ok(());
    }
    match fs::symlink_metadata(&pending.temporary) {
        Ok(metadata) if metadata.file_type().is_symlink() || !metadata.is_file() => {
            discard_invalid_journal(journal);
            return Ok(());
        }
        Ok(_) => {
            if fs::remove_file(&pending.temporary).is_err() {
                return Ok(());
            }
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(_) => return Ok(()),
    }
    let _ = clear_pending_export(journal);
    Ok(())
}

fn discard_invalid_journal(journal: &Path) {
    let _ = fs::remove_file(journal);
    let _ = sync_parent(journal);
}

fn write_pending_export(journal: &Path, temporary: &Path) -> Result<(), &'static str> {
    let parent = journal.parent().ok_or(HISTORY_EXPORT_ERROR_MESSAGE)?;
    fs::create_dir_all(parent).map_err(|_| HISTORY_EXPORT_ERROR_MESSAGE)?;
    let pending = PendingExport {
        version: 1,
        temporary: temporary.to_path_buf(),
    };
    let body = serde_json::to_vec(&pending).map_err(|_| HISTORY_EXPORT_ERROR_MESSAGE)?;
    let staging = parent.join(format!(".pending-export-{}.tmp", random_suffix()?));
    let mut stream = open_private_temporary(&staging)?;
    let result = (|| {
        stream
            .write_all(&body)
            .map_err(|_| HISTORY_EXPORT_ERROR_MESSAGE)?;
        stream.flush().map_err(|_| HISTORY_EXPORT_ERROR_MESSAGE)?;
        stream
            .sync_all()
            .map_err(|_| HISTORY_EXPORT_ERROR_MESSAGE)?;
        drop(stream);
        fs::rename(&staging, journal).map_err(|_| HISTORY_EXPORT_ERROR_MESSAGE)?;
        sync_parent(journal)
    })();
    if result.is_err() {
        let _ = fs::remove_file(&staging);
    }
    result
}

fn clear_pending_export(journal: &Path) -> Result<(), &'static str> {
    match fs::remove_file(journal) {
        Ok(()) => sync_parent(journal),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(_) => Err(HISTORY_EXPORT_ERROR_MESSAGE),
    }
}

pub fn validate_export_request(value: Value) -> Result<ExportRequest, &'static str> {
    let Value::Object(mut object) = value else {
        return Err(HISTORY_EXPORT_ERROR_MESSAGE);
    };
    if object.len() != 2 || !object.contains_key("format") || !object.contains_key("filters") {
        return Err(HISTORY_EXPORT_ERROR_MESSAGE);
    }
    let format = match object
        .remove("format")
        .and_then(|value| value.as_str().map(str::to_string))
        .as_deref()
    {
        Some("json") => ExportFormat::Json,
        Some("csv") => ExportFormat::Csv,
        Some("markdown") => ExportFormat::Markdown,
        _ => return Err(HISTORY_EXPORT_ERROR_MESSAGE),
    };
    let filters = object
        .remove("filters")
        .filter(Value::is_object)
        .ok_or(HISTORY_EXPORT_ERROR_MESSAGE)?;
    Ok(ExportRequest { format, filters })
}

#[cfg(test)]
pub fn write_selected_export(
    target: Option<&Path>,
    body: &[u8],
) -> Result<ExportOutcome, &'static str> {
    let Some(target) = target else {
        return Ok(ExportOutcome::Cancelled);
    };
    let mut writer = AtomicExportWriter::new(target)?;
    writer.write_chunk(body)?;
    writer.commit()?;
    Ok(ExportOutcome::Written)
}

fn temporary_path(target: &Path) -> Result<PathBuf, &'static str> {
    let parent = target.parent().ok_or(HISTORY_EXPORT_ERROR_MESSAGE)?;
    target
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or(HISTORY_EXPORT_ERROR_MESSAGE)?;
    Ok(parent.join(format!(".reflex-history-export-{}.tmp", random_suffix()?)))
}

fn random_suffix() -> Result<String, &'static str> {
    let mut random = [0_u8; 8];
    getrandom::fill(&mut random).map_err(|_| HISTORY_EXPORT_ERROR_MESSAGE)?;
    Ok(random
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>())
}

fn valid_temporary_path(path: &Path) -> bool {
    let Some(name) = path.file_name().and_then(|name| name.to_str()) else {
        return false;
    };
    let Some(suffix) = name
        .strip_prefix(".reflex-history-export-")
        .and_then(|name| name.strip_suffix(".tmp"))
    else {
        return false;
    };
    path.is_absolute() && suffix.len() == 16 && suffix.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn open_private_temporary(path: &Path) -> Result<File, &'static str> {
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::OpenOptionsExt;
        use windows_sys::Win32::Storage::FileSystem::{
            FILE_ATTRIBUTE_HIDDEN, FILE_ATTRIBUTE_TEMPORARY,
        };
        options.share_mode(0);
        options.attributes(FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_TEMPORARY);
    }
    options.open(path).map_err(|_| HISTORY_EXPORT_ERROR_MESSAGE)
}

#[cfg(windows)]
fn replace_file(source: &Path, target: &Path) -> Result<(), &'static str> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::ReplaceFileW;

    if !target.exists() {
        return fs::rename(source, target).map_err(|_| HISTORY_EXPORT_ERROR_MESSAGE);
    }
    let target = target
        .as_os_str()
        .encode_wide()
        .chain(Some(0))
        .collect::<Vec<_>>();
    let source = source
        .as_os_str()
        .encode_wide()
        .chain(Some(0))
        .collect::<Vec<_>>();
    let result = unsafe {
        ReplaceFileW(
            target.as_ptr(),
            source.as_ptr(),
            std::ptr::null(),
            0,
            std::ptr::null(),
            std::ptr::null(),
        )
    };
    if result == 0 {
        Err(HISTORY_EXPORT_ERROR_MESSAGE)
    } else {
        Ok(())
    }
}

#[cfg(not(windows))]
fn replace_file(source: &Path, target: &Path) -> Result<(), &'static str> {
    fs::rename(source, target).map_err(|_| HISTORY_EXPORT_ERROR_MESSAGE)
}

#[cfg(not(windows))]
fn sync_parent(target: &Path) -> Result<(), &'static str> {
    let parent = OpenOptions::new()
        .read(true)
        .open(target.parent().ok_or(HISTORY_EXPORT_ERROR_MESSAGE)?)
        .map_err(|_| HISTORY_EXPORT_ERROR_MESSAGE)?;
    parent.sync_all().map_err(|_| HISTORY_EXPORT_ERROR_MESSAGE)
}

#[cfg(windows)]
fn sync_parent(_target: &Path) -> Result<(), &'static str> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::fs;

    use serde_json::json;

    use super::{
        cleanup_pending_export, validate_export_request, write_selected_export, AtomicExportWriter,
        ExportFormat, ExportOutcome,
    };

    #[test]
    fn export_request_accepts_only_format_and_filters_without_path_or_authority() {
        let request = validate_export_request(json!({
            "format": "json",
            "filters": {"provider": "minimax"}
        }))
        .unwrap();
        assert_eq!(request.format, ExportFormat::Json);
        assert_eq!(request.filters["provider"], "minimax");
        for forbidden in ["path", "handle", "confirmed", "admin"] {
            assert!(validate_export_request(json!({
                "format": "json",
                "filters": {},
                forbidden: true
            }))
            .is_err());
        }
    }

    #[test]
    fn stream_writer_flushes_chunks_and_atomically_replaces_on_success() {
        let root = std::env::temp_dir().join(format!("reflex-next-export-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).unwrap();
        let target = root.join("history.json");
        fs::write(&target, b"old").unwrap();

        let mut writer = AtomicExportWriter::new(&target).unwrap();
        writer.write_chunk(b"n").unwrap();
        writer.write_chunk(b"ew").unwrap();
        writer.commit().unwrap();

        assert_eq!(fs::read(&target).unwrap(), b"new");
        assert_eq!(fs::read_dir(&root).unwrap().count(), 1);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn export_format_uses_stable_extensions_and_rejects_unknown_format() {
        assert_eq!(ExportFormat::Json.extension(), "json");
        assert_eq!(ExportFormat::Csv.extension(), "csv");
        assert_eq!(ExportFormat::Markdown.extension(), "md");
        assert!(validate_export_request(json!({"format": "html", "filters": {}})).is_err());
    }

    #[test]
    fn native_dialog_cancel_creates_no_target_or_temporary_file() {
        let root =
            std::env::temp_dir().join(format!("reflex-next-export-cancel-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).unwrap();

        let result = write_selected_export(None, b"private body").unwrap();

        assert_eq!(result, ExportOutcome::Cancelled);
        assert_eq!(fs::read_dir(&root).unwrap().count(), 0);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn dropping_stream_writer_preserves_existing_target_and_removes_temporary_file() {
        let root =
            std::env::temp_dir().join(format!("reflex-next-export-drop-{}", std::process::id()));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).unwrap();
        let target = root.join("history.json");
        fs::write(&target, b"old").unwrap();
        {
            let mut writer = AtomicExportWriter::new(&target).unwrap();
            writer.write_chunk(b"private body").unwrap();
        }

        assert_eq!(fs::read(&target).unwrap(), b"old");
        assert_eq!(fs::read_dir(&root).unwrap().count(), 1);
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn startup_cleanup_removes_plaintext_temp_when_drop_never_ran() {
        let root = std::env::temp_dir().join(format!(
            "reflex-next-export-crash-cleanup-{}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).unwrap();
        let target = root.join("history.json");
        let journal = root.join("private").join("pending-export.json");
        fs::write(&target, b"old").unwrap();
        let mut writer = AtomicExportWriter::new_registered(&target, &journal).unwrap();
        writer.write_chunk(b"private body").unwrap();
        writer.abandon_without_drop();
        assert!(journal.is_file());
        assert_eq!(
            fs::read_dir(&root)
                .unwrap()
                .filter_map(Result::ok)
                .filter(|entry| entry
                    .file_name()
                    .to_string_lossy()
                    .starts_with(".reflex-history-export-"))
                .count(),
            1
        );

        cleanup_pending_export(&journal).unwrap();

        assert_eq!(fs::read(&target).unwrap(), b"old");
        assert!(!journal.exists());
        assert_eq!(
            fs::read_dir(&root)
                .unwrap()
                .filter_map(Result::ok)
                .filter(|entry| entry
                    .file_name()
                    .to_string_lossy()
                    .starts_with(".reflex-history-export-"))
                .count(),
            0
        );
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn invalid_cleanup_journal_never_deletes_referenced_file_or_blocks_startup() {
        let root = std::env::temp_dir().join(format!(
            "reflex-next-export-invalid-journal-{}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&root);
        fs::create_dir_all(&root).unwrap();
        let journal = root.join("pending-export.json");
        let sentinel = root.join(".reflex-history-export-0123456789abcdef.tmp");
        fs::write(&sentinel, b"must stay").unwrap();
        for body in [
            b"not-json".to_vec(),
            vec![b'x'; 4097],
            serde_json::to_vec(&serde_json::json!({
                "version": 2,
                "temporary": sentinel,
            }))
            .unwrap(),
        ] {
            fs::write(&journal, body).unwrap();

            cleanup_pending_export(&journal).unwrap();

            assert_eq!(fs::read(&sentinel).unwrap(), b"must stay");
            assert!(!journal.exists());
        }
        let _ = fs::remove_dir_all(root);
    }
}
