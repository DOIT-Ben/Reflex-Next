import pytest

from reflex_runtime.protocol import (
    RUNTIME_PROTOCOL_VERSION,
    CommandEnvelope,
    ProtocolError,
    parse_command,
)


def command(command_type, payload=None):
    return {
        "version": 1,
        "request_id": "fixture-request",
        "type": command_type,
        "payload": {} if payload is None else payload,
    }


def test_runtime_protocol_version_is_owned_by_runtime():
    assert RUNTIME_PROTOCOL_VERSION == 1


def test_parse_valid_optimize_command():
    command = parse_command(
        {
            "version": 1,
            "request_id": "req-1",
            "type": "optimize",
            "payload": {"text": "写一封邮件"},
        }
    )

    assert command == CommandEnvelope(
        version=1,
        request_id="req-1",
        type="optimize",
        payload={"text": "写一封邮件"},
    )


def test_parse_private_provider_configuration_command():
    command = parse_command(
        {
            "version": 1,
            "request_id": "host-config-minimax",
            "type": "configure_provider",
            "payload": {
                "provider_id": "minimax",
                "secret": "fixture-private-credential",
                "config": {"model": "MiniMax-M2.7-highspeed"},
            },
        }
    )

    assert command.type == "configure_provider"
    assert command.payload["provider_id"] == "minimax"


@pytest.mark.parametrize(
    ("command_type", "payload"),
    [
        ("list_plugins", {}),
        (
            "plugin_call",
            {"plugin_id": "translator", "operation": "translate", "input": {}},
        ),
        (
            "plugin_admin_call",
            {
                "plugin_id": "history-sqlite",
                "operation": "delete",
                "input": {"admin": True},
            },
        ),
        ("configure_plugin", {"plugin_id": "translator", "enabled": True}),
        (
            "configure_history_keys",
            {"keys": {"v1": "11" * 32}},
        ),
        (
            "configure_history_policy",
            {
                "history_enabled": True,
                "privacy_mode": False,
                "history_redaction": "secrets",
            },
        ),
    ],
)
def test_parse_runtime_capability_commands(command_type, payload):
    parsed = parse_command(command(command_type, payload))

    assert parsed.type == command_type
    assert parsed.payload == payload


@pytest.mark.parametrize(
    "private_input",
    [
        {"key": "fixture-private"},
        {"nested": {"database_path": "C:\\private\\history.db"}},
        {"admin": True},
        {"private_token": "fixture-private"},
    ],
)
def test_public_plugin_call_rejects_private_fields_recursively(private_input):
    with pytest.raises(ProtocolError) as caught:
        parse_command(
            command(
                "plugin_call",
                {
                    "plugin_id": "history-sqlite",
                    "operation": "list",
                    "input": private_input,
                },
            )
        )

    assert str(caught.value) == "invalid public plugin call"
    assert "fixture-private" not in str(caught.value)


def test_history_key_command_repr_and_str_do_not_expose_private_payload():
    private_value = "11" * 32
    parsed = parse_command(
        command("configure_history_keys", {"keys": {"v1": private_value}})
    )

    assert private_value not in repr(parsed)
    assert private_value not in str(parsed)
    assert "payload=<redacted>" in repr(parsed)


@pytest.mark.parametrize(
    ("command_type", "payload"),
    [
        ("ping", {"extra": True}),
        ("list_plugins", {"extra": True}),
        (
            "plugin_call",
            {
                "plugin_id": "translator",
                "operation": "translate",
                "input": {},
                "extra": True,
            },
        ),
        ("configure_plugin", {"plugin_id": "translator", "enabled": "yes"}),
        ("configure_history_keys", {"keys": [], "extra": True}),
        (
            "configure_history_policy",
            {"history_enabled": True, "privacy_mode": False, "state": "writable"},
        ),
        ("optimize", {"text": "fixture", "unknown": True}),
    ],
)
def test_each_command_type_rejects_non_contract_fields(command_type, payload):
    with pytest.raises(ProtocolError):
        parse_command(command(command_type, payload))


def test_command_envelope_rejects_unknown_top_level_fields():
    payload = command("ping")
    payload["debug"] = True

    with pytest.raises(ProtocolError):
        parse_command(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"state": "writable"},
        {
            "history_enabled": "yes",
            "privacy_mode": False,
            "history_redaction": "secrets",
        },
        {
            "history_enabled": True,
            "privacy_mode": False,
            "history_redaction": "raw",
        },
    ],
)
def test_history_policy_requires_the_versioned_boolean_contract(payload):
    with pytest.raises(ProtocolError):
        parse_command(command("configure_history_policy", payload))


@pytest.mark.parametrize(
    "keys",
    [
        {"active": "fixture-secret"},
        {"v1": ""},
        {"../v1": "fixture-secret"},
        {"v1": 42},
        {"v0": "11" * 32},
        {"v01": "11" * 32},
        {"v1": "fixture-history-private-key"},
        {"v1": "1" * 63},
        {"v1": "1" * 65},
        {"v1": "g" * 64},
        {"v1": "AA" * 32},
    ],
)
def test_history_keys_require_safe_version_and_exact_lowercase_64_hex_value(keys):
    with pytest.raises(ProtocolError):
        parse_command(command("configure_history_keys", {"keys": keys}))


def test_history_key_protocol_rejects_overlong_version_safely():
    overlong_version = "v" + "9" * 5000

    with pytest.raises(ProtocolError):
        parse_command(
            command(
                "configure_history_keys",
                {"keys": {overlong_version: "11" * 32}},
            )
        )


def test_empty_history_key_map_is_valid_and_derives_absent_state():
    parsed = parse_command(command("configure_history_keys", {"keys": {}}))

    assert parsed.payload == {"keys": {}}


@pytest.mark.parametrize("operation", ["save", "append", "get", "search", "update_rating"])
def test_public_plugin_call_rejects_history_write_and_legacy_aliases(operation):
    with pytest.raises(ProtocolError):
        parse_command(
            command(
                "plugin_call",
                {
                    "plugin_id": "history-sqlite",
                    "operation": operation,
                    "input": {},
                },
            )
        )


@pytest.mark.parametrize(
    "payload",
    [
        {"provider_id": "../minimax", "secret": "fixture-secret", "config": {}},
        {"provider_id": "minimax", "secret": "", "config": {}},
        {"provider_id": "minimax", "secret": "fixture-secret", "config": []},
        {
            "provider_id": "minimax",
            "secret": "fixture-secret",
            "config": {},
            "unexpected": True,
        },
    ],
)
def test_private_provider_configuration_rejects_unsafe_payloads_without_echo(payload):
    with pytest.raises(ProtocolError) as caught:
        parse_command(
            {
                "version": 1,
                "request_id": "host-config-minimax",
                "type": "configure_provider",
                "payload": payload,
            }
        )

    assert str(caught.value) == "invalid provider configuration command"
    assert "fixture-secret" not in str(caught.value)

@pytest.mark.parametrize(
    "payload",
    [
        {"version": 2, "request_id": "req-1", "type": "ping", "payload": {}},
        {"version": 1, "request_id": "", "type": "ping", "payload": {}},
        {"version": 1, "request_id": "req-1", "type": "unknown", "payload": {}},
        {"version": 1, "request_id": "req-1", "type": "ping", "payload": []},
    ],
)
def test_parse_rejects_invalid_command_envelopes(payload):
    with pytest.raises(ProtocolError):
        parse_command(payload)
