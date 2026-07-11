use std::collections::BTreeMap;
use std::fmt;
use std::path::{Component, Path};
use std::sync::atomic::{AtomicU64, Ordering};

use serde_json::Value;

pub const COMMAND_INVALID_MESSAGE: &str = "运行请求无效。";
static PRIVATE_REQUEST_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CommandKind {
    Optimize,
    Cancel,
    Ping,
    Shutdown,
    ConfigureProvider,
    ListPlugins,
    PluginCall,
    ConfigurePlugin,
    ConfigureHistoryKeys,
    ConfigureHistoryPolicy,
    ConfigureHistoryPath,
    PluginAdminCall,
}

impl CommandKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Optimize => "optimize",
            Self::Cancel => "cancel",
            Self::Ping => "ping",
            Self::Shutdown => "shutdown",
            Self::ConfigureProvider => "configure_provider",
            Self::ListPlugins => "list_plugins",
            Self::PluginCall => "plugin_call",
            Self::ConfigurePlugin => "configure_plugin",
            Self::ConfigureHistoryKeys => "configure_history_keys",
            Self::ConfigureHistoryPolicy => "configure_history_policy",
            Self::ConfigureHistoryPath => "configure_history_path",
            Self::PluginAdminCall => "plugin_admin_call",
        }
    }

    fn from_str(value: &str) -> Option<Self> {
        match value {
            "optimize" => Some(Self::Optimize),
            "cancel" => Some(Self::Cancel),
            "ping" => Some(Self::Ping),
            "shutdown" => Some(Self::Shutdown),
            "configure_provider" => Some(Self::ConfigureProvider),
            "list_plugins" => Some(Self::ListPlugins),
            "plugin_call" => Some(Self::PluginCall),
            "configure_plugin" => Some(Self::ConfigurePlugin),
            "configure_history_keys" => Some(Self::ConfigureHistoryKeys),
            "configure_history_policy" => Some(Self::ConfigureHistoryPolicy),
            "configure_history_path" => Some(Self::ConfigureHistoryPath),
            "plugin_admin_call" => Some(Self::PluginAdminCall),
            _ => None,
        }
    }
}

#[derive(Clone, PartialEq)]
pub struct ValidatedCommand {
    pub request_id: String,
    pub kind: CommandKind,
    pub payload: Value,
}

impl fmt::Debug for ValidatedCommand {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ValidatedCommand")
            .field("request_id", &self.request_id)
            .field("kind", &self.kind)
            .field("payload", &"[REDACTED]")
            .finish()
    }
}

pub(crate) fn configure_provider_command(
    provider_id: &str,
    secret: &str,
    config: Value,
) -> Result<ValidatedCommand, &'static str> {
    let provider_id = provider_id.trim().to_ascii_lowercase();
    if provider_id.is_empty()
        || provider_id.len() > 64
        || !provider_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
        || secret.trim().is_empty()
        || secret.len() > 16_384
        || !config.is_object()
    {
        return Err(COMMAND_INVALID_MESSAGE);
    }
    Ok(ValidatedCommand {
        request_id: format!(
            "host-config-{provider_id}-{}",
            PRIVATE_REQUEST_SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ),
        kind: CommandKind::ConfigureProvider,
        payload: serde_json::json!({
            "provider_id": provider_id,
            "secret": secret,
            "config": config,
        }),
    })
}

#[cfg(test)]
pub(crate) fn configure_history_keys_command(
    keys: BTreeMap<String, String>,
) -> Result<ValidatedCommand, &'static str> {
    let payload = serde_json::json!({ "keys": keys });
    if !validate_payload(CommandKind::ConfigureHistoryKeys, &payload) {
        return Err(COMMAND_INVALID_MESSAGE);
    }
    Ok(ValidatedCommand {
        request_id: format!(
            "host-history-keys-{}",
            PRIVATE_REQUEST_SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ),
        kind: CommandKind::ConfigureHistoryKeys,
        payload,
    })
}

pub(crate) fn configure_history_keyring_command(
    keys: BTreeMap<String, String>,
    active_version: Option<u32>,
    pending_version: Option<u32>,
) -> Result<ValidatedCommand, &'static str> {
    let payload = serde_json::json!({
        "keys": keys,
        "active_version": active_version.map(|version| format!("v{version}")),
        "pending_version": pending_version.map(|version| format!("v{version}")),
    });
    if !validate_payload(CommandKind::ConfigureHistoryKeys, &payload) {
        return Err(COMMAND_INVALID_MESSAGE);
    }
    Ok(ValidatedCommand {
        request_id: format!(
            "host-history-keyring-{}",
            PRIVATE_REQUEST_SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ),
        kind: CommandKind::ConfigureHistoryKeys,
        payload,
    })
}

pub(crate) fn plugin_admin_command(
    plugin_id: &str,
    operation: &str,
    input: Value,
) -> Result<ValidatedCommand, &'static str> {
    let payload = serde_json::json!({
        "plugin_id": plugin_id,
        "operation": operation,
        "input": input,
    });
    if !validate_payload(CommandKind::PluginAdminCall, &payload) {
        return Err(COMMAND_INVALID_MESSAGE);
    }
    Ok(ValidatedCommand {
        request_id: format!(
            "host-admin-{operation}-{}",
            PRIVATE_REQUEST_SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ),
        kind: CommandKind::PluginAdminCall,
        payload,
    })
}

pub(crate) fn configure_plugin_command(
    plugin_id: &str,
    enabled: bool,
) -> Result<ValidatedCommand, &'static str> {
    let payload = serde_json::json!({
        "plugin_id": plugin_id,
        "enabled": enabled,
    });
    if !validate_payload(CommandKind::ConfigurePlugin, &payload) {
        return Err(COMMAND_INVALID_MESSAGE);
    }
    Ok(ValidatedCommand {
        request_id: format!(
            "host-plugin-{plugin_id}-{}",
            PRIVATE_REQUEST_SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ),
        kind: CommandKind::ConfigurePlugin,
        payload,
    })
}

pub(crate) fn configure_history_policy_command(
    history_enabled: bool,
    privacy_mode: bool,
    history_redaction: &str,
) -> Result<ValidatedCommand, &'static str> {
    let payload = serde_json::json!({
        "history_enabled": history_enabled,
        "privacy_mode": privacy_mode,
        "history_redaction": history_redaction,
    });
    if !validate_payload(CommandKind::ConfigureHistoryPolicy, &payload) {
        return Err(COMMAND_INVALID_MESSAGE);
    }
    Ok(ValidatedCommand {
        request_id: format!(
            "host-history-policy-{}",
            PRIVATE_REQUEST_SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ),
        kind: CommandKind::ConfigureHistoryPolicy,
        payload,
    })
}

pub(crate) fn configure_history_path_command(
    database_path: &Path,
) -> Result<ValidatedCommand, &'static str> {
    let Some(database_path) = database_path.to_str() else {
        return Err(COMMAND_INVALID_MESSAGE);
    };
    if !is_history_database_path(database_path) {
        return Err(COMMAND_INVALID_MESSAGE);
    }
    let payload = serde_json::json!({ "database_path": database_path });
    if !validate_payload(CommandKind::ConfigureHistoryPath, &payload) {
        return Err(COMMAND_INVALID_MESSAGE);
    }
    Ok(ValidatedCommand {
        request_id: format!(
            "host-history-path-{}",
            PRIVATE_REQUEST_SEQUENCE.fetch_add(1, Ordering::Relaxed)
        ),
        kind: CommandKind::ConfigureHistoryPath,
        payload,
    })
}

pub(crate) fn validate_command(
    command: Value,
    expected_kind: CommandKind,
) -> Result<ValidatedCommand, &'static str> {
    let Value::Object(command) = command else {
        return Err(COMMAND_INVALID_MESSAGE);
    };
    if command.len() != 4
        || !["version", "request_id", "type", "payload"]
            .iter()
            .all(|field| command.contains_key(*field))
    {
        return Err(COMMAND_INVALID_MESSAGE);
    }
    let request_id = command
        .get("request_id")
        .and_then(Value::as_str)
        .filter(|value| is_safe_request_id(value))
        .ok_or(COMMAND_INVALID_MESSAGE)?;
    let kind = command
        .get("type")
        .and_then(Value::as_str)
        .and_then(CommandKind::from_str)
        .filter(|kind| *kind == expected_kind)
        .ok_or(COMMAND_INVALID_MESSAGE)?;
    let is_current_version = command.get("version").and_then(Value::as_u64) == Some(1);
    let payload = command
        .get("payload")
        .filter(|value| value.is_object())
        .cloned()
        .ok_or(COMMAND_INVALID_MESSAGE)?;

    if !is_current_version || kind != expected_kind || !validate_payload(expected_kind, &payload) {
        return Err(COMMAND_INVALID_MESSAGE);
    }

    Ok(ValidatedCommand {
        request_id: request_id.to_string(),
        kind: expected_kind,
        payload,
    })
}

fn validate_payload(kind: CommandKind, payload: &Value) -> bool {
    let Some(payload) = payload.as_object() else {
        return false;
    };
    match kind {
        CommandKind::Cancel
        | CommandKind::Ping
        | CommandKind::Shutdown
        | CommandKind::ListPlugins => payload.is_empty(),
        CommandKind::Optimize => {
            const FIELDS: &[&str] = &[
                "text",
                "mode",
                "style",
                "scene",
                "scene_policy",
                "provider",
                "model",
                "stream",
                "metadata",
            ];
            payload.get("text").is_some_and(Value::is_string)
                && payload.keys().all(|field| FIELDS.contains(&field.as_str()))
        }
        CommandKind::ConfigureProvider => {
            has_exact_fields(payload, &["provider_id", "secret", "config"])
                && payload
                    .get("provider_id")
                    .is_some_and(|value| value.as_str().is_some_and(is_safe_dotted_id))
                && payload.get("secret").is_some_and(|value| {
                    value
                        .as_str()
                        .is_some_and(|secret| !secret.trim().is_empty() && secret.len() <= 16_384)
                })
                && payload.get("config").is_some_and(Value::is_object)
        }
        CommandKind::PluginCall | CommandKind::PluginAdminCall => {
            validate_plugin_call(payload, kind == CommandKind::PluginCall)
        }
        CommandKind::ConfigurePlugin => {
            has_exact_fields(payload, &["plugin_id", "enabled"])
                && matches!(
                    payload.get("plugin_id").and_then(Value::as_str),
                    Some("translator" | "markdown-preview")
                )
                && payload.get("enabled").is_some_and(Value::is_boolean)
        }
        CommandKind::ConfigureHistoryKeys => {
            let fields_valid = has_exact_fields(payload, &["keys"])
                || has_exact_fields(payload, &["keys", "active_version", "pending_version"]);
            let keys_valid = payload
                .get("keys")
                .and_then(Value::as_object)
                .is_some_and(|keys| {
                    keys.iter().all(|(key_id, secret)| {
                        is_safe_key_version(key_id)
                            && secret.as_str().is_some_and(is_canonical_history_key)
                    })
                });
            if !fields_valid || !keys_valid {
                return false;
            }
            if !payload.contains_key("active_version") {
                return true;
            }
            let keys = payload.get("keys").and_then(Value::as_object).unwrap();
            let active = payload.get("active_version").and_then(Value::as_str);
            let pending = payload.get("pending_version").and_then(Value::as_str);
            let active_valid = active
                .is_none_or(|version| is_safe_key_version(version) && keys.contains_key(version));
            let pending_valid = pending.is_none_or(|version| {
                is_safe_key_version(version)
                    && keys.contains_key(version)
                    && active.is_some_and(|active| {
                        version[1..].parse::<u32>().ok() > active[1..].parse::<u32>().ok()
                    })
            });
            active_valid && pending_valid
        }
        CommandKind::ConfigureHistoryPolicy => {
            has_exact_fields(
                payload,
                &["history_enabled", "privacy_mode", "history_redaction"],
            ) && payload
                .get("history_enabled")
                .is_some_and(Value::is_boolean)
                && payload.get("privacy_mode").is_some_and(Value::is_boolean)
                && matches!(
                    payload.get("history_redaction").and_then(Value::as_str),
                    Some("secrets" | "none")
                )
        }
        CommandKind::ConfigureHistoryPath => {
            has_exact_fields(payload, &["database_path"])
                && payload
                    .get("database_path")
                    .and_then(Value::as_str)
                    .is_some_and(is_history_database_path)
        }
    }
}

fn validate_plugin_call(payload: &serde_json::Map<String, Value>, public: bool) -> bool {
    if !has_exact_fields(payload, &["plugin_id", "operation", "input"]) {
        return false;
    }
    let Some(plugin_id) = payload.get("plugin_id").and_then(Value::as_str) else {
        return false;
    };
    let Some(operation) = payload.get("operation").and_then(Value::as_str) else {
        return false;
    };
    let Some(input) = payload.get("input").and_then(Value::as_object) else {
        return false;
    };
    if !is_safe_id(plugin_id) || !is_safe_id(operation) {
        return false;
    }
    let allowed = if public {
        matches!(
            (plugin_id, operation),
            (
                "history-sqlite",
                "list" | "detail" | "rate" | "backups" | "scan"
            ) | ("translator", "translate")
                | ("markdown-preview", "preview")
        )
    } else {
        matches!(
            (plugin_id, operation),
            (
                "history-sqlite",
                "delete" | "clear" | "export" | "repair" | "restore" | "rotate"
            ) | ("markdown-preview", "export")
        )
    };
    allowed && (!public || !contains_private_field(&Value::Object(input.clone())))
}

fn has_exact_fields(payload: &serde_json::Map<String, Value>, fields: &[&str]) -> bool {
    payload.len() == fields.len() && fields.iter().all(|field| payload.contains_key(*field))
}

fn is_history_database_path(value: &str) -> bool {
    let path = Path::new(value);
    path.is_absolute()
        && path.file_name().and_then(|name| name.to_str()) == Some("history.sqlite3")
        && path
            .parent()
            .and_then(Path::file_name)
            .and_then(|name| name.to_str())
            == Some("history")
        && path
            .components()
            .all(|component| !matches!(component, Component::CurDir | Component::ParentDir))
}

fn contains_private_field(value: &Value) -> bool {
    match value {
        Value::Array(values) => values.iter().any(contains_private_field),
        Value::Object(values) => values.iter().any(|(field, value)| {
            let field = field.trim().to_ascii_lowercase();
            matches!(
                field.as_str(),
                "key" | "keys" | "path" | "admin" | "private" | "secret" | "token"
            ) || field.starts_with("admin_")
                || field.starts_with("private_")
                || field.starts_with("secret_")
                || field.starts_with("token_")
                || field.ends_with("_key")
                || field.ends_with("_keys")
                || field.ends_with("_path")
                || field.ends_with("_secret")
                || field.ends_with("_token")
                || contains_private_field(value)
        }),
        _ => false,
    }
}

pub(crate) fn is_safe_request_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 128
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b':'))
}

pub(crate) fn is_safe_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value.as_bytes()[0].is_ascii_lowercase()
        && value.bytes().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || matches!(byte, b'-' | b'_')
        })
}

fn is_safe_dotted_id(value: &str) -> bool {
    !value.is_empty()
        && value.len() <= 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.'))
}

fn is_safe_key_version(value: &str) -> bool {
    let Some(version) = value.strip_prefix('v') else {
        return false;
    };
    let Ok(version_number) = version.parse::<u32>() else {
        return false;
    };
    version_number > 0 && version_number <= 1_000_000 && version == version_number.to_string()
}

fn is_canonical_history_key(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || matches!(byte, b'a'..=b'f'))
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeMap;

    use serde_json::json;

    use super::{
        configure_history_keys_command, configure_history_policy_command,
        configure_provider_command, validate_command, CommandKind, ValidatedCommand,
        COMMAND_INVALID_MESSAGE,
    };

    #[test]
    fn accepts_only_the_expected_complete_command_envelope() {
        let command = json!({
            "version": 1,
            "request_id": "req-1",
            "type": "optimize",
            "payload": { "text": "保留原始请求标识" }
        });

        let validated = validate_command(command, CommandKind::Optimize).unwrap();

        assert_eq!(validated.request_id, "req-1");
        assert_eq!(validated.kind, CommandKind::Optimize);
        assert_eq!(validated.payload, json!({ "text": "保留原始请求标识" }));
    }

    #[test]
    fn rejects_version_request_id_type_and_non_object_payload_with_one_safe_message() {
        let invalid_commands = [
            json!({ "version": 2, "request_id": "req-1", "type": "optimize", "payload": {} }),
            json!({ "version": 1, "request_id": "", "type": "optimize", "payload": {} }),
            json!({ "version": 1, "request_id": "req-1", "type": "cancel", "payload": {} }),
            json!({ "version": 1, "request_id": "req-1", "type": "optimize", "payload": [] }),
        ];

        for command in invalid_commands {
            assert_eq!(
                validate_command(command, CommandKind::Optimize),
                Err(COMMAND_INVALID_MESSAGE)
            );
        }
    }

    #[test]
    fn builds_a_private_provider_configuration_command_without_debug_secret_leakage() {
        let secret = "fixture-rust-private-credential";

        let command = configure_provider_command(
            "minimax",
            secret,
            json!({ "model": "MiniMax-M2.7-highspeed", "tls_verify": true }),
        )
        .unwrap();

        assert!(command.request_id.starts_with("host-config-minimax-"));
        assert_eq!(command.kind, CommandKind::ConfigureProvider);
        assert_eq!(command.payload["provider_id"], "minimax");
        assert_eq!(command.payload["secret"], secret);
        assert!(!format!("{command:?}").contains(secret));
    }

    #[test]
    fn builds_strict_private_history_commands_without_debug_secret_leakage() {
        let first_key = "11".repeat(32);
        let second_key = "22".repeat(32);
        let mut keys = BTreeMap::new();
        keys.insert("v1".to_string(), first_key.clone());
        keys.insert("v2".to_string(), second_key);

        let key_command = configure_history_keys_command(keys.clone()).unwrap();
        let policy_command = configure_history_policy_command(true, false, "secrets").unwrap();

        assert_eq!(key_command.kind, CommandKind::ConfigureHistoryKeys);
        assert_eq!(key_command.payload["keys"]["v1"], first_key);
        assert_eq!(policy_command.kind, CommandKind::ConfigureHistoryPolicy);
        assert_eq!(
            policy_command.payload,
            json!({
                "history_enabled": true,
                "privacy_mode": false,
                "history_redaction": "secrets"
            })
        );
        assert!(!format!("{key_command:?}").contains(&first_key));
        assert!(!format!("{policy_command:?}").contains(&first_key));
    }

    #[test]
    fn builds_private_fixed_history_path_without_debug_leakage_or_io() {
        let root = std::env::temp_dir().join(format!(
            "reflex-next-history-path-builder-{}",
            std::process::id()
        ));
        let path = root.join("history").join("history.sqlite3");

        let command = super::configure_history_path_command(&path).unwrap();

        assert_eq!(command.kind, CommandKind::ConfigureHistoryPath);
        assert_eq!(
            command.payload["database_path"],
            path.to_string_lossy().as_ref()
        );
        assert!(!format!("{command:?}").contains(path.to_string_lossy().as_ref()));
        assert!(!root.exists());
    }

    #[test]
    fn history_path_builder_rejects_relative_or_noncanonical_paths() {
        for path in [
            std::path::Path::new("history/history.sqlite3"),
            std::path::Path::new("D:/app-data/history.sqlite3"),
            std::path::Path::new("D:/app-data/other/history.sqlite3"),
            std::path::Path::new("D:/app-data/history/other.sqlite3"),
        ] {
            assert!(super::configure_history_path_command(path).is_err());
        }
    }

    #[test]
    fn private_history_command_builders_reject_unsafe_payload_values() {
        let mut invalid_keys = BTreeMap::new();
        invalid_keys.insert("v0".to_string(), "11".repeat(32));
        assert!(configure_history_keys_command(invalid_keys).is_err());
        for invalid_value in [
            "history-fixture-key".to_string(),
            String::new(),
            "1".repeat(63),
            "1".repeat(65),
            "g".repeat(64),
            "AA".repeat(32),
        ] {
            let mut invalid_keys = BTreeMap::new();
            invalid_keys.insert("v1".to_string(), invalid_value);
            assert!(configure_history_keys_command(invalid_keys).is_err());
        }
        assert!(configure_history_policy_command(true, false, "raw").is_err());
    }

    #[test]
    fn supports_the_complete_runtime_command_kind_contract() {
        let kinds = [
            (CommandKind::Optimize, "optimize"),
            (CommandKind::Cancel, "cancel"),
            (CommandKind::Ping, "ping"),
            (CommandKind::Shutdown, "shutdown"),
            (CommandKind::ConfigureProvider, "configure_provider"),
            (CommandKind::ListPlugins, "list_plugins"),
            (CommandKind::PluginCall, "plugin_call"),
            (CommandKind::ConfigurePlugin, "configure_plugin"),
            (CommandKind::ConfigureHistoryKeys, "configure_history_keys"),
            (
                CommandKind::ConfigureHistoryPolicy,
                "configure_history_policy",
            ),
            (CommandKind::ConfigureHistoryPath, "configure_history_path"),
            (CommandKind::PluginAdminCall, "plugin_admin_call"),
        ];

        for (kind, wire_name) in kinds {
            assert_eq!(kind.as_str(), wire_name);
        }
    }

    #[test]
    fn accepts_ping_and_shutdown_only_with_the_empty_runtime_payload() {
        for (request_id, command_type, kind) in [
            ("ping-accepted", "ping", CommandKind::Ping),
            ("shutdown-accepted", "shutdown", CommandKind::Shutdown),
        ] {
            let command = json!({
                "version": 1,
                "request_id": request_id,
                "type": command_type,
                "payload": {}
            });

            let validated = validate_command(command, kind).unwrap();
            assert_eq!(validated.request_id, request_id);
            assert_eq!(validated.kind, kind);
            assert_eq!(validated.payload, json!({}));
        }
    }

    #[test]
    fn rejects_unknown_envelope_fields_and_non_contract_payload_fields() {
        let invalid = [
            (
                json!({
                    "version": 1,
                    "request_id": "req-1",
                    "type": "list_plugins",
                    "payload": {},
                    "debug": true
                }),
                CommandKind::ListPlugins,
            ),
            (
                json!({
                    "version": 1,
                    "request_id": "req-2",
                    "type": "list_plugins",
                    "payload": { "extra": true }
                }),
                CommandKind::ListPlugins,
            ),
            (
                json!({
                    "version": 1,
                    "request_id": "req-3",
                    "type": "plugin_call",
                    "payload": {
                        "plugin_id": "translator",
                        "operation": "translate",
                        "input": {},
                        "extra": true
                    }
                }),
                CommandKind::PluginCall,
            ),
            (
                json!({
                    "version": 1,
                    "request_id": "ping-1",
                    "type": "ping",
                    "payload": { "extra": true }
                }),
                CommandKind::Ping,
            ),
            (
                json!({
                    "version": 1,
                    "request_id": "shutdown-1",
                    "type": "shutdown",
                    "payload": { "extra": true }
                }),
                CommandKind::Shutdown,
            ),
        ];

        for (command, kind) in invalid {
            assert_eq!(
                validate_command(command, kind),
                Err(COMMAND_INVALID_MESSAGE)
            );
        }
    }

    #[test]
    fn validates_public_plugin_calls_and_rejects_admin_or_private_input() {
        let accepted = json!({
            "version": 1,
            "request_id": "plugin-1",
            "type": "plugin_call",
            "payload": {
                "plugin_id": "history-sqlite",
                "operation": "detail",
                "input": { "id": "entry-1" }
            }
        });
        assert!(validate_command(accepted, CommandKind::PluginCall).is_ok());

        for (operation, input) in [
            ("delete", json!({ "id": "entry-1" })),
            ("list", json!({ "nested": { "token": "fixture-private" } })),
            ("list", json!({ "export_path": "fixture-private" })),
        ] {
            let command = json!({
                "version": 1,
                "request_id": "plugin-denied",
                "type": "plugin_call",
                "payload": {
                    "plugin_id": "history-sqlite",
                    "operation": operation,
                    "input": input
                }
            });
            assert_eq!(
                validate_command(command, CommandKind::PluginCall),
                Err(COMMAND_INVALID_MESSAGE)
            );
        }
    }

    #[test]
    fn validated_command_debug_always_redacts_every_payload() {
        for kind in [
            CommandKind::Optimize,
            CommandKind::Cancel,
            CommandKind::Ping,
            CommandKind::Shutdown,
            CommandKind::ConfigureProvider,
            CommandKind::ListPlugins,
            CommandKind::PluginCall,
            CommandKind::ConfigurePlugin,
            CommandKind::ConfigureHistoryKeys,
            CommandKind::ConfigureHistoryPolicy,
            CommandKind::ConfigureHistoryPath,
            CommandKind::PluginAdminCall,
        ] {
            let command = ValidatedCommand {
                request_id: "debug-redaction".to_string(),
                kind,
                payload: json!({ "secret": "fixture-private-value" }),
            };
            let debug = format!("{command:?}");
            assert!(debug.contains("payload: \"[REDACTED]\""));
            assert!(!debug.contains("fixture-private-value"));
        }
    }
}
