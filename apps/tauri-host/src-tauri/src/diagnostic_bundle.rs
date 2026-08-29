use std::fs::{self, File, OpenOptions};
use std::io::{Read, Write};
use std::path::{Component, Path, PathBuf};

use serde::{Deserialize, Serialize};
use serde_json::{json, Map, Value};
use zip::write::SimpleFileOptions;
use zip::{CompressionMethod, ZipWriter};

pub const DIAGNOSTIC_EXPORT_ERROR_MESSAGE: &str = "诊断包导出失败，请重试。";
pub const DIAGNOSTIC_EXPORT_EMPTY_MESSAGE: &str = "暂无可导出的诊断记录。请先启用本地诊断。";
pub const DIAGNOSTIC_EXPORT_BLOCKED_MESSAGE: &str = "诊断记录包含无法安全导出的内容，已停止导出。";
pub const DIAGNOSTIC_EXPORT_BUSY_MESSAGE: &str = "诊断包正在导出，请稍候。";

const MAX_FILE_BYTES: u64 = 1_000_000;
const MAX_TOTAL_INPUT_BYTES: u64 = 6_000_000;
const MAX_LINE_BYTES: usize = 64 * 1024;
const MAX_ZIP_BYTES: u64 = 8_000_000;
const PENDING_EXPORT_FILE: &str = "pending-diagnostic-export.json";
const PENDING_EXPORT_VERSION: u8 = 1;

const INPUT_FILES: [(&str, SourceKind); 6] = [
    ("host-diagnostics.jsonl", SourceKind::Host),
    ("host-diagnostics.1.jsonl", SourceKind::Host),
    ("host-diagnostics.2.jsonl", SourceKind::Host),
    ("runtime-diagnostics.jsonl", SourceKind::Runtime),
    ("runtime-diagnostics.1.jsonl", SourceKind::Runtime),
    ("runtime-diagnostics.2.jsonl", SourceKind::Runtime),
];

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ExportOutcome {
    Cancelled,
    Written,
}

#[derive(Clone, Copy)]
enum SourceKind {
    Host,
    Runtime,
}

impl SourceKind {
    fn name(self) -> &'static str {
        match self {
            Self::Host => "host",
            Self::Runtime => "runtime",
        }
    }
}

struct NormalizedFile {
    name: &'static str,
    source: SourceKind,
    body: Vec<u8>,
    records: usize,
}

struct NormalizedInput {
    body: Vec<u8>,
    input_bytes: u64,
    records: usize,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct PendingExport {
    version: u8,
    temporary: PathBuf,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct HostRecord {
    timestamp_unix_ms: u64,
    event: String,
    component: Option<String>,
    status: Option<String>,
    code: Option<String>,
    diagnostic_id: Option<String>,
    phase: Option<String>,
    duration_ms: Option<u64>,
    plugin_id: Option<String>,
    operation: Option<String>,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct RuntimeRecord {
    timestamp: String,
    event: String,
    level: Option<String>,
    component: Option<String>,
    code: Option<String>,
    request_id: Option<String>,
    provider_id: Option<String>,
    model: Option<String>,
    phase: Option<String>,
    status: Option<String>,
    error_type: Option<String>,
    duration_ms: Option<u64>,
    chunk_count: Option<u64>,
    cancel_latency_ms: Option<u64>,
    diagnostic_id: Option<String>,
    plugin_id: Option<String>,
    operation: Option<String>,
}

pub fn export_diagnostic_bundle(
    diagnostics_dir: &Path,
    target: &Path,
    is_cancelled: impl Fn() -> bool,
) -> Result<ExportOutcome, &'static str> {
    validate_absolute_local_path(diagnostics_dir)?;
    validate_absolute_local_path(target)?;
    if target.extension().and_then(|value| value.to_str()) != Some("zip") {
        return Err(DIAGNOSTIC_EXPORT_ERROR_MESSAGE);
    }
    let target_parent = target.parent().ok_or(DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
    if !diagnostics_dir.exists() {
        return Err(DIAGNOSTIC_EXPORT_EMPTY_MESSAGE);
    }
    validate_directory(diagnostics_dir)?;
    validate_directory(target_parent)?;
    validate_existing_target(target)?;
    cleanup_pending_export(diagnostics_dir)?;

    if is_cancelled() {
        return Ok(ExportOutcome::Cancelled);
    }

    let mut normalized_files = Vec::new();
    let mut total_input_bytes = 0_u64;
    let mut total_records = 0_usize;
    for (name, source) in INPUT_FILES {
        if is_cancelled() {
            return Ok(ExportOutcome::Cancelled);
        }
        let path = diagnostics_dir.join(name);
        let normalized = match read_and_normalize(&path, source, &is_cancelled) {
            Ok(normalized) => normalized,
            Err(CANCELLED_SENTINEL) => return Ok(ExportOutcome::Cancelled),
            Err(error) => return Err(error),
        };
        let Some(NormalizedInput {
            body,
            input_bytes,
            records,
        }) = normalized
        else {
            continue;
        };
        total_input_bytes = total_input_bytes
            .checked_add(input_bytes)
            .filter(|size| *size <= MAX_TOTAL_INPUT_BYTES)
            .ok_or(DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
        total_records = total_records
            .checked_add(records)
            .ok_or(DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
        normalized_files.push(NormalizedFile {
            name,
            source,
            body,
            records,
        });
    }

    if normalized_files.is_empty() || total_records == 0 {
        return Err(DIAGNOSTIC_EXPORT_EMPTY_MESSAGE);
    }

    let manifest = build_manifest(&normalized_files, total_records, total_input_bytes)?;
    let mut scan_body = Vec::new();
    let normalized_size = normalized_files
        .iter()
        .map(|file| file.body.len())
        .sum::<usize>()
        .checked_add(manifest.len())
        .ok_or(DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
    scan_body.reserve(normalized_size);
    for file in &normalized_files {
        scan_body.extend_from_slice(&file.body);
    }
    scan_body.extend_from_slice(&manifest);
    if crate::sensitive_scan::contains_sensitive_content(&scan_body) {
        return Err(DIAGNOSTIC_EXPORT_BLOCKED_MESSAGE);
    }
    drop(scan_body);

    if is_cancelled() {
        return Ok(ExportOutcome::Cancelled);
    }

    let temporary = temporary_path(target_parent)?;
    let stream = open_private_temporary(&temporary)?;
    let journal = diagnostics_dir.join(PENDING_EXPORT_FILE);
    let mut guard = TemporaryFileGuard::new(temporary.clone(), journal.clone());
    write_pending_export(&journal, &temporary)?;
    let result = write_zip(stream, &normalized_files, &manifest, &is_cancelled)?;
    if result == ExportOutcome::Cancelled {
        return Ok(result);
    }
    if fs::metadata(&temporary)
        .map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?
        .len()
        > MAX_ZIP_BYTES
    {
        return Err(DIAGNOSTIC_EXPORT_ERROR_MESSAGE);
    }
    prepare_temporary_for_commit(&temporary)?;

    validate_directory(target_parent)?;
    validate_existing_target(target)?;
    if is_cancelled() {
        return Ok(ExportOutcome::Cancelled);
    }
    sync_parent_before_replace(target_parent)?;
    replace_file(&temporary, target)?;
    guard.committed = true;
    let _ = clear_pending_export(&journal);
    sync_parent_after_replace(target_parent);
    Ok(ExportOutcome::Written)
}

pub fn cleanup_pending_export(diagnostics_dir: &Path) -> Result<(), &'static str> {
    let journal = diagnostics_dir.join(PENDING_EXPORT_FILE);
    if !journal.exists() {
        return Ok(());
    }
    let body = match fs::read(&journal) {
        Ok(body) if body.len() <= 4096 => body,
        _ => {
            discard_invalid_journal(&journal);
            return Ok(());
        }
    };
    let pending: PendingExport = match serde_json::from_slice(&body) {
        Ok(pending) => pending,
        Err(_) => {
            discard_invalid_journal(&journal);
            return Ok(());
        }
    };
    if pending.version != PENDING_EXPORT_VERSION || !valid_temporary_path(&pending.temporary) {
        discard_invalid_journal(&journal);
        return Ok(());
    }
    match fs::symlink_metadata(&pending.temporary) {
        Ok(metadata) if metadata_is_link_or_reparse(&metadata) || !metadata.is_file() => {
            discard_invalid_journal(&journal);
            return Ok(());
        }
        Ok(_) => {
            fs::remove_file(&pending.temporary).map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(_) => return Err(DIAGNOSTIC_EXPORT_ERROR_MESSAGE),
    }
    clear_pending_export(&journal)
}

fn write_pending_export(journal: &Path, temporary: &Path) -> Result<(), &'static str> {
    let parent = journal.parent().ok_or(DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
    validate_directory(parent)?;
    let body = serde_json::to_vec(&PendingExport {
        version: PENDING_EXPORT_VERSION,
        temporary: temporary.to_path_buf(),
    })
    .map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
    let staging = parent.join(format!(
        ".pending-diagnostic-export-{}.tmp",
        random_suffix()?
    ));
    let mut stream = open_private_temporary(&staging)?;
    let result = (|| {
        stream
            .write_all(&body)
            .map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
        stream
            .flush()
            .map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
        stream
            .sync_all()
            .map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
        drop(stream);
        fs::rename(&staging, journal).map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(staging);
    }
    result
}

fn clear_pending_export(journal: &Path) -> Result<(), &'static str> {
    match fs::remove_file(journal) {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(_) => Err(DIAGNOSTIC_EXPORT_ERROR_MESSAGE),
    }
}

fn discard_invalid_journal(journal: &Path) {
    let _ = fs::remove_file(journal);
}

fn read_and_normalize(
    path: &Path,
    source: SourceKind,
    is_cancelled: &impl Fn() -> bool,
) -> Result<Option<NormalizedInput>, &'static str> {
    let metadata = match fs::symlink_metadata(path) {
        Ok(metadata) => metadata,
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
        Err(_) => return Err(DIAGNOSTIC_EXPORT_ERROR_MESSAGE),
    };
    if metadata_is_link_or_reparse(&metadata)
        || !metadata.is_file()
        || metadata.len() > MAX_FILE_BYTES
    {
        return Err(DIAGNOSTIC_EXPORT_ERROR_MESSAGE);
    }

    let mut stream = OpenOptions::new()
        .read(true)
        .open(path)
        .map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
    let opened_metadata = stream
        .metadata()
        .map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
    if !opened_metadata.is_file() || opened_metadata.len() > MAX_FILE_BYTES {
        return Err(DIAGNOSTIC_EXPORT_ERROR_MESSAGE);
    }
    let mut input = Vec::with_capacity(opened_metadata.len() as usize);
    Read::by_ref(&mut stream)
        .take(MAX_FILE_BYTES + 1)
        .read_to_end(&mut input)
        .map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
    if input.len() as u64 > MAX_FILE_BYTES {
        return Err(DIAGNOSTIC_EXPORT_ERROR_MESSAGE);
    }
    let final_metadata = fs::symlink_metadata(path).map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
    if metadata_is_link_or_reparse(&final_metadata)
        || !final_metadata.is_file()
        || final_metadata.len() != opened_metadata.len()
        || final_metadata.len() != input.len() as u64
        || (!input.is_empty() && !input.ends_with(b"\n"))
    {
        return Err(DIAGNOSTIC_EXPORT_ERROR_MESSAGE);
    }

    let mut output = Vec::with_capacity(input.len());
    let mut records = 0_usize;
    for raw_line in input.split_inclusive(|byte| *byte == b'\n') {
        if is_cancelled() {
            return Err(CANCELLED_SENTINEL);
        }
        let line = raw_line
            .strip_suffix(b"\n")
            .unwrap_or(raw_line)
            .strip_suffix(b"\r")
            .unwrap_or_else(|| raw_line.strip_suffix(b"\n").unwrap_or(raw_line));
        if line.is_empty() || line.len() > MAX_LINE_BYTES {
            return Err(DIAGNOSTIC_EXPORT_ERROR_MESSAGE);
        }
        let value = match source {
            SourceKind::Host => normalize_host(line)?,
            SourceKind::Runtime => normalize_runtime(line)?,
        };
        serde_json::to_writer(&mut output, &value).map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
        output.push(b'\n');
        records += 1;
    }
    if input.is_empty() {
        return Ok(Some(NormalizedInput {
            body: output,
            input_bytes: 0,
            records: 0,
        }));
    }
    Ok(Some(NormalizedInput {
        body: output,
        input_bytes: input.len() as u64,
        records,
    }))
}

const CANCELLED_SENTINEL: &str = "diagnostic export cancelled";

fn normalize_host(line: &[u8]) -> Result<Value, &'static str> {
    let record: HostRecord =
        serde_json::from_slice(line).map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
    validate_identifier(&record.event, 128, false)?;
    let mut output = Map::new();
    output.insert("timestamp_unix_ms".into(), record.timestamp_unix_ms.into());
    output.insert("event".into(), record.event.into());
    insert_safe_string(&mut output, "component", record.component, 64, false)?;
    insert_safe_string(&mut output, "status", record.status, 64, false)?;
    insert_safe_string(&mut output, "code", record.code, 128, false)?;
    insert_safe_string(
        &mut output,
        "diagnostic_id",
        record.diagnostic_id,
        128,
        false,
    )?;
    insert_safe_string(&mut output, "phase", record.phase, 64, false)?;
    insert_number(&mut output, "duration_ms", record.duration_ms);
    insert_safe_string(&mut output, "plugin_id", record.plugin_id, 64, false)?;
    insert_safe_string(&mut output, "operation", record.operation, 64, false)?;
    Ok(Value::Object(output))
}

fn normalize_runtime(line: &[u8]) -> Result<Value, &'static str> {
    let record: RuntimeRecord =
        serde_json::from_slice(line).map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
    validate_timestamp(&record.timestamp)?;
    validate_identifier(&record.event, 128, false)?;
    if let Some(request_id) = record.request_id.as_deref() {
        validate_identifier(request_id, 256, true)?;
    }
    let mut output = Map::new();
    output.insert("timestamp".into(), record.timestamp.into());
    output.insert("event".into(), record.event.into());
    insert_safe_string(&mut output, "level", record.level, 32, false)?;
    insert_safe_string(&mut output, "component", record.component, 64, false)?;
    insert_safe_string(&mut output, "code", record.code, 128, false)?;
    insert_safe_string(&mut output, "provider_id", record.provider_id, 128, true)?;
    insert_safe_string(&mut output, "model", record.model, 256, true)?;
    insert_safe_string(&mut output, "phase", record.phase, 64, false)?;
    insert_safe_string(&mut output, "status", record.status, 64, false)?;
    insert_safe_string(&mut output, "error_type", record.error_type, 128, false)?;
    insert_number(&mut output, "duration_ms", record.duration_ms);
    insert_number(&mut output, "chunk_count", record.chunk_count);
    insert_number(&mut output, "cancel_latency_ms", record.cancel_latency_ms);
    insert_safe_string(
        &mut output,
        "diagnostic_id",
        record.diagnostic_id,
        128,
        false,
    )?;
    insert_safe_string(&mut output, "plugin_id", record.plugin_id, 64, false)?;
    insert_safe_string(&mut output, "operation", record.operation, 64, false)?;
    Ok(Value::Object(output))
}

fn insert_safe_string(
    output: &mut Map<String, Value>,
    key: &str,
    value: Option<String>,
    limit: usize,
    allow_slash: bool,
) -> Result<(), &'static str> {
    if let Some(value) = value {
        validate_identifier(&value, limit, allow_slash)?;
        output.insert(key.to_string(), Value::String(value));
    }
    Ok(())
}

fn insert_number(output: &mut Map<String, Value>, key: &str, value: Option<u64>) {
    if let Some(value) = value {
        output.insert(key.to_string(), Value::from(value));
    }
}

fn validate_identifier(value: &str, limit: usize, allow_slash: bool) -> Result<(), &'static str> {
    if value.is_empty()
        || value.len() > limit
        || !value.bytes().all(|byte| {
            byte.is_ascii_alphanumeric()
                || matches!(byte, b'-' | b'_' | b'.' | b':' | b'@')
                || (allow_slash && byte == b'/')
        })
    {
        return Err(DIAGNOSTIC_EXPORT_ERROR_MESSAGE);
    }
    Ok(())
}

fn validate_timestamp(value: &str) -> Result<(), &'static str> {
    if value.len() < 20
        || value.len() > 40
        || !value.ends_with('Z')
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || matches!(byte, b'-' | b':' | b'.' | b'T' | b'Z'))
    {
        return Err(DIAGNOSTIC_EXPORT_ERROR_MESSAGE);
    }
    Ok(())
}

fn build_manifest(
    files: &[NormalizedFile],
    total_records: usize,
    total_input_bytes: u64,
) -> Result<Vec<u8>, &'static str> {
    let entries = files
        .iter()
        .map(|file| {
            json!({
                "name": file.name,
                "source": file.source.name(),
                "records": file.records,
                "bytes": file.body.len(),
            })
        })
        .collect::<Vec<_>>();
    let mut body = serde_json::to_vec(&json!({
        "format_version": 1,
        "local_only": true,
        "file_count": files.len(),
        "files": entries,
        "total_input_bytes": total_input_bytes,
        "total_records": total_records,
    }))
    .map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
    body.push(b'\n');
    Ok(body)
}

fn write_zip(
    stream: File,
    files: &[NormalizedFile],
    manifest: &[u8],
    is_cancelled: &impl Fn() -> bool,
) -> Result<ExportOutcome, &'static str> {
    let options = SimpleFileOptions::default()
        .compression_method(CompressionMethod::Stored)
        .unix_permissions(0o600);
    let mut archive = ZipWriter::new(stream);
    for file in files {
        if is_cancelled() {
            return Ok(ExportOutcome::Cancelled);
        }
        archive
            .start_file(file.name, options)
            .map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
        archive
            .write_all(&file.body)
            .map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
    }
    if is_cancelled() {
        return Ok(ExportOutcome::Cancelled);
    }
    archive
        .start_file("manifest.json", options)
        .map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
    archive
        .write_all(manifest)
        .map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
    if is_cancelled() {
        return Ok(ExportOutcome::Cancelled);
    }
    let mut stream = archive
        .finish()
        .map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
    stream
        .flush()
        .map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
    stream
        .sync_all()
        .map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
    Ok(ExportOutcome::Written)
}

fn validate_absolute_local_path(path: &Path) -> Result<(), &'static str> {
    if !path.is_absolute() {
        return Err(DIAGNOSTIC_EXPORT_ERROR_MESSAGE);
    }
    for component in path.components() {
        match component {
            Component::ParentDir | Component::CurDir => {
                return Err(DIAGNOSTIC_EXPORT_ERROR_MESSAGE)
            }
            #[cfg(windows)]
            Component::Prefix(prefix) => {
                use std::path::Prefix;
                if !matches!(prefix.kind(), Prefix::Disk(_)) {
                    return Err(DIAGNOSTIC_EXPORT_ERROR_MESSAGE);
                }
            }
            _ => {}
        }
    }
    Ok(())
}

fn validate_directory(path: &Path) -> Result<(), &'static str> {
    let metadata = fs::symlink_metadata(path).map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
    if !metadata.is_dir() || metadata_is_link_or_reparse(&metadata) {
        return Err(DIAGNOSTIC_EXPORT_ERROR_MESSAGE);
    }
    Ok(())
}

fn validate_existing_target(path: &Path) -> Result<(), &'static str> {
    match fs::symlink_metadata(path) {
        Ok(metadata) => {
            if !metadata.is_file() || metadata_is_link_or_reparse(&metadata) {
                return Err(DIAGNOSTIC_EXPORT_ERROR_MESSAGE);
            }
        }
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => {}
        Err(_) => return Err(DIAGNOSTIC_EXPORT_ERROR_MESSAGE),
    }
    Ok(())
}

fn metadata_is_link_or_reparse(metadata: &fs::Metadata) -> bool {
    if metadata.file_type().is_symlink() {
        return true;
    }
    #[cfg(windows)]
    {
        use std::os::windows::fs::MetadataExt;
        metadata.file_attributes()
            & windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT
            != 0
    }
    #[cfg(not(windows))]
    {
        false
    }
}

fn temporary_path(parent: &Path) -> Result<PathBuf, &'static str> {
    Ok(parent.join(format!(
        ".reflex-diagnostic-export-{}.tmp",
        random_suffix()?
    )))
}

fn random_suffix() -> Result<String, &'static str> {
    let mut random = [0_u8; 16];
    getrandom::fill(&mut random).map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)?;
    Ok(random
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>())
}

fn valid_temporary_path(path: &Path) -> bool {
    let Some(name) = path.file_name().and_then(|value| value.to_str()) else {
        return false;
    };
    let Some(suffix) = name
        .strip_prefix(".reflex-diagnostic-export-")
        .and_then(|value| value.strip_suffix(".tmp"))
    else {
        return false;
    };
    validate_absolute_local_path(path).is_ok()
        && suffix.len() == 32
        && suffix.bytes().all(|byte| byte.is_ascii_hexdigit())
}

fn open_private_temporary(path: &Path) -> Result<File, &'static str> {
    let mut options = OpenOptions::new();
    options.write(true).read(true).create_new(true);
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
    options
        .open(path)
        .map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)
}

#[cfg(windows)]
fn prepare_temporary_for_commit(path: &Path) -> Result<(), &'static str> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::{SetFileAttributesW, FILE_ATTRIBUTE_NORMAL};

    let path = path
        .as_os_str()
        .encode_wide()
        .chain(Some(0))
        .collect::<Vec<_>>();
    if unsafe { SetFileAttributesW(path.as_ptr(), FILE_ATTRIBUTE_NORMAL) } == 0 {
        Err(DIAGNOSTIC_EXPORT_ERROR_MESSAGE)
    } else {
        Ok(())
    }
}

#[cfg(not(windows))]
fn prepare_temporary_for_commit(_path: &Path) -> Result<(), &'static str> {
    Ok(())
}

struct TemporaryFileGuard {
    path: PathBuf,
    journal: PathBuf,
    committed: bool,
}

impl TemporaryFileGuard {
    fn new(path: PathBuf, journal: PathBuf) -> Self {
        Self {
            path,
            journal,
            committed: false,
        }
    }
}

impl Drop for TemporaryFileGuard {
    fn drop(&mut self) {
        if !self.committed {
            let _ = fs::remove_file(&self.path);
            let _ = clear_pending_export(&self.journal);
        }
    }
}

#[cfg(windows)]
fn replace_file(source: &Path, target: &Path) -> Result<(), &'static str> {
    use std::os::windows::ffi::OsStrExt;
    use windows_sys::Win32::Storage::FileSystem::ReplaceFileW;

    if !target.exists() {
        return fs::rename(source, target).map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE);
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
        Err(DIAGNOSTIC_EXPORT_ERROR_MESSAGE)
    } else {
        Ok(())
    }
}

#[cfg(not(windows))]
fn replace_file(source: &Path, target: &Path) -> Result<(), &'static str> {
    fs::rename(source, target).map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)
}

#[cfg(not(windows))]
fn sync_parent_before_replace(parent: &Path) -> Result<(), &'static str> {
    OpenOptions::new()
        .read(true)
        .open(parent)
        .and_then(|stream| stream.sync_all())
        .map_err(|_| DIAGNOSTIC_EXPORT_ERROR_MESSAGE)
}

#[cfg(windows)]
fn sync_parent_before_replace(_parent: &Path) -> Result<(), &'static str> {
    Ok(())
}

#[cfg(not(windows))]
fn sync_parent_after_replace(parent: &Path) {
    let _ = OpenOptions::new()
        .read(true)
        .open(parent)
        .and_then(|stream| stream.sync_all());
}

#[cfg(windows)]
fn sync_parent_after_replace(_parent: &Path) {}

#[cfg(test)]
mod tests {
    use std::io::Read;
    use std::sync::atomic::{AtomicUsize, Ordering};

    use super::*;

    fn test_root(name: &str) -> PathBuf {
        let mut random = [0_u8; 8];
        getrandom::fill(&mut random).unwrap();
        let suffix = random
            .iter()
            .map(|byte| format!("{byte:02x}"))
            .collect::<String>();
        std::env::temp_dir().join(format!("reflex-diagnostic-bundle-{name}-{suffix}"))
    }

    fn setup(name: &str) -> (PathBuf, PathBuf, PathBuf) {
        let root = test_root(name);
        let diagnostics = root.join("diagnostics");
        fs::create_dir_all(&diagnostics).unwrap();
        let target = root.join("diagnostics.zip");
        (root, diagnostics, target)
    }

    fn host_record() -> &'static [u8] {
        br#"{"timestamp_unix_ms":1,"event":"host_started","component":"host","status":"ready"}
"#
    }

    fn runtime_record() -> Vec<u8> {
        format!(
            concat!(
                r#"{{"timestamp":"2026-07-14T00:00:00.000Z","event":"request_completed","request_id":"{}{}","provider_id":"mock","model":"mock-stream","status":"completed","duration_ms":7,"chunk_count":2}}"#,
                "\n"
            ),
            "sk-", "cp-fixtureRequestIdentifier123456"
        )
        .into_bytes()
    }

    fn zip_entry(target: &Path, name: &str) -> Vec<u8> {
        let file = File::open(target).unwrap();
        let mut archive = zip::ZipArchive::new(file).unwrap();
        let mut entry = archive.by_name(name).unwrap();
        let mut body = Vec::new();
        entry.read_to_end(&mut body).unwrap();
        body
    }

    #[test]
    fn exports_fixed_files_manifest_and_removes_request_id() {
        let (root, diagnostics, target) = setup("success");
        fs::write(diagnostics.join("host-diagnostics.jsonl"), host_record()).unwrap();
        fs::write(
            diagnostics.join("runtime-diagnostics.1.jsonl"),
            runtime_record(),
        )
        .unwrap();
        fs::write(diagnostics.join("ignored.jsonl"), b"not-json").unwrap();

        assert_eq!(
            export_diagnostic_bundle(&diagnostics, &target, || false).unwrap(),
            ExportOutcome::Written
        );
        let runtime = zip_entry(&target, "runtime-diagnostics.1.jsonl");
        assert!(!String::from_utf8_lossy(&runtime).contains("request_id"));
        assert!(!String::from_utf8_lossy(&runtime).contains("sk-cp-"));
        assert!(!crate::sensitive_scan::contains_sensitive_content(&runtime));
        let host = zip_entry(&target, "host-diagnostics.jsonl");
        assert!(!crate::sensitive_scan::contains_sensitive_content(&host));
        let manifest: Value = serde_json::from_slice(&zip_entry(&target, "manifest.json")).unwrap();
        assert_eq!(manifest["format_version"], 1);
        assert_eq!(manifest["local_only"], true);
        assert_eq!(manifest["file_count"], 2);
        assert_eq!(manifest["total_records"], 2);
        assert!(manifest["total_input_bytes"].as_u64().unwrap() > 0);
        assert_eq!(manifest["files"].as_array().unwrap().len(), 2);
        assert!(!diagnostics.join(PENDING_EXPORT_FILE).exists());
        assert!(
            !String::from_utf8_lossy(&serde_json::to_vec(&manifest).unwrap())
                .contains(&root.to_string_lossy().to_string())
        );
        assert!(!crate::sensitive_scan::contains_sensitive_content(
            &serde_json::to_vec(&manifest).unwrap()
        ));
        #[cfg(windows)]
        {
            use std::os::windows::fs::MetadataExt;
            use windows_sys::Win32::Storage::FileSystem::{
                FILE_ATTRIBUTE_HIDDEN, FILE_ATTRIBUTE_TEMPORARY,
            };
            let attributes = fs::metadata(&target).unwrap().file_attributes();
            assert_eq!(
                attributes & (FILE_ATTRIBUTE_HIDDEN | FILE_ATTRIBUTE_TEMPORARY),
                0
            );
        }
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn empty_source_fails_without_creating_target() {
        let (root, diagnostics, target) = setup("empty");
        assert_eq!(
            export_diagnostic_bundle(&diagnostics, &target, || false),
            Err(DIAGNOSTIC_EXPORT_EMPTY_MESSAGE)
        );
        assert!(!target.exists());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn sensitive_normalized_content_is_rejected() {
        let (root, diagnostics, target) = setup("sensitive");
        fs::write(
            diagnostics.join("runtime-diagnostics.jsonl"),
            format!(
                concat!(
                    r#"{{"timestamp":"2026-07-14T00:00:00.000Z","event":"request_failed","model":"{}{}","status":"error"}}"#,
                    "\n"
                ),
                "sk-", "abcdefghijklmnopqrstuvwxyz012345"
            ),
        )
        .unwrap();
        assert_eq!(
            export_diagnostic_bundle(&diagnostics, &target, || false),
            Err(DIAGNOSTIC_EXPORT_BLOCKED_MESSAGE)
        );
        assert!(!target.exists());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn unknown_fields_are_rejected_and_old_target_is_preserved() {
        let (root, diagnostics, target) = setup("unknown");
        fs::write(&target, b"old-target").unwrap();
        fs::write(
            diagnostics.join("host-diagnostics.jsonl"),
            br#"{"timestamp_unix_ms":1,"event":"host_started","private_body":"forbidden"}
"#,
        )
        .unwrap();
        assert!(export_diagnostic_bundle(&diagnostics, &target, || false).is_err());
        assert_eq!(fs::read(&target).unwrap(), b"old-target");
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn oversized_file_and_line_are_rejected() {
        for (name, body) in [
            ("file", vec![b'x'; MAX_FILE_BYTES as usize + 1]),
            ("line", vec![b'x'; MAX_LINE_BYTES + 1]),
        ] {
            let (root, diagnostics, target) = setup(name);
            fs::write(diagnostics.join("host-diagnostics.jsonl"), body).unwrap();
            assert!(export_diagnostic_bundle(&diagnostics, &target, || false).is_err());
            assert!(!target.exists());
            let _ = fs::remove_dir_all(root);
        }
    }

    #[test]
    fn cancellation_preserves_old_target_and_cleans_temporary_file() {
        let (root, diagnostics, target) = setup("cancel");
        fs::write(&target, b"old-target").unwrap();
        fs::write(diagnostics.join("host-diagnostics.jsonl"), host_record()).unwrap();
        let checks = AtomicUsize::new(0);
        let outcome = export_diagnostic_bundle(&diagnostics, &target, || {
            checks.fetch_add(1, Ordering::SeqCst) >= 9
        })
        .unwrap();
        assert_eq!(outcome, ExportOutcome::Cancelled);
        assert_eq!(fs::read(&target).unwrap(), b"old-target");
        assert_eq!(
            fs::read_dir(&root)
                .unwrap()
                .filter_map(Result::ok)
                .filter(|entry| entry
                    .file_name()
                    .to_string_lossy()
                    .starts_with(".reflex-diagnostic-export-"))
                .count(),
            0
        );
        assert!(!diagnostics.join(PENDING_EXPORT_FILE).exists());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn startup_cleanup_removes_only_a_valid_recorded_temporary_file() {
        let (root, diagnostics, _target) = setup("startup-cleanup");
        let temporary = root.join(".reflex-diagnostic-export-0123456789abcdef0123456789abcdef.tmp");
        fs::write(&temporary, b"partial-zip").unwrap();
        fs::write(
            diagnostics.join(PENDING_EXPORT_FILE),
            serde_json::to_vec(&PendingExport {
                version: PENDING_EXPORT_VERSION,
                temporary: temporary.clone(),
            })
            .unwrap(),
        )
        .unwrap();

        cleanup_pending_export(&diagnostics).unwrap();

        assert!(!temporary.exists());
        assert!(!diagnostics.join(PENDING_EXPORT_FILE).exists());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn invalid_startup_journal_never_deletes_the_referenced_file() {
        let (root, diagnostics, _target) = setup("invalid-journal");
        let protected = root.join("protected.txt");
        fs::write(&protected, b"keep").unwrap();
        fs::write(
            diagnostics.join(PENDING_EXPORT_FILE),
            serde_json::to_vec(&PendingExport {
                version: PENDING_EXPORT_VERSION,
                temporary: protected.clone(),
            })
            .unwrap(),
        )
        .unwrap();

        cleanup_pending_export(&diagnostics).unwrap();

        assert_eq!(fs::read(&protected).unwrap(), b"keep");
        assert!(!diagnostics.join(PENDING_EXPORT_FILE).exists());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn rejects_relative_parent_traversal_and_non_directory_target_parent() {
        let (root, diagnostics, target) = setup("paths");
        fs::write(diagnostics.join("host-diagnostics.jsonl"), host_record()).unwrap();
        assert!(export_diagnostic_bundle(Path::new("diagnostics"), &target, || false).is_err());
        assert!(
            export_diagnostic_bundle(&diagnostics, Path::new("..\\bundle.zip"), || false).is_err()
        );
        assert!(
            export_diagnostic_bundle(&diagnostics, &root.join("bundle.json"), || false).is_err()
        );
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn rejects_a_valid_json_record_without_a_complete_newline() {
        let (root, diagnostics, target) = setup("partial-line");
        fs::write(
            diagnostics.join("host-diagnostics.jsonl"),
            br#"{"timestamp_unix_ms":1,"event":"host_started"}"#,
        )
        .unwrap();

        assert!(export_diagnostic_bundle(&diagnostics, &target, || false).is_err());
        assert!(!target.exists());
        let _ = fs::remove_dir_all(root);
    }

    #[test]
    fn rejects_source_symlink_when_platform_allows_it() {
        let (root, diagnostics, target) = setup("symlink");
        let real = root.join("real.jsonl");
        fs::write(&real, host_record()).unwrap();
        let link = diagnostics.join("host-diagnostics.jsonl");
        #[cfg(unix)]
        let linked = std::os::unix::fs::symlink(&real, &link).is_ok();
        #[cfg(windows)]
        let linked = std::os::windows::fs::symlink_file(&real, &link).is_ok();
        if linked {
            assert!(export_diagnostic_bundle(&diagnostics, &target, || false).is_err());
            assert!(!target.exists());
        }
        let _ = fs::remove_dir_all(root);
    }
}
