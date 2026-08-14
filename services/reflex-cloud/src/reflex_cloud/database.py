from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


class Database:
    def __init__(self, url: str) -> None:
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, pool_pre_ping=True, connect_args=connect_args)
        if url.startswith("sqlite"):
            event.listen(self.engine, "connect", _enable_sqlite_foreign_keys)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)

    def create_schema(self) -> None:
        Base.metadata.create_all(self.engine)
        self._upgrade_feedback_source()

    def _upgrade_feedback_source(self) -> None:
        columns = {
            column["name"]
            for column in inspect(self.engine).get_columns("feedback_items")
        }
        if "source" in columns:
            return
        statement = (
            "ALTER TABLE feedback_items ADD COLUMN IF NOT EXISTS "
            "source VARCHAR(16) NOT NULL DEFAULT 'manual'"
            if self.engine.dialect.name == "postgresql"
            else "ALTER TABLE feedback_items ADD COLUMN "
            "source VARCHAR(16) NOT NULL DEFAULT 'manual'"
        )
        with self.engine.begin() as connection:
            connection.execute(text(statement))

    def ping(self) -> bool:
        with self.engine.connect() as connection:
            return connection.execute(text("SELECT 1")).scalar_one() == 1

    def session(self) -> Iterator[Session]:
        with self.sessions() as session:
            yield session

    def close(self) -> None:
        self.engine.dispose()


def _enable_sqlite_foreign_keys(connection: object, _: object) -> None:
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def database_from_engine(engine: Engine) -> Database:
    database = object.__new__(Database)
    database.engine = engine
    database.sessions = sessionmaker(engine, expire_on_commit=False)
    return database
