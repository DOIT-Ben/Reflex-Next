from __future__ import annotations

from sqlalchemy import inspect, text

from reflex_cloud.database import Database
from reflex_cloud.models import Base


def test_create_schema_adds_feedback_source_to_legacy_database(tmp_path):
    database = Database(f"sqlite:///{tmp_path / 'legacy-cloud.db'}")
    Base.metadata.create_all(database.engine)
    with database.engine.begin() as connection:
        connection.execute(text("ALTER TABLE feedback_items DROP COLUMN source"))

    assert "source" not in {
        column["name"] for column in inspect(database.engine).get_columns("feedback_items")
    }

    database.create_schema()

    columns = {
        column["name"] for column in inspect(database.engine).get_columns("feedback_items")
    }
    assert "source" in columns
    database.close()
