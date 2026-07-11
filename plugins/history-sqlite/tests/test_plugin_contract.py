from __future__ import annotations

import importlib

from reflex_history_sqlite.contract import HistorySaveSnapshot, HistoryServiceSnapshot


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


def test_import_and_plugin_materialization_have_no_filesystem_side_effects(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    module = importlib.import_module("reflex_history_sqlite")
    instance = module.plugin()

    assert list(tmp_path.iterdir()) == []
    assert instance.descriptor.plugin_id == "history-sqlite"
    assert instance.descriptor.kind == "storage"
    assert instance.descriptor.permissions == ("storage_read", "storage_write")
    assert instance.descriptor.operations == HISTORY_OPERATIONS
    assert instance.descriptor.public_operations == HISTORY_PUBLIC_OPERATIONS


def test_plugin_repr_does_not_expose_runtime_configuration():
    module = importlib.import_module("reflex_history_sqlite")

    rendered = repr(module.plugin())

    assert "key" not in rendered.casefold()
    assert "path" not in rendered.casefold()


def test_private_snapshot_reprs_do_not_expose_key_path_or_body(
    history_services, make_snapshot
):
    service_snapshot = HistoryServiceSnapshot.from_services(history_services)
    save_snapshot = HistorySaveSnapshot.from_payload(
        make_snapshot(input="private input body", output="private output body")
    )
    private_values = (
        str(history_services["history"]["database_path"]),
        history_services["history"]["keys"]["v1"],
        "private input body",
        "private output body",
    )

    rendered = " ".join(
        (repr(service_snapshot), repr(service_snapshot.keys), repr(save_snapshot))
    )

    assert all(value not in rendered for value in private_values)
    assert "redacted" in rendered.casefold()
