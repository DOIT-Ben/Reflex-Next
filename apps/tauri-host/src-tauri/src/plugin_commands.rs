pub const PLUGIN_COMMAND_DENIED_MESSAGE: &str = "当前窗口无权调用此插件能力。";

use serde_json::Value;

use crate::runtime_commands::{validate_command, CommandKind, ValidatedCommand};

const MAIN_CAPABILITY_PERMISSIONS: &[&str] = &[
    "allow-read-clipboard-text",
    "allow-write-clipboard-text",
    "allow-hide-main-window",
    "allow-show-history-window",
    "allow-minimize-window",
    "allow-toggle-maximize-window",
    "allow-set-window-size",
    "allow-desktop-status",
    "allow-runtime-available",
    "allow-runtime-optimize",
    "allow-runtime-cancel",
    "allow-runtime-list-providers",
    "allow-runtime-list-plugins",
    "allow-runtime-plugin-call",
    "allow-runtime-plugin-cancel",
    "allow-load-app-config",
    "allow-save-app-config",
    "allow-provider-secret-status",
    "allow-save-provider-secret",
    "allow-delete-provider-secret",
    "allow-diagnostic-bundle-export",
    "allow-diagnostic-bundle-cancel",
    "core:event:allow-listen",
    "core:event:allow-unlisten",
];

const HISTORY_CAPABILITY_PERMISSIONS: &[&str] = &[
    "allow-runtime-plugin-call",
    "allow-runtime-plugin-cancel",
    "allow-history-export",
    "allow-history-admin-operation",
    "allow-history-operation-cancel",
    "allow-history-reuse-intent",
    "allow-load-app-config",
    "core:event:allow-listen",
    "core:event:allow-unlisten",
];

const MAIN_PUBLIC_PLUGIN_CALLS: &[(&str, &str)] = &[
    ("history-sqlite", "rate"),
    ("translator", "translate"),
    ("markdown-preview", "preview"),
    ("semantic-detector", "status"),
    ("semantic-detector", "download"),
    ("semantic-detector", "delete"),
];

const HISTORY_PUBLIC_PLUGIN_CALLS: &[(&str, &str)] = &[
    ("history-sqlite", "list"),
    ("history-sqlite", "detail"),
    ("history-sqlite", "rate"),
    ("history-sqlite", "backups"),
    ("history-sqlite", "scan"),
];

const HISTORY_MANAGEMENT_OPERATIONS: &[&str] =
    &["export", "delete", "clear", "repair", "restore", "rotate"];

struct WindowAuthorization {
    capability_permissions: &'static [&'static str],
    public_plugin_calls: &'static [(&'static str, &'static str)],
    history_management_operations: &'static [&'static str],
}

const MAIN_AUTHORIZATION: WindowAuthorization = WindowAuthorization {
    capability_permissions: MAIN_CAPABILITY_PERMISSIONS,
    public_plugin_calls: MAIN_PUBLIC_PLUGIN_CALLS,
    history_management_operations: &[],
};

const HISTORY_AUTHORIZATION: WindowAuthorization = WindowAuthorization {
    capability_permissions: HISTORY_CAPABILITY_PERMISSIONS,
    public_plugin_calls: HISTORY_PUBLIC_PLUGIN_CALLS,
    history_management_operations: HISTORY_MANAGEMENT_OPERATIONS,
};

fn authorization_for_window(window_label: &str) -> Option<&'static WindowAuthorization> {
    match window_label {
        "main" => Some(&MAIN_AUTHORIZATION),
        "history" => Some(&HISTORY_AUTHORIZATION),
        _ => None,
    }
}

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
    let allowed = authorization_for_window(window_label).is_some_and(|policy| {
        policy
            .capability_permissions
            .contains(&"allow-runtime-plugin-call")
            && policy.public_plugin_calls.contains(&(plugin_id, operation))
    });

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
    let required_permission = if operation == "export" {
        "allow-history-export"
    } else {
        "allow-history-admin-operation"
    };
    let allowed = authorization_for_window(window_label).is_some_and(|policy| {
        policy.capability_permissions.contains(&required_permission)
            && policy.history_management_operations.contains(&operation)
    });
    if allowed {
        Ok(())
    } else {
        Err(PLUGIN_COMMAND_DENIED_MESSAGE)
    }
}

#[cfg(test)]
mod tests {
    use std::collections::HashSet;

    use serde_json::json;
    use serde_json::Value;

    use super::{authorize_public_plugin_call, validate_authorized_plugin_call};

    fn capability(source: &str) -> Value {
        serde_json::from_str(source).expect("capability JSON must be valid")
    }

    fn assert_exact_capability(capability: &Value, identifier: &str, window_label: &str) {
        assert_eq!(capability["identifier"], identifier);
        assert_eq!(capability["windows"], json!([window_label]));
        assert_eq!(capability["platforms"], json!(["windows"]));

        let actual = capability["permissions"]
            .as_array()
            .expect("permissions must be an array")
            .iter()
            .map(|permission| permission.as_str().expect("permission must be a string"))
            .collect::<Vec<_>>();
        let policy = super::authorization_for_window(window_label)
            .expect("capability window must have a Rust authorization policy");
        assert_eq!(actual, policy.capability_permissions);
        assert_eq!(
            actual.iter().copied().collect::<HashSet<_>>().len(),
            actual.len()
        );
    }

    #[test]
    fn capability_files_define_the_exact_minimal_window_matrix() {
        assert_exact_capability(
            &capability(include_str!("../capabilities/default.json")),
            "main-capability",
            "main",
        );
        assert_exact_capability(
            &capability(include_str!("../capabilities/history.json")),
            "history-capability",
            "history",
        );
    }

    #[test]
    fn webview_capabilities_expose_no_private_runtime_commands() {
        let forbidden = [
            "allow-configure-provider",
            "allow-configure-plugin",
            "allow-configure-history-keys",
            "allow-configure-history-policy",
            "allow-plugin-admin-call",
        ];
        for source in [
            include_str!("../capabilities/default.json"),
            include_str!("../capabilities/history.json"),
        ] {
            let capability = capability(source);
            let permissions = capability["permissions"].as_array().unwrap();
            for permission in forbidden {
                assert!(!permissions.iter().any(|value| value == permission));
            }
        }
    }

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

        let spoofed_main = json!({
            "version": 1,
            "request_id": "plugin-unknown-window",
            "type": "plugin_call",
            "payload": {
                "plugin_id": "translator",
                "operation": "translate",
                "input": { "text": "fixture" },
                "window": "main"
            }
        });
        for real_label in ["", "Main", "main ", "history/../main", "unknown"] {
            assert!(validate_authorized_plugin_call(real_label, spoofed_main.clone()).is_err());
            assert!(super::authorization_for_window(real_label).is_none());
        }
    }
}
