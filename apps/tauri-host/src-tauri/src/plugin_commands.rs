pub const PLUGIN_COMMAND_DENIED_MESSAGE: &str = "当前窗口无权调用此插件能力。";

use serde_json::Value;

use crate::runtime_commands::{validate_command, CommandKind, ValidatedCommand};

pub fn validate_authorized_plugin_call(
    window_label: &str,
    command: Value,
) -> Result<ValidatedCommand, &'static str> {
    let command = validate_command(command, CommandKind::PluginCall)?;
    let plugin_id = command.payload["plugin_id"]
        .as_str()
        .ok_or(PLUGIN_COMMAND_DENIED_MESSAGE)?;
    let operation = command.payload["operation"]
        .as_str()
        .ok_or(PLUGIN_COMMAND_DENIED_MESSAGE)?;
    authorize_public_plugin_call(window_label, plugin_id, operation)?;
    Ok(command)
}

pub fn authorize_public_plugin_call(
    window_label: &str,
    plugin_id: &str,
    operation: &str,
) -> Result<(), &'static str> {
    let allowed = match window_label {
        "main" => matches!(
            (plugin_id, operation),
            ("history-sqlite", "rate")
                | ("translator", "translate")
                | ("markdown-preview", "preview")
                | ("semantic-detector", "status" | "download" | "delete")
        ),
        "history" => matches!(
            (plugin_id, operation),
            (
                "history-sqlite",
                "list" | "detail" | "rate" | "backups" | "scan"
            )
        ),
        _ => false,
    };

    if allowed {
        Ok(())
    } else {
        Err(PLUGIN_COMMAND_DENIED_MESSAGE)
    }
}

pub fn authorize_history_management(
    window_label: &str,
    operation: &str,
) -> Result<(), &'static str> {
    if window_label == "history"
        && matches!(
            operation,
            "export" | "delete" | "clear" | "repair" | "restore" | "rotate"
        )
    {
        Ok(())
    } else {
        Err(PLUGIN_COMMAND_DENIED_MESSAGE)
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::{authorize_public_plugin_call, validate_authorized_plugin_call};

    #[test]
    fn private_history_management_is_bound_to_the_history_window() {
        for operation in ["export", "delete", "clear", "repair", "restore", "rotate"] {
            assert!(super::authorize_history_management("history", operation).is_ok());
            assert!(super::authorize_history_management("main", operation).is_err());
            assert!(super::authorize_history_management("forged", operation).is_err());
        }
    }

    #[test]
    fn main_window_has_only_the_minimal_public_plugin_matrix() {
        for (plugin_id, operation) in [
            ("history-sqlite", "rate"),
            ("translator", "translate"),
            ("markdown-preview", "preview"),
            ("semantic-detector", "status"),
            ("semantic-detector", "download"),
            ("semantic-detector", "delete"),
        ] {
            assert!(authorize_public_plugin_call("main", plugin_id, operation).is_ok());
        }

        for (plugin_id, operation) in [
            ("history-sqlite", "list"),
            ("history-sqlite", "detail"),
            ("history-sqlite", "backups"),
            ("history-sqlite", "scan"),
            ("history-sqlite", "save"),
            ("history-sqlite", "delete"),
            ("history-sqlite", "clear"),
            ("history-sqlite", "export"),
            ("history-sqlite", "repair"),
            ("history-sqlite", "restore"),
            ("history-sqlite", "rotate"),
            ("translator", "configure"),
            ("markdown-preview", "export"),
        ] {
            assert!(authorize_public_plugin_call("main", plugin_id, operation).is_err());
        }
    }

    #[test]
    fn history_window_has_read_rate_backup_and_scan_only() {
        for operation in ["list", "detail", "rate", "backups", "scan"] {
            assert!(authorize_public_plugin_call("history", "history-sqlite", operation).is_ok());
        }

        for operation in [
            "save", "delete", "clear", "export", "repair", "restore", "rotate",
        ] {
            assert!(authorize_public_plugin_call("history", "history-sqlite", operation).is_err());
        }
        assert!(authorize_public_plugin_call("history", "translator", "translate").is_err());
        assert!(authorize_public_plugin_call("forged", "history-sqlite", "rate").is_err());
    }

    #[test]
    fn authorization_uses_the_real_window_label_and_rejects_payload_spoofing() {
        let valid = json!({
            "version": 1,
            "request_id": "plugin-main",
            "type": "plugin_call",
            "payload": {
                "plugin_id": "translator",
                "operation": "translate",
                "input": { "text": "fixture" }
            }
        });
        assert!(validate_authorized_plugin_call("main", valid).is_ok());

        let forged = json!({
            "version": 1,
            "request_id": "plugin-forged",
            "type": "plugin_call",
            "payload": {
                "plugin_id": "history-sqlite",
                "operation": "list",
                "input": {},
                "window": "history"
            }
        });
        assert!(validate_authorized_plugin_call("main", forged).is_err());
    }
}
