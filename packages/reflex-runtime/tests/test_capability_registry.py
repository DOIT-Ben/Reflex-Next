from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from pathlib import Path
import threading

import pytest

from reflex_core import CancellationToken
from reflex_runtime.capability_registry import (
    CapabilityDenied,
    CapabilityRegistry,
    HistoryPolicySnapshot,
)
from reflex_runtime.plugin_contracts import (
    CapabilityListEnvelope,
    PluginDescriptor,
    PluginEventEnvelope,
)


class RecordingPlugin:
    def __init__(self) -> None:
        self.calls = []

    def invoke(self, operation, payload, services, cancellation):
        self.calls.append((operation, payload, services, cancellation))
        return {"ok": True}


def descriptor(
    plugin_id: str,
    kind: str,
    operations: tuple[str, ...],
    permissions: tuple[str, ...] = (),
    public_operations: tuple[str, ...] | None = None,
) -> PluginDescriptor:
    return PluginDescriptor(
        plugin_id=plugin_id,
        display_name=plugin_id,
        version="fixture-1",
        kind=kind,
        permissions=permissions,
        operations=operations,
        public_operations=operations if public_operations is None else public_operations,
    )


HISTORY_OPERATIONS = (
    "save",
    "list",
    "detail",
    "rate",
    "delete",
    "clear",
    "export",
    "scan",
    "repair",
    "backups",
    "restore",
    "rotate",
)
HISTORY_PUBLIC_OPERATIONS = ("list", "detail", "rate", "backups", "scan")


def history_descriptor() -> PluginDescriptor:
    return descriptor(
        "history-sqlite",
        "storage",
        HISTORY_OPERATIONS,
        ("storage_read", "storage_write"),
        HISTORY_PUBLIC_OPERATIONS,
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"plugin_id": "../history"},
        {"kind": "provider"},
        {"permissions": ("storage/read",)},
        {"operations": ("__dict__",)},
    ],
)
def test_plugin_descriptor_rejects_unsafe_contract_values(changes):
    base = descriptor("history-sqlite", "storage", ("list",), ("storage_read",))

    with pytest.raises(ValueError):
        replace(base, **changes)


def test_capability_and_plugin_event_envelopes_are_not_core_events():
    plugin = descriptor("translator", "transformer", ("translate",))

    capability = CapabilityListEnvelope("list-1", (plugin,)).to_dict()
    event = PluginEventEnvelope(
        request_id="plugin-1",
        plugin_id="translator",
        operation="translate",
        status="result",
        data={"text": "fixture result"},
    ).to_dict()

    assert capability == {
        "version": 1,
        "request_id": "list-1",
        "type": "capability_list",
        "plugins": [plugin.to_dict()],
    }
    assert "event" not in capability
    assert event["type"] == "plugin_event"
    assert event["status"] == "result"
    assert "event" not in event


def test_capability_list_exposes_only_public_operations():
    plugin = history_descriptor()

    listed = CapabilityListEnvelope("list-public", (plugin,)).to_dict()["plugins"][0]

    assert listed["public_operations"] == list(HISTORY_PUBLIC_OPERATIONS)
    assert "operations" not in listed
    assert not ({"save", "delete", "clear", "repair", "restore", "rotate"} & set(listed["public_operations"]))


def test_plugin_envelope_accepts_a_safe_host_scoped_request_id():
    event = PluginEventEnvelope(
        request_id="host:req.1",
        plugin_id="translator",
        operation="translate",
        status="result",
        data={},
    )

    assert event.to_dict()["request_id"] == "host:req.1"


def test_plugin_event_rejects_unknown_status_and_error_detail():
    with pytest.raises(ValueError):
        PluginEventEnvelope("req", "translator", "translate", "done")

    with pytest.raises(ValueError):
        PluginEventEnvelope(
            "req",
            "translator",
            "translate",
            "error",
            data={"exception": "raw traceback"},
        )


def test_public_dispatch_uses_only_invoke_for_allowlisted_operation():
    plugin = RecordingPlugin()
    token = CancellationToken()
    services = {"clock": object()}
    registry = CapabilityRegistry(
        [(descriptor("translator", "transformer", ("translate",)), plugin)],
        enabled_plugins={"translator"},
    )

    result = registry.invoke_public(
        "translator", "translate", {"text": "fixture"}, services, token
    )

    assert result == {"ok": True}
    assert plugin.calls == [("translate", {"text": "fixture"}, services, token)]


def test_public_dispatch_cannot_reach_admin_or_undeclared_operations():
    plugin = RecordingPlugin()
    registry = CapabilityRegistry(
        [(history_descriptor(), plugin)],
    )
    registry.configure_history_keys({"v1": "11" * 32})
    registry.configure_history_policy(
        history_enabled=True,
        privacy_mode=False,
        history_redaction="secrets",
    )

    with pytest.raises(CapabilityDenied) as admin_error:
        registry.invoke_public("history-sqlite", "delete", {}, {}, CancellationToken())
    with pytest.raises(CapabilityDenied):
        registry.invoke_admin(
            "history-sqlite", "missing", {}, {}, CancellationToken()
        )

    assert admin_error.value.code == "operation_not_allowed"
    assert plugin.calls == []


@pytest.mark.parametrize(
    "keys",
    [
        {"v0": "11" * 32},
        {"v01": "11" * 32},
        {"active": "11" * 32},
        {"v1": "fixture-history-private-key"},
        {"v1": ""},
        {"v1": "1" * 63},
        {"v1": "1" * 65},
        {"v1": "g" * 64},
        {"v1": "AA" * 32},
    ],
)
def test_direct_history_key_configuration_requires_canonical_version_and_key(keys):
    registry = CapabilityRegistry([(history_descriptor(), RecordingPlugin())])

    with pytest.raises(CapabilityDenied) as caught:
        registry.configure_history_keys(keys)

    assert caught.value.code == "history_keys_invalid"


def test_direct_history_key_configuration_rejects_overlong_version_safely():
    registry = CapabilityRegistry([(history_descriptor(), RecordingPlugin())])
    overlong_version = "v" + "9" * 5000

    with pytest.raises(CapabilityDenied) as caught:
        registry.configure_history_keys({overlong_version: "11" * 32})

    assert caught.value.code == "history_keys_invalid"


def test_admin_dispatch_has_a_separate_explicit_allowlist():
    plugin = RecordingPlugin()
    registry = CapabilityRegistry(
        [
            (
                history_descriptor(),
                plugin,
            )
        ],
    )
    registry.configure_history_keys({"v1": "11" * 32})
    registry.configure_history_policy(
        history_enabled=True,
        privacy_mode=False,
        history_redaction="secrets",
    )

    registry.invoke_admin("history-sqlite", "delete", {}, {}, CancellationToken())

    assert plugin.calls[0][0] == "delete"


def test_disabled_optional_plugin_is_not_invoked():
    plugin = RecordingPlugin()
    registry = CapabilityRegistry(
        [(descriptor("markdown-preview", "command", ("preview", "export"), public_operations=("preview",)), plugin)],
        enabled_plugins=set(),
    )

    with pytest.raises(CapabilityDenied) as caught:
        registry.invoke_public(
            "markdown-preview", "preview", {}, {}, CancellationToken()
        )

    assert caught.value.code == "plugin_disabled"
    assert plugin.calls == []


def test_history_state_is_derived_only_from_keys_and_policy():
    plugin = RecordingPlugin()
    registry = CapabilityRegistry([(history_descriptor(), plugin)])

    assert registry.history_state == "absent"

    registry.configure_history_keys({"v1": "11" * 32})
    assert registry.history_state == "read_only"

    registry.configure_history_policy(
        history_enabled=True,
        privacy_mode=True,
        history_redaction="secrets",
    )
    assert registry.history_state == "private"

    registry.configure_history_policy(
        history_enabled=True,
        privacy_mode=False,
        history_redaction="none",
    )
    assert registry.history_state == "writable"

    registry.configure_history_keys({})
    assert registry.history_state == "absent"


@pytest.mark.parametrize("state", ["absent", "read_only", "private", "unavailable"])
def test_internal_trusted_save_is_rejected_unless_history_is_writable(state):
    plugin = RecordingPlugin()
    registry = CapabilityRegistry(
        [(history_descriptor(), plugin)],
        history_unavailable=state == "unavailable",
    )
    if state != "absent":
        registry.configure_history_keys({"v1": "11" * 32})
    if state == "private":
        registry.configure_history_policy(
            history_enabled=True,
            privacy_mode=True,
            history_redaction="secrets",
        )

    assert registry.history_state == state
    with pytest.raises(CapabilityDenied):
        registry.invoke_internal(
            "history-sqlite",
            "save",
            {},
            {},
            CancellationToken(),
            trusted=True,
        )
    assert plugin.calls == []


def test_internal_trusted_save_succeeds_only_in_writable_state():
    plugin = RecordingPlugin()
    registry = CapabilityRegistry([(history_descriptor(), plugin)])
    registry.configure_history_keys({"v1": "11" * 32})
    registry.configure_history_policy(
        history_enabled=True,
        privacy_mode=False,
        history_redaction="secrets",
    )

    registry.invoke_internal(
        "history-sqlite",
        "save",
        {"text": "fixture"},
        {},
        CancellationToken(),
        trusted=True,
    )

    assert plugin.calls[0][0] == "save"


@pytest.mark.parametrize("state", ["read_only", "private"])
@pytest.mark.parametrize("operation", ["delete", "repair"])
def test_existing_history_admin_operations_are_allowed_without_new_record_writes(
    state, operation
):
    plugin = RecordingPlugin()
    registry = CapabilityRegistry([(history_descriptor(), plugin)])
    registry.configure_history_keys({"v1": "11" * 32})
    if state == "private":
        registry.configure_history_policy(
            history_enabled=True,
            privacy_mode=True,
            history_redaction="secrets",
        )

    registry.invoke_admin(
        "history-sqlite", operation, {}, {}, CancellationToken()
    )
    with pytest.raises(CapabilityDenied):
        registry.invoke_internal(
            "history-sqlite",
            "save",
            {},
            {},
            CancellationToken(),
            trusted=True,
        )

    assert [call[0] for call in plugin.calls] == [operation]


@pytest.mark.parametrize("unavailable", [False, True])
def test_absent_and_unavailable_history_reject_every_real_call(unavailable):
    plugin = RecordingPlugin()
    registry = CapabilityRegistry(
        [(history_descriptor(), plugin)], history_unavailable=unavailable
    )

    for invoke, operation, kwargs in (
        (registry.invoke_public, "list", {}),
        (registry.invoke_admin, "delete", {}),
        (registry.invoke_internal, "save", {"trusted": True}),
    ):
        with pytest.raises(CapabilityDenied):
            invoke(
                "history-sqlite",
                operation,
                {},
                {},
                CancellationToken(),
                **kwargs,
            )

    assert plugin.calls == []


def test_known_unloaded_history_descriptor_tracks_absent_then_unavailable():
    known = history_descriptor()
    registry = CapabilityRegistry([], known_descriptors=(known,))

    absent = registry.descriptors()[0]
    assert absent.state == "absent"
    assert absent.error_code is None

    registry.configure_history_keys({"v1": "11" * 32})
    unavailable = registry.descriptors()[0]

    assert registry.history_state == "unavailable"
    assert unavailable.state == "unavailable"
    assert unavailable.error_code == "plugin_unavailable"


def test_loaded_history_descriptor_tracks_every_derived_runtime_state():
    plugin = RecordingPlugin()
    known = history_descriptor()
    registry = CapabilityRegistry(
        [(known, plugin)], known_descriptors=(known,)
    )

    assert registry.descriptors()[0].state == "absent"
    registry.configure_history_keys({"v1": "11" * 32})
    assert registry.descriptors()[0].state == "read_only"
    registry.configure_history_policy(
        history_enabled=True,
        privacy_mode=True,
        history_redaction="secrets",
    )
    assert registry.descriptors()[0].state == "private"
    registry.configure_history_policy(
        history_enabled=True,
        privacy_mode=False,
        history_redaction="secrets",
    )
    assert registry.descriptors()[0].state == "writable"


def test_history_policy_is_an_immutable_atomic_snapshot():
    plugin = RecordingPlugin()
    registry = CapabilityRegistry([(history_descriptor(), plugin)])
    original = registry.history_policy

    assert original == HistoryPolicySnapshot(False, False, "secrets")
    with pytest.raises(FrozenInstanceError):
        original.history_enabled = True

    barrier = threading.Barrier(2)
    observed = []

    def configure_private():
        barrier.wait()
        registry.configure_history_policy(
            history_enabled=True,
            privacy_mode=True,
            history_redaction="none",
        )

    def observe():
        barrier.wait()
        for _ in range(2_000):
            observed.append(registry.history_policy)

    writer = threading.Thread(target=configure_private)
    reader = threading.Thread(target=observe)
    writer.start()
    reader.start()
    writer.join(timeout=2)
    reader.join(timeout=2)

    assert set(observed).issubset(
        {
            HistoryPolicySnapshot(False, False, "secrets"),
            HistoryPolicySnapshot(True, True, "none"),
        }
    )
    assert HistoryPolicySnapshot(True, False, "none") not in observed


def test_plugin_execution_happens_outside_registry_lock():
    entered = threading.Event()
    release = threading.Event()

    class BlockingPlugin(RecordingPlugin):
        def invoke(self, operation, payload, services, cancellation):
            entered.set()
            release.wait(timeout=2)
            return {"ok": True}

    plugin = BlockingPlugin()
    translator = descriptor("translator", "transformer", ("translate",))
    registry = CapabilityRegistry(
        [(translator, plugin)], enabled_plugins={"translator"}
    )
    worker = threading.Thread(
        target=lambda: registry.invoke_public(
            "translator", "translate", {}, {}, CancellationToken()
        )
    )
    worker.start()
    assert entered.wait(timeout=1)

    registry.configure_plugin("translator", False)
    release.set()
    worker.join(timeout=2)

    assert not worker.is_alive()


def test_history_plugin_receives_only_a_private_immutable_policy_and_key_snapshot():
    plugin = RecordingPlugin()
    registry = CapabilityRegistry([(history_descriptor(), plugin)])
    registry.configure_history_path(Path("D:/private/history/history.sqlite3"))
    registry.configure_history_keys({"v1": "11" * 32})
    registry.configure_history_policy(
        history_enabled=True,
        privacy_mode=False,
        history_redaction="secrets",
    )
    services = {
        "history_database_path": Path("D:/private/history.sqlite3"),
        "public_value": "must-not-be-forwarded",
    }

    registry.invoke_public(
        "history-sqlite",
        "list",
        {},
        services,
        CancellationToken(),
    )

    forwarded = plugin.calls[-1][2]
    assert set(forwarded) == {"history"}
    assert forwarded["history"]["database_path"] == Path(
        "D:/private/history/history.sqlite3"
    )
    assert forwarded["history"]["keys"] == {"v1": "11" * 32}
    assert forwarded["history"]["history_enabled"] is True
    assert forwarded["history"]["privacy_mode"] is False
    assert forwarded["history"]["history_redaction"] == "secrets"
    assert forwarded is not services
    rendered = " ".join(
        (
            repr(forwarded),
            repr(forwarded["history"]),
            repr(forwarded["history"]["keys"]),
        )
    )
    assert "11" * 32 not in rendered
    assert "D:/private/history.sqlite3" not in rendered.replace("\\", "/")
    assert "redacted" in rendered.casefold()
    with pytest.raises(TypeError):
        forwarded["history"]["privacy_mode"] = True
    with pytest.raises(TypeError):
        forwarded["history"]["keys"]["v2"] = "22" * 32


def test_history_path_is_stored_privately_and_cannot_be_overridden_by_call_services():
    plugin = RecordingPlugin()
    registry = CapabilityRegistry([(history_descriptor(), plugin)])
    configured_path = Path("D:/AppData/Reflex Next/history/history.sqlite3")
    registry.configure_history_path(configured_path)
    registry.configure_history_keys({"v1": "11" * 32})

    registry.invoke_public(
        "history-sqlite",
        "list",
        {},
        {"history_database_path": Path("D:/forged/history/history.sqlite3")},
        CancellationToken(),
    )

    forwarded = plugin.calls[-1][2]
    assert forwarded["history"]["database_path"] == configured_path
    assert "history.sqlite3" not in repr(forwarded)


def test_history_save_is_rejected_before_plugin_when_policy_is_disabled_or_private():
    plugin = RecordingPlugin()
    registry = CapabilityRegistry([(history_descriptor(), plugin)])
    registry.configure_history_keys({"v1": "11" * 32})

    for privacy_mode in (False, True):
        registry.configure_history_policy(
            history_enabled=not privacy_mode,
            privacy_mode=privacy_mode,
            history_redaction="secrets",
        )
        if not privacy_mode:
            registry.configure_history_policy(
                history_enabled=False,
                privacy_mode=False,
                history_redaction="secrets",
            )
        with pytest.raises(CapabilityDenied) as caught:
            registry.invoke_internal(
                "history-sqlite",
                "save",
                {},
                {"history_database_path": Path("D:/private/history.sqlite3")},
                CancellationToken(),
                trusted=True,
            )
        assert caught.value.code == "write_permission_denied"
    assert plugin.calls == []


@pytest.mark.parametrize(
    "operation",
    [
        "append",
        "save",
        "delete",
        "clear",
        "repair",
        "restore",
        "rotate",
        "update_rating",
        "get",
        "search",
    ],
)
def test_public_history_call_rejects_write_admin_and_legacy_aliases(operation):
    plugin = RecordingPlugin()
    registry = CapabilityRegistry([(history_descriptor(), plugin)])
    registry.configure_history_keys({"v1": "11" * 32})
    registry.configure_history_policy(
        history_enabled=True,
        privacy_mode=False,
        history_redaction="secrets",
    )

    with pytest.raises(CapabilityDenied) as caught:
        registry.invoke_public(
            "history-sqlite", operation, {}, {}, CancellationToken()
        )

    assert caught.value.code == "operation_not_allowed"
    assert plugin.calls == []


def test_untrusted_internal_save_is_rejected_even_when_writable():
    plugin = RecordingPlugin()
    registry = CapabilityRegistry([(history_descriptor(), plugin)])
    registry.configure_history_keys({"v1": "11" * 32})
    registry.configure_history_policy(
        history_enabled=True,
        privacy_mode=False,
        history_redaction="secrets",
    )

    with pytest.raises(CapabilityDenied) as caught:
        registry.invoke_internal(
            "history-sqlite",
            "save",
            {},
            {},
            CancellationToken(),
            trusted=False,
        )

    assert caught.value.code == "trusted_call_required"
