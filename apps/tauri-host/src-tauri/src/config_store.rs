use std::collections::HashSet;
use std::fmt;
use std::fs::{self, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};

pub const CONFIG_FILE_NAME: &str = "config.json";
const CONFIG_BACKUP_FILE_NAME: &str = "config.json.bak";
const CONFIG_TEMP_FILE_NAME: &str = "config.json.tmp";
const CURRENT_CONFIG_VERSION: u32 = 2;
const CONFIG_ERROR_MESSAGE: &str = "配置存储暂不可用。";

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(default)]
pub struct AppConfig {
    pub version: u32,
    pub provider: String,
    pub model: String,
    pub mode: String,
    pub style: String,
    pub scene_policy: String,
    pub clipboard_policy: String,
    pub clipboard_replace_confirmed: bool,
    pub history_enabled: bool,
    pub privacy_mode: bool,
    pub history_redaction: String,
    pub enabled_plugins: Vec<String>,
    pub language: String,
    pub theme: String,
    pub hotkey: String,
    pub tls_verify: bool,
    pub ca_bundle_path: Option<String>,
    #[serde(flatten)]
    pub extensions: Map<String, Value>,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            version: CURRENT_CONFIG_VERSION,
            provider: "minimax".to_string(),
            model: "MiniMax-M2.7-highspeed".to_string(),
            mode: "content".to_string(),
            style: "balanced".to_string(),
            scene_policy: "auto".to_string(),
            clipboard_policy: "manual".to_string(),
            clipboard_replace_confirmed: false,
            history_enabled: false,
            privacy_mode: false,
            history_redaction: "secrets".to_string(),
            enabled_plugins: vec!["translator".to_string(), "markdown-preview".to_string()],
            language: "zh-CN".to_string(),
            theme: "system".to_string(),
            hotkey: "Ctrl+Alt+R".to_string(),
            tls_verify: true,
            ca_bundle_path: None,
            extensions: Map::new(),
        }
    }
}

impl AppConfig {
    pub fn from_value(value: Value) -> Result<Self, ConfigStoreError> {
        let Value::Object(mut object) = value else {
            return Err(ConfigStoreError);
        };
        let source_version = migrate_legacy_fields(&mut object)?;

        let defaults = Self::default();
        let known_fields = known_config_fields();
        let extensions = object
            .iter()
            .filter(|(key, _)| !known_fields.contains(key.as_str()))
            .map(|(key, value)| (key.clone(), value.clone()))
            .collect::<Map<_, _>>();
        validate_extension_keys(&extensions)?;

        let provider = normalized_provider(object.get("provider"), &defaults.provider);
        let model = normalized_bounded_string(object.get("model"), &defaults.model, 128);
        let mode = normalized_choice(object.get("mode"), &defaults.mode, &["content", "prompt"]);
        let style = normalized_choice(
            object.get("style"),
            &defaults.style,
            &["concise", "balanced", "detailed", "creative"],
        );
        let scene_policy = normalized_choice(
            object.get("scene_policy"),
            &defaults.scene_policy,
            &["auto", "manual", "ask"],
        );
        let clipboard_policy = normalized_choice(
            object.get("clipboard_policy"),
            &defaults.clipboard_policy,
            &["startup", "manual", "auto_replace"],
        );
        let language = normalized_choice(
            object.get("language"),
            &defaults.language,
            &["zh-CN", "en-US"],
        );
        let theme = normalized_choice(
            object.get("theme"),
            &defaults.theme,
            &["light", "dark", "system"],
        );
        let hotkey = normalized_bounded_string(object.get("hotkey"), &defaults.hotkey, 128);
        let ca_bundle_path = normalized_optional_string(object.get("ca_bundle_path"), 2048);
        let history_redaction = if source_version == u64::from(CURRENT_CONFIG_VERSION) {
            normalized_choice(
                object.get("history_redaction"),
                &defaults.history_redaction,
                &["secrets", "none"],
            )
        } else {
            defaults.history_redaction.clone()
        };
        let enabled_plugins =
            normalized_plugins(object.get("enabled_plugins"), &defaults.enabled_plugins);

        Ok(Self {
            version: CURRENT_CONFIG_VERSION,
            provider,
            model,
            mode,
            style,
            scene_policy,
            clipboard_policy,
            clipboard_replace_confirmed: object
                .get("clipboard_replace_confirmed")
                .and_then(Value::as_bool)
                .unwrap_or(defaults.clipboard_replace_confirmed),
            history_enabled: source_version == u64::from(CURRENT_CONFIG_VERSION)
                && object
                    .get("history_enabled")
                    .and_then(Value::as_bool)
                    .unwrap_or(defaults.history_enabled),
            privacy_mode: object
                .get("privacy_mode")
                .and_then(Value::as_bool)
                .unwrap_or(defaults.privacy_mode),
            history_redaction,
            enabled_plugins,
            language,
            theme,
            hotkey,
            tls_verify: true,
            ca_bundle_path,
            extensions,
        })
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ConfigStoreError;

impl fmt::Display for ConfigStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(CONFIG_ERROR_MESSAGE)
    }
}

impl std::error::Error for ConfigStoreError {}

pub struct ConfigStore {
    directory: PathBuf,
    write_lock: Mutex<()>,
}

impl ConfigStore {
    pub fn new(directory: PathBuf) -> Self {
        Self {
            directory,
            write_lock: Mutex::new(()),
        }
    }

    pub fn load(&self) -> Result<AppConfig, ConfigStoreError> {
        let primary = self.config_path();
        if primary.exists() {
            if let Ok(config) = read_config_file(&primary) {
                return Ok(config);
            }
        }

        let backup = self.backup_path();
        if backup.exists() {
            if let Ok(config) = read_config_file(&backup) {
                return Ok(config);
            }
        }

        Ok(AppConfig::default())
    }

    pub fn save(&self, config: &AppConfig) -> Result<AppConfig, ConfigStoreError> {
        let _guard = self.write_lock.lock().map_err(|_| ConfigStoreError)?;
        let normalized =
            AppConfig::from_value(serde_json::to_value(config).map_err(|_| ConfigStoreError)?)?;
        fs::create_dir_all(&self.directory).map_err(|_| ConfigStoreError)?;

        let bytes = serde_json::to_vec_pretty(&normalized).map_err(|_| ConfigStoreError)?;
        let temporary = self.directory.join(CONFIG_TEMP_FILE_NAME);
        write_synced_file(&temporary, &bytes)?;
        if let Err(error) =
            replace_primary_file(&temporary, &self.config_path(), &self.backup_path())
        {
            let _ = fs::remove_file(&temporary);
            return Err(error);
        }
        Ok(normalized)
    }

    pub fn backup_path(&self) -> PathBuf {
        self.directory.join(CONFIG_BACKUP_FILE_NAME)
    }

    fn config_path(&self) -> PathBuf {
        self.directory.join(CONFIG_FILE_NAME)
    }
}

fn read_config_file(path: &Path) -> Result<AppConfig, ConfigStoreError> {
    let bytes = fs::read(path).map_err(|_| ConfigStoreError)?;
    let value = serde_json::from_slice(&bytes).map_err(|_| ConfigStoreError)?;
    AppConfig::from_value(value)
}

fn write_synced_file(path: &Path, bytes: &[u8]) -> Result<(), ConfigStoreError> {
    let mut file = OpenOptions::new()
        .create(true)
        .truncate(true)
        .write(true)
        .open(path)
        .map_err(|_| ConfigStoreError)?;
    file.write_all(bytes).map_err(|_| ConfigStoreError)?;
    file.sync_all().map_err(|_| ConfigStoreError)
}

#[cfg(windows)]
fn replace_primary_file(
    temporary: &Path,
    primary: &Path,
    backup: &Path,
) -> Result<(), ConfigStoreError> {
    use std::os::windows::ffi::OsStrExt;

    use windows_sys::Win32::Storage::FileSystem::{
        MoveFileExW, ReplaceFileW, MOVEFILE_REPLACE_EXISTING, MOVEFILE_WRITE_THROUGH,
        REPLACEFILE_WRITE_THROUGH,
    };

    fn wide(path: &Path) -> Vec<u16> {
        path.as_os_str().encode_wide().chain(Some(0)).collect()
    }

    let primary_exists = primary.exists();
    let temporary = wide(temporary);
    let primary = wide(primary);
    let result = if primary_exists {
        let _ = fs::remove_file(backup);
        let backup = wide(backup);
        unsafe {
            ReplaceFileW(
                primary.as_ptr(),
                temporary.as_ptr(),
                backup.as_ptr(),
                REPLACEFILE_WRITE_THROUGH,
                std::ptr::null_mut(),
                std::ptr::null_mut(),
            )
        }
    } else {
        unsafe {
            MoveFileExW(
                temporary.as_ptr(),
                primary.as_ptr(),
                MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH,
            )
        }
    };

    if result == 0 {
        Err(ConfigStoreError)
    } else {
        Ok(())
    }
}

#[cfg(not(windows))]
fn replace_primary_file(
    temporary: &Path,
    primary: &Path,
    backup: &Path,
) -> Result<(), ConfigStoreError> {
    if primary.exists() {
        fs::copy(primary, backup).map_err(|_| ConfigStoreError)?;
    }
    fs::rename(temporary, primary).map_err(|_| ConfigStoreError)
}

fn migrate_legacy_fields(object: &mut Map<String, Value>) -> Result<u64, ConfigStoreError> {
    let version = object.get("version").and_then(Value::as_u64).unwrap_or(0);
    if version > u64::from(CURRENT_CONFIG_VERSION) {
        return Err(ConfigStoreError);
    }
    if version == 0 {
        for (old, current) in [
            ("default_provider", "provider"),
            ("default_model", "model"),
            ("default_mode", "mode"),
            ("default_style", "style"),
        ] {
            if !object.contains_key(current) {
                if let Some(value) = object.get(old).cloned() {
                    object.insert(current.to_string(), value);
                }
            }
            object.remove(old);
        }
    }
    object.insert("version".to_string(), Value::from(CURRENT_CONFIG_VERSION));
    Ok(version)
}

fn known_config_fields() -> HashSet<&'static str> {
    [
        "version",
        "provider",
        "model",
        "mode",
        "style",
        "scene_policy",
        "clipboard_policy",
        "clipboard_replace_confirmed",
        "history_enabled",
        "privacy_mode",
        "history_redaction",
        "enabled_plugins",
        "language",
        "theme",
        "hotkey",
        "tls_verify",
        "ca_bundle_path",
    ]
    .into_iter()
    .collect()
}

fn validate_extension_keys(extensions: &Map<String, Value>) -> Result<(), ConfigStoreError> {
    if extensions
        .iter()
        .any(|(key, value)| is_secret_like_key(key) || contains_secret_like_extension_field(value))
    {
        Err(ConfigStoreError)
    } else {
        Ok(())
    }
}

fn contains_secret_like_extension_field(value: &Value) -> bool {
    match value {
        Value::Array(values) => values.iter().any(contains_secret_like_extension_field),
        Value::Object(values) => values.iter().any(|(key, value)| {
            is_secret_like_key(key) || contains_secret_like_extension_field(value)
        }),
        _ => false,
    }
}

fn is_secret_like_key(key: &str) -> bool {
    let normalized = key.to_ascii_lowercase().replace('-', "_");
    [
        "api_key",
        "apikey",
        "token",
        "secret",
        "authorization",
        "password",
    ]
    .iter()
    .any(|part| normalized.contains(part))
}

fn normalized_provider(value: Option<&Value>, fallback: &str) -> String {
    let Some(value) = value.and_then(Value::as_str).map(str::trim) else {
        return fallback.to_string();
    };
    if value.is_empty()
        || value.len() > 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
    {
        fallback.to_string()
    } else {
        value.to_ascii_lowercase()
    }
}

fn normalized_choice(value: Option<&Value>, fallback: &str, allowed: &[&str]) -> String {
    let Some(value) = value.and_then(Value::as_str).map(str::trim) else {
        return fallback.to_string();
    };
    allowed
        .iter()
        .find(|candidate| **candidate == value)
        .map(|value| (*value).to_string())
        .unwrap_or_else(|| fallback.to_string())
}

fn normalized_plugins(value: Option<&Value>, fallback: &[String]) -> Vec<String> {
    let Some(values) = value.and_then(Value::as_array) else {
        return fallback.to_vec();
    };
    ["translator", "markdown-preview", "batch-runner", "semantic-detector"]
        .into_iter()
        .filter(|allowed| values.iter().any(|value| value.as_str() == Some(*allowed)))
        .map(str::to_string)
        .collect()
}

fn normalized_bounded_string(value: Option<&Value>, fallback: &str, max_len: usize) -> String {
    let Some(value) = value.and_then(Value::as_str).map(str::trim) else {
        return fallback.to_string();
    };
    if value.is_empty() || value.len() > max_len {
        fallback.to_string()
    } else {
        value.to_string()
    }
}

fn normalized_optional_string(value: Option<&Value>, max_len: usize) -> Option<String> {
    let value = value.and_then(Value::as_str)?.trim();
    if value.is_empty() || value.len() > max_len {
        None
    } else {
        Some(value.to_string())
    }
}

#[cfg(test)]
mod tests {
    use std::fs;
    use std::path::{Path, PathBuf};
    use std::sync::atomic::{AtomicU64, Ordering};

    use serde_json::json;

    use super::{AppConfig, ConfigStore, CONFIG_FILE_NAME};

    static NEXT_TEST_DIRECTORY: AtomicU64 = AtomicU64::new(0);

    struct TestDirectory(PathBuf);

    impl TestDirectory {
        fn new() -> Self {
            let suffix = NEXT_TEST_DIRECTORY.fetch_add(1, Ordering::Relaxed);
            let path = std::env::temp_dir().join(format!(
                "reflex-next-config-store-{}-{suffix}",
                std::process::id()
            ));
            let _ = fs::remove_dir_all(&path);
            fs::create_dir_all(&path).unwrap();
            Self(path)
        }

        fn path(&self) -> &Path {
            &self.0
        }
    }

    impl Drop for TestDirectory {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn defaults_are_safe_and_match_the_stage_a_contract() {
        let config = AppConfig::default();

        assert_eq!(config.version, 2);
        assert_eq!(config.provider, "minimax");
        assert_eq!(config.model, "MiniMax-M2.7-highspeed");
        assert_eq!(config.mode, "content");
        assert_eq!(config.style, "balanced");
        assert_eq!(config.scene_policy, "auto");
        assert_eq!(config.clipboard_policy, "manual");
        assert!(!config.clipboard_replace_confirmed);
        assert!(!config.history_enabled);
        assert!(!config.privacy_mode);
        assert_eq!(config.history_redaction, "secrets");
        assert_eq!(config.enabled_plugins, ["translator", "markdown-preview"]);
        assert_eq!(config.language, "zh-CN");
        assert_eq!(config.theme, "system");
        assert!(config.tls_verify);
        assert!(config.ca_bundle_path.is_none());
    }

    #[test]
    fn invalid_values_fall_back_without_dropping_unknown_fields() {
        let config = AppConfig::from_value(json!({
            "version": 2,
            "provider": "../minimax",
            "model": "",
            "mode": "unsafe",
            "style": "verbose",
            "scene_policy": "guess",
            "clipboard_policy": "always",
            "history_redaction": "raw",
            "enabled_plugins": ["translator", "history-sqlite", "../unsafe"],
            "language": "fr-FR",
            "theme": "purple",
            "tls_verify": false,
            "ca_bundle_path": "  C:\\certs\\root.pem  ",
            "future_flag": true
        }))
        .unwrap();

        assert_eq!(config.provider, "minimax");
        assert_eq!(config.model, "MiniMax-M2.7-highspeed");
        assert_eq!(config.mode, "content");
        assert_eq!(config.style, "balanced");
        assert_eq!(config.scene_policy, "auto");
        assert_eq!(config.clipboard_policy, "manual");
        assert_eq!(config.history_redaction, "secrets");
        assert_eq!(config.enabled_plugins, ["translator"]);
        assert_eq!(config.language, "zh-CN");
        assert_eq!(config.theme, "system");
        assert!(config.tls_verify);
        assert_eq!(
            config.ca_bundle_path.as_deref(),
            Some("C:\\certs\\root.pem")
        );
        assert_eq!(config.extensions.get("future_flag"), Some(&json!(true)));
    }

    #[test]
    fn migrates_version_zero_default_fields_to_the_current_shape() {
        let config = AppConfig::from_value(json!({
            "version": 0,
            "default_provider": "MiniMax",
            "default_model": "legacy-model",
            "default_mode": "prompt",
            "default_style": "creative"
        }))
        .unwrap();

        assert_eq!(config.version, 2);
        assert_eq!(config.provider, "minimax");
        assert_eq!(config.model, "legacy-model");
        assert_eq!(config.mode, "prompt");
        assert_eq!(config.style, "creative");
        assert!(!config.history_enabled);
        assert_eq!(config.history_redaction, "secrets");
        assert_eq!(config.enabled_plugins, ["translator", "markdown-preview"]);
        assert!(!config.extensions.contains_key("default_provider"));
    }

    #[test]
    fn version_one_migration_forces_history_off_even_when_legacy_value_was_true() {
        let config = AppConfig::from_value(json!({
            "version": 1,
            "history_enabled": true,
            "privacy_mode": true,
            "history_redaction": "none"
        }))
        .unwrap();

        assert_eq!(config.version, 2);
        assert!(!config.history_enabled);
        assert!(config.privacy_mode);
        assert_eq!(config.history_redaction, "secrets");
    }

    #[test]
    fn version_two_preserves_explicit_history_policy_and_valid_plugins() {
        let config = AppConfig::from_value(json!({
            "version": 2,
            "history_enabled": true,
            "privacy_mode": true,
            "history_redaction": "none",
            "enabled_plugins": ["semantic-detector", "markdown-preview", "translator", "translator"]
        }))
        .unwrap();

        assert!(config.history_enabled);
        assert!(config.privacy_mode);
        assert_eq!(config.history_redaction, "none");
        assert_eq!(
            config.enabled_plugins,
            ["translator", "markdown-preview", "semantic-detector"]
        );
    }

    #[test]
    fn preserves_a_valid_clipboard_replacement_confirmation() {
        let config = AppConfig::from_value(json!({
            "version": 1,
            "clipboard_replace_confirmed": true
        }))
        .unwrap();

        assert!(config.clipboard_replace_confirmed);
    }

    #[test]
    fn save_replaces_primary_and_recovers_from_the_previous_valid_backup() {
        let directory = TestDirectory::new();
        let store = ConfigStore::new(directory.path().to_path_buf());
        store.save(&AppConfig::default()).unwrap();

        let mut changed = AppConfig::default();
        changed.style = "concise".to_string();
        store.save(&changed).unwrap();

        assert_eq!(store.load().unwrap().style, "concise");
        assert!(store.backup_path().is_file());

        fs::write(directory.path().join(CONFIG_FILE_NAME), b"{not-json").unwrap();
        assert_eq!(store.load().unwrap().style, "balanced");
    }

    #[test]
    fn refuses_secret_like_extension_fields_without_writing_a_file() {
        let directory = TestDirectory::new();
        let store = ConfigStore::new(directory.path().to_path_buf());
        let mut config = AppConfig::default();
        config
            .extensions
            .insert("api_key".to_string(), json!("fixture-value"));

        assert!(store.save(&config).is_err());
        assert!(!directory.path().join(CONFIG_FILE_NAME).exists());
    }

    #[test]
    fn refuses_nested_secret_like_extension_fields() {
        let config = AppConfig::from_value(json!({
            "version": 2,
            "future_provider": {
                "credentials": {
                    "token": "history-fixture-key"
                }
            }
        }));

        assert!(config.is_err());
    }
}
