use std::fmt;

use serde_json::Value;

pub const COMMAND_INVALID_MESSAGE: &str = "运行请求无效。";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CommandKind {
    Optimize,
    Cancel,
    ConfigureProvider,
}

impl CommandKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Optimize => "optimize",
            Self::Cancel => "cancel",
            Self::ConfigureProvider => "configure_provider",
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

pub fn configure_provider_command(
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
        request_id: format!("host-config-{provider_id}"),
        kind: CommandKind::ConfigureProvider,
        payload: serde_json::json!({
            "provider_id": provider_id,
            "secret": secret,
            "config": config,
        }),
    })
}

pub fn validate_command(
    command: Value,
    expected_kind: CommandKind,
) -> Result<ValidatedCommand, &'static str> {
    let Value::Object(command) = command else {
        return Err(COMMAND_INVALID_MESSAGE);
    };
    let request_id = command
        .get("request_id")
        .and_then(Value::as_str)
        .filter(|value| !value.trim().is_empty())
        .ok_or(COMMAND_INVALID_MESSAGE)?;
    let kind = command
        .get("type")
        .and_then(Value::as_str)
        .filter(|value| *value == expected_kind.as_str())
        .ok_or(COMMAND_INVALID_MESSAGE)?;
    let is_current_version = command.get("version").and_then(Value::as_u64) == Some(1);
    let payload = command
        .get("payload")
        .filter(|value| value.is_object())
        .cloned()
        .ok_or(COMMAND_INVALID_MESSAGE)?;

    if !is_current_version || kind != expected_kind.as_str() {
        return Err(COMMAND_INVALID_MESSAGE);
    }

    Ok(ValidatedCommand {
        request_id: request_id.to_string(),
        kind: expected_kind,
        payload,
    })
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::{
        configure_provider_command, validate_command, CommandKind, COMMAND_INVALID_MESSAGE,
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

        assert_eq!(command.request_id, "host-config-minimax");
        assert_eq!(command.kind, CommandKind::ConfigureProvider);
        assert_eq!(command.payload["provider_id"], "minimax");
        assert_eq!(command.payload["secret"], secret);
        assert!(!format!("{command:?}").contains(secret));
    }
}
