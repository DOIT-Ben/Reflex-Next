use serde_json::Value;

pub const COMMAND_INVALID_MESSAGE: &str = "运行请求无效。";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum CommandKind {
    Optimize,
    Cancel,
}

impl CommandKind {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Optimize => "optimize",
            Self::Cancel => "cancel",
        }
    }
}

#[derive(Debug, Clone, PartialEq)]
pub struct ValidatedCommand {
    pub request_id: String,
    pub kind: CommandKind,
    pub payload: Value,
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

    use super::{validate_command, CommandKind, COMMAND_INVALID_MESSAGE};

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
}
