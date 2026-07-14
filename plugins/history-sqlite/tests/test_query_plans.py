from __future__ import annotations

import sqlite3
from threading import RLock

from reflex_core import CancellationToken
from reflex_history_sqlite.contract import HistoryServiceSnapshot
from reflex_history_sqlite.repository import HistoryRepository


def _plan(connection: sqlite3.Connection, sql: str, parameters=()) -> str:
    return "\n".join(
        row[3] for row in connection.execute("EXPLAIN QUERY PLAN " + sql, parameters)
    )


def _assert_indexed_without_temp_sort(plan: str, index_name: str) -> None:
    assert index_name in plan
    assert "USE TEMP B-TREE" not in plan


def test_schema_uses_six_query_specific_indexes(
    history_plugin, history_services, make_snapshot
):
    history_plugin.invoke(
        "save", make_snapshot(), history_services, CancellationToken()
    )
    connection = sqlite3.connect(history_services["history"]["database_path"])
    try:
        indexes = dict(
            connection.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type = 'index' AND tbl_name = 'history_records' "
                "AND sql IS NOT NULL"
            )
        )
    finally:
        connection.close()

    assert set(indexes) == {
        "history_records_created_at_idx",
        "history_records_provider_idx",
        "history_records_scene_idx",
        "history_records_style_idx",
        "history_records_rating_idx",
        "history_records_status_idx",
    }
    assert "(created_at, id)" in indexes["history_records_created_at_idx"]
    assert "(key_version, id, status)" in indexes["history_records_status_idx"]


def test_ordinary_schema_ensure_returns_without_index_ddl(
    history_plugin, history_services, make_snapshot
):
    history_plugin.invoke(
        "save", make_snapshot(), history_services, CancellationToken()
    )
    repository = HistoryRepository(
        HistoryServiceSnapshot.from_services(history_services), schema_lock=RLock()
    )
    connection = repository._open_connection(read_only=False)
    statements: list[str] = []
    connection.set_trace_callback(statements.append)
    try:
        repository._ensure_schema(connection)
    finally:
        connection.close()

    assert not any(
        statement.lstrip().upper().startswith(("CREATE INDEX", "DROP INDEX"))
        for statement in statements
    )


def test_created_at_and_filtered_pagination_avoid_temp_sort(
    history_plugin, history_services, make_snapshot
):
    history_plugin.invoke(
        "save", make_snapshot(), history_services, CancellationToken()
    )
    connection = sqlite3.connect(history_services["history"]["database_path"])
    try:
        created_plan = _plan(
            connection,
            "SELECT id FROM history_records ORDER BY created_at ASC, id ASC LIMIT ?",
            (50,),
        )
        provider_plan = _plan(
            connection,
            "SELECT id FROM history_records WHERE provider = ? LIMIT ?",
            ("minimax", 50),
        )
    finally:
        connection.close()

    _assert_indexed_without_temp_sort(
        created_plan, "history_records_created_at_idx"
    )
    _assert_indexed_without_temp_sort(provider_plan, "history_records_provider_idx")


def test_rating_order_and_rotation_batches_use_covering_indexes(
    history_plugin, history_services, make_snapshot
):
    history_plugin.invoke(
        "save", make_snapshot(), history_services, CancellationToken()
    )
    connection = sqlite3.connect(history_services["history"]["database_path"])
    try:
        rating_plan = _plan(
            connection,
            "SELECT id FROM history_records "
            "ORDER BY rating IS NULL ASC, rating ASC, id ASC LIMIT ?",
            (50,),
        )
        rotation_plan = _plan(
            connection,
            "SELECT id FROM history_records WHERE key_version != ? "
            "ORDER BY key_version, id LIMIT ?",
            (2, 25),
        )
    finally:
        connection.close()

    _assert_indexed_without_temp_sort(
        rating_plan, "history_records_rating_idx"
    )
    _assert_indexed_without_temp_sort(
        rotation_plan, "history_records_status_idx"
    )
