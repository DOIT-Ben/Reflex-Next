from __future__ import annotations

import sqlite3

import pytest

from reflex_core import CancellationToken, OperationCancelled
from reflex_history_sqlite import plugin
from reflex_history_sqlite.contract import HistoryPluginError
from reflex_history_sqlite.repository import HistoryRepository


def _rotation_services(history_services, *, active="v1", pending="v2"):
    history_services["history"]["keys"] = {
        "v1": "11" * 32,
        "v2": "22" * 32,
        "v3": "33" * 32,
    }
    history_services["history"]["active_key_version"] = active
    history_services["history"]["pending_key_version"] = pending
    return history_services


def test_rotation_prepares_under_pending_key_then_requires_host_promotion_and_finalize(
    history_plugin, history_services, make_snapshot
):
    services = _rotation_services(history_services)
    history_plugin.invoke(
        "save", make_snapshot(), services, CancellationToken()
    )

    prepared = history_plugin.invoke(
        "rotate",
        {"action": "prepare", "target_version": "v2"},
        services,
        CancellationToken(),
    )

    assert prepared["promotion_required"] is True
    assert prepared["target_version"] == "v2"
    with pytest.raises(HistoryPluginError, match="history_busy"):
        history_plugin.invoke(
            "save", make_snapshot(id="blocked"), services, CancellationToken()
        )
    connection = sqlite3.connect(services["history"]["database_path"])
    try:
        assert connection.execute(
            "SELECT DISTINCT key_version FROM history_records"
        ).fetchall() == [(2,)]
        assert connection.execute(
            "SELECT phase FROM rotation_checkpoint WHERE id = 1"
        ).fetchone() == ("verified",)
    finally:
        connection.close()

    promoted = _rotation_services(services, active="v2", pending=None)
    finalized = history_plugin.invoke(
        "rotate",
        {"action": "finalize", "target_version": "v2"},
        promoted,
        CancellationToken(),
    )
    assert finalized == {"rotated": True, "active_version": "v2"}
    history_plugin.invoke(
        "save", make_snapshot(id="after"), promoted, CancellationToken()
    )
    assert history_plugin.invoke(
        "detail", {"id": "history-001"}, promoted, CancellationToken()
    )["record"]["output"] == "Optimized result"


def test_restart_after_host_promotion_resumes_verified_checkpoint_before_new_rotation(
    history_plugin, history_services, make_snapshot
):
    services = _rotation_services(history_services)
    history_plugin.invoke("save", make_snapshot(), services, CancellationToken())
    history_plugin.invoke(
        "rotate",
        {"action": "prepare", "target_version": "v2"},
        services,
        CancellationToken(),
    )
    restarted = plugin()
    promoted = _rotation_services(services, active="v2", pending=None)

    resumed = restarted.invoke(
        "rotate",
        {"action": "resume", "target_version": "v2"},
        promoted,
        CancellationToken(),
    )

    assert resumed == {"resumed": True, "rotated": True, "active_version": "v2"}
    connection = sqlite3.connect(promoted["history"]["database_path"])
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM rotation_checkpoint"
        ).fetchone() == (0,)
    finally:
        connection.close()
    assert restarted.invoke(
        "save",
        make_snapshot(id="after-resume"),
        promoted,
        CancellationToken(),
    )["id"] == "after-resume"


@pytest.mark.parametrize(
    "phase",
    ["frozen", "backup", "metadata", "reencrypt", "verified"],
)
def test_each_rotation_phase_failure_restores_backup_and_never_promotes_pending(
    history_plugin, history_services, make_snapshot, monkeypatch, phase
):
    services = _rotation_services(history_services)
    history_plugin.invoke("save", make_snapshot(), services, CancellationToken())
    original = HistoryRepository._rotation_phase_hook

    def fail_at_phase(self, current):
        if current == phase:
            raise RuntimeError("fixture body path key")
        return original(self, current)

    monkeypatch.setattr(HistoryRepository, "_rotation_phase_hook", fail_at_phase)

    with pytest.raises(HistoryPluginError) as caught:
        history_plugin.invoke(
            "rotate",
            {"action": "prepare", "target_version": "v2"},
            services,
            CancellationToken(),
        )
    assert caught.value.code in {"history_rotation_failed", "history_recovery_required"}
    assert "fixture" not in str(caught.value)
    connection = sqlite3.connect(services["history"]["database_path"])
    try:
        assert connection.execute(
            "SELECT DISTINCT key_version FROM history_records"
        ).fetchall() == [(1,)]
        assert connection.execute(
            "SELECT COUNT(*) FROM rotation_checkpoint"
        ).fetchone() == (0,)
    finally:
        connection.close()


def test_host_promotion_failure_rollback_unfreezes_later_history_writes(
    history_plugin, history_services, make_snapshot
):
    services = _rotation_services(history_services)
    history_plugin.invoke("save", make_snapshot(), services, CancellationToken())
    prepared = history_plugin.invoke(
        "rotate",
        {"action": "prepare", "target_version": "v2"},
        services,
        CancellationToken(),
    )

    rolled_back = history_plugin.invoke(
        "rotate",
        {"action": "rollback", "target_version": "v2"},
        services,
        CancellationToken(),
    )

    assert rolled_back == {"rolled_back": True, "active_version": "v1"}
    assert prepared["promotion_required"] is True
    services = _rotation_services(services, active="v1", pending=None)
    assert history_plugin.invoke(
        "save", make_snapshot(id="after-promote-failure"), services, CancellationToken()
    )["id"] == "after-promote-failure"


def test_cancelled_rotation_uses_non_cancelled_recovery_and_restores_v1(
    history_plugin, history_services, make_snapshot, monkeypatch
):
    services = _rotation_services(history_services)
    for index in range(3):
        history_plugin.invoke(
            "save",
            make_snapshot(id=f"cancel-record-{index}"),
            services,
            CancellationToken(),
        )
    token = CancellationToken()
    original = HistoryRepository._reencrypt_batch
    calls = 0

    def cancel_after_first_batch(self, *args, **kwargs):
        nonlocal calls
        changed = original(self, *args, **kwargs)
        calls += 1
        if calls == 1:
            token.cancel()
        return changed

    monkeypatch.setattr(
        HistoryRepository,
        "_reencrypt_batch",
        cancel_after_first_batch,
    )

    with pytest.raises(OperationCancelled):
        history_plugin.invoke(
            "rotate",
            {"action": "prepare", "target_version": "v2", "batch_size": 1},
            services,
            token,
        )

    connection = sqlite3.connect(services["history"]["database_path"])
    try:
        assert connection.execute(
            "SELECT DISTINCT key_version FROM history_records"
        ).fetchall() == [(1,)]
        assert connection.execute(
            "SELECT COUNT(*) FROM rotation_checkpoint"
        ).fetchone() == (0,)
    finally:
        connection.close()


def test_interrupted_rotation_resumes_from_checkpoint_with_mixed_key_versions(
    history_plugin, history_services, make_snapshot, monkeypatch
):
    services = _rotation_services(history_services)
    for index in range(3):
        history_plugin.invoke(
            "save", make_snapshot(id=f"record-{index}"), services, CancellationToken()
        )
    calls = 0
    original = HistoryRepository._reencrypt_batch

    class SimulatedProcessExit(BaseException):
        pass

    def interrupt_after_first_batch(self, *args, **kwargs):
        nonlocal calls
        result = original(self, *args, **kwargs)
        calls += 1
        if calls == 1:
            raise SimulatedProcessExit()
        return result

    monkeypatch.setattr(HistoryRepository, "_reencrypt_batch", interrupt_after_first_batch)
    with pytest.raises(SimulatedProcessExit):
        history_plugin.invoke(
            "rotate",
            {"action": "prepare", "target_version": "v2", "batch_size": 1},
            services,
            CancellationToken(),
        )

    connection = sqlite3.connect(services["history"]["database_path"])
    try:
        versions = {
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT key_version FROM history_records"
            )
        }
        assert versions == {1, 2}
    finally:
        connection.close()

    monkeypatch.setattr(HistoryRepository, "_reencrypt_batch", original)
    resumed_plugin = plugin()
    prepared = resumed_plugin.invoke(
        "rotate",
        {"action": "prepare", "target_version": "v2", "batch_size": 1},
        services,
        CancellationToken(),
    )
    assert prepared["promotion_required"] is True
    assert resumed_plugin.invoke(
        "detail", {"id": "record-0"}, services, CancellationToken()
    )["record"]["corrupted"] is False


def test_two_rotations_keep_old_keys_and_each_generation_backup_is_restorable(
    history_plugin, history_services, make_snapshot
):
    services = _rotation_services(history_services)
    history_plugin.invoke("save", make_snapshot(), services, CancellationToken())
    first = history_plugin.invoke(
        "rotate", {"action": "prepare", "target_version": "v2"}, services, CancellationToken()
    )
    services = _rotation_services(services, active="v2", pending=None)
    history_plugin.invoke(
        "rotate", {"action": "finalize", "target_version": "v2"}, services, CancellationToken()
    )
    services = _rotation_services(services, active="v2", pending="v3")
    second = history_plugin.invoke(
        "rotate", {"action": "prepare", "target_version": "v3"}, services, CancellationToken()
    )
    services = _rotation_services(services, active="v3", pending=None)
    history_plugin.invoke(
        "rotate", {"action": "finalize", "target_version": "v3"}, services, CancellationToken()
    )

    backups = history_plugin.invoke("backups", {}, services, CancellationToken())["items"]
    assert {first["backup_id"], second["backup_id"]}.issubset(
        {item["id"] for item in backups}
    )
    assert services["history"]["keys"] == {
        "v1": "11" * 32,
        "v2": "22" * 32,
        "v3": "33" * 32,
    }
