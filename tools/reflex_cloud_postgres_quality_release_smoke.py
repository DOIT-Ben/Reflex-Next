"""Bounded PostgreSQL concurrency gate for Reflex Cloud quality releases."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, BrokenBarrierError
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "reflex-cloud" / "src"))


def _load_runtime_dependencies() -> None:
    """Load database dependencies only after CLI arguments are validated."""
    global AttachmentStore, CloudService, CloudServiceError, CloudSettings
    global FeedbackItem, QualityRelease, QualityReleaseCreate
    global SecretStr, create_engine, database_from_engine, select, text

    from pydantic import SecretStr as _SecretStr
    from sqlalchemy import create_engine as _create_engine, select as _select, text as _text

    from reflex_cloud.config import CloudSettings as _CloudSettings
    from reflex_cloud.database import database_from_engine as _database_from_engine
    from reflex_cloud.models import FeedbackItem as _FeedbackItem, QualityRelease as _QualityRelease
    from reflex_cloud.schemas import QualityReleaseCreate as _QualityReleaseCreate
    from reflex_cloud.service import CloudService as _CloudService, CloudServiceError as _CloudServiceError
    from reflex_cloud.storage import AttachmentStore as _AttachmentStore

    SecretStr = _SecretStr
    create_engine = _create_engine
    database_from_engine = _database_from_engine
    select = _select
    text = _text
    CloudSettings = _CloudSettings
    FeedbackItem = _FeedbackItem
    QualityRelease = _QualityRelease
    QualityReleaseCreate = _QualityReleaseCreate
    CloudService = _CloudService
    CloudServiceError = _CloudServiceError
    AttachmentStore = _AttachmentStore


DATABASE_URL_ENV = "REFLEX_CLOUD_POSTGRES_TEST_URL"
DATABASE_NAME_PATTERN = re.compile(
    r"^reflex_cloud_(?:test|qa|ci)(?:_[a-z0-9][a-z0-9_]{0,31})?$"
)
SCHEMA_NAME_PATTERN = re.compile(r"^reflex_quality_smoke_[a-f0-9]{20}$")
ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
OUTPUT_FIELDS = (
    "schema_version",
    "operation",
    "classification",
    "same_release_successes",
    "different_release_successes",
    "rollback_successes",
    "published_count",
    "unique_index_verified",
    "schema_cleanup",
    "error_code",
)


class SmokeFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code if ERROR_CODE_PATTERN.fullmatch(code) else "smoke_failed"
        super().__init__(self.code)


class SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise SmokeFailure("invalid_arguments")


def _record(
    classification: str,
    *,
    same_release_successes: int = 0,
    different_release_successes: int = 0,
    rollback_successes: int = 0,
    published_count: int = 0,
    unique_index_verified: bool = False,
    schema_cleanup: bool = False,
    error_code: str | None = None,
) -> dict[str, Any]:
    value = {
        "schema_version": 1,
        "operation": "cloud_postgres_quality_release",
        "classification": classification,
        "same_release_successes": max(0, int(same_release_successes)),
        "different_release_successes": max(0, int(different_release_successes)),
        "rollback_successes": max(0, int(rollback_successes)),
        "published_count": max(0, int(published_count)),
        "unique_index_verified": bool(unique_index_verified),
        "schema_cleanup": bool(schema_cleanup),
        "error_code": (
            error_code
            if error_code is not None and ERROR_CODE_PATTERN.fullmatch(error_code)
            else None
        ),
    }
    return {field: value[field] for field in OUTPUT_FIELDS}


def _emit(record: dict[str, Any]) -> None:
    print(json.dumps(record, ensure_ascii=True, separators=(",", ":")), flush=True)


def _validated_database_url(value: str, *, allow_remote: bool) -> URL:
    if not value or len(value) > 2_048:
        raise SmokeFailure("database_url_missing")
    from sqlalchemy.engine import make_url

    try:
        url = make_url(value)
    except Exception as error:
        raise SmokeFailure("database_url_invalid") from error
    if url.drivername != "postgresql+psycopg":
        raise SmokeFailure("database_driver_invalid")
    if not url.database or not DATABASE_NAME_PATTERN.fullmatch(url.database):
        raise SmokeFailure("database_name_unsafe")
    host = (url.host or "").lower()
    if not allow_remote and host not in LOOPBACK_HOSTS:
        raise SmokeFailure("remote_database_refused")
    return url


def _database_url_from_environment(
    environment: Mapping[str, str], *, allow_remote: bool
) -> URL:
    return _validated_database_url(
        environment.get(DATABASE_URL_ENV, ""), allow_remote=allow_remote
    )


def _new_schema_name() -> str:
    return f"reflex_quality_smoke_{uuid4().hex[:20]}"


def _schema_database(base_url: URL, schema: str, timeout_seconds: int) -> Database:
    if not SCHEMA_NAME_PATTERN.fullmatch(schema):
        raise SmokeFailure("schema_name_invalid")
    query = dict(base_url.query)
    timeout_ms = timeout_seconds * 1_000
    query.update(
        {
            "connect_timeout": "5",
            "options": (
                f"-csearch_path={schema} "
                f"-cstatement_timeout={timeout_ms} -clock_timeout=5000"
            ),
        }
    )
    engine = create_engine(
        base_url.set(query=query),
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=0,
    )
    return database_from_engine(engine)


def _settings(upload_directory: Path) -> CloudSettings:
    return CloudSettings(
        _env_file=None,
        environment="test",
        upload_directory=upload_directory,
        admin_token=SecretStr("a" * 32),
        token_pepper=SecretStr("p" * 32),
    )


def _feedback(installation_id: str, index: int, policy_version: str) -> FeedbackItem:
    return FeedbackItem(
        id=str(uuid4()),
        installation_id=installation_id,
        sentiment="negative",
        category="quality",
        status="fixed",
        message="quality fixture",
        expected_output="",
        contact="",
        app_version="0.0.0-smoke",
        os_version="test",
        provider="minimax",
        model="fixture-model",
        mode="content",
        style="balanced",
        scene="general",
        request_id=f"smoke-request-{index}",
        diagnostic_id="",
        error_code="",
        elapsed_ms=1,
        include_prompt=False,
        include_result=False,
        include_screenshot=False,
        prompt_text=None,
        result_text=None,
        screenshot_path=None,
        screenshot_media_type=None,
        consent_version=policy_version,
    )


def _create_draft(
    database: Database,
    service: CloudService,
    installation_id: str,
    index: int,
) -> str:
    with database.sessions() as session:
        source = _feedback(installation_id, index, service.settings.privacy_policy_version)
        session.add(source)
        session.commit()
        release = service.create_quality_release(
            session,
            QualityReleaseCreate(
                release_version=f"1.0.{index}",
                template_pack_version="1.0.0",
                title=f"Quality smoke {index}",
                summary="Bounded PostgreSQL concurrency fixture.",
                global_guidance="Preserve explicit constraints.",
                source_feedback_ids=[source.id],
            ),
        )
        return release.id


def _run_operation(
    database: Database,
    barrier: Barrier,
    operation: Callable[[Any], object],
) -> str:
    try:
        barrier.wait(timeout=5)
    except BrokenBarrierError:
        return "concurrency_barrier_failed"
    try:
        with database.sessions() as session:
            operation(session)
    except CloudServiceError as error:
        return error.code
    except Exception:
        return "database_operation_failed"
    return "ok"


def _run_pair(
    left_database: Database,
    right_database: Database,
    left_operation: Callable[[Any], object],
    right_operation: Callable[[Any], object],
    timeout_seconds: int,
) -> list[str]:
    barrier = Barrier(2)
    pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="quality-smoke")
    futures = (
        pool.submit(_run_operation, left_database, barrier, left_operation),
        pool.submit(_run_operation, right_database, barrier, right_operation),
    )
    deadline = time.monotonic() + timeout_seconds
    try:
        results: list[str] = []
        for future in futures:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            results.append(future.result(timeout=remaining))
        return results
    except TimeoutError as error:
        for future in futures:
            future.cancel()
        # ``Future.cancel`` cannot stop a thread that is already running.  The
        # per-connection PostgreSQL statement timeout is the cooperative stop
        # boundary; wait for every worker before the caller closes engines or
        # drops the temporary schema, otherwise cleanup can race an in-flight
        # transaction.  This timeout is therefore an operation deadline, not
        # an unsafe promise that Python threads can be force-killed.
        for future in futures:
            if future.cancelled():
                continue
            try:
                future.result()
            except Exception:
                pass
        raise SmokeFailure("database_operation_timeout") from error
    finally:
        pool.shutdown(wait=True, cancel_futures=True)


def _published_release_id(database: Database) -> str:
    with database.sessions() as session:
        ids = list(
            session.scalars(
                select(QualityRelease.id).where(QualityRelease.status == "published")
            )
        )
    if len(ids) != 1:
        raise SmokeFailure("published_release_invariant_failed")
    return ids[0]


def _published_count(database: Database) -> int:
    with database.sessions() as session:
        return len(
            list(
                session.scalars(
                    select(QualityRelease.id).where(
                        QualityRelease.status == "published"
                    )
                )
            )
        )


def _verify_unique_index(database: Database) -> bool:
    statement = text(
        """
        SELECT idx.indisunique, pg_get_expr(idx.indpred, idx.indrelid)
        FROM pg_class table_class
        JOIN pg_namespace namespace ON namespace.oid = table_class.relnamespace
        JOIN pg_index idx ON idx.indrelid = table_class.oid
        JOIN pg_class index_class ON index_class.oid = idx.indexrelid
        WHERE namespace.nspname = current_schema()
          AND table_class.relname = 'quality_releases'
          AND index_class.relname = 'quality_release_one_published_uq'
        """
    )
    with database.engine.connect() as connection:
        row = connection.execute(statement).one_or_none()
    if row is None:
        return False
    predicate = str(row[1] or "").lower()
    return bool(row[0]) and "status" in predicate and "published" in predicate


def _assert_results(
    results: list[str],
    *,
    minimum_successes: int,
    maximum_successes: int,
    allowed_errors: frozenset[str],
    failure_code: str,
) -> int:
    successes = results.count("ok")
    if not minimum_successes <= successes <= maximum_successes:
        raise SmokeFailure(failure_code)
    if any(result != "ok" and result not in allowed_errors for result in results):
        raise SmokeFailure(failure_code)
    return successes


def _run_smoke(base_url: URL, timeout_seconds: int) -> dict[str, Any]:
    _load_runtime_dependencies()
    schema = _new_schema_name()
    if not SCHEMA_NAME_PATTERN.fullmatch(schema):
        raise SmokeFailure("schema_name_invalid")
    admin_timeout_ms = timeout_seconds * 1_000
    admin_engine = create_engine(
        base_url.set(
            query={
                **dict(base_url.query),
                "connect_timeout": "5",
                "options": (
                    f"-cstatement_timeout={admin_timeout_ms} -clock_timeout=5000"
                ),
            }
        ),
        pool_pre_ping=True,
        pool_size=1,
        max_overflow=0,
    )
    schema_created = False
    cleanup = False
    left_database: Database | None = None
    right_database: Database | None = None
    metrics: dict[str, Any] = {}
    failure: SmokeFailure | None = None
    database_close_ok = True

    try:
        with admin_engine.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        schema_created = True
        left_database = _schema_database(base_url, schema, timeout_seconds)
        right_database = _schema_database(base_url, schema, timeout_seconds)
        left_database.create_schema()

        with tempfile.TemporaryDirectory(prefix="reflex-cloud-quality-smoke-") as root:
            settings = _settings(Path(root))
            left_service = CloudService(
                settings, AttachmentStore(Path(root) / "left", settings.max_screenshot_bytes)
            )
            right_service = CloudService(
                settings, AttachmentStore(Path(root) / "right", settings.max_screenshot_bytes)
            )
            with left_database.sessions() as session:
                installation, _ = left_service.create_installation(session)

            same_release = _create_draft(
                left_database, left_service, installation.id, 1
            )
            same_results = _run_pair(
                left_database,
                right_database,
                lambda session: left_service.publish_quality_release(
                    session, same_release
                ),
                lambda session: right_service.publish_quality_release(
                    session, same_release
                ),
                timeout_seconds,
            )
            same_successes = _assert_results(
                same_results,
                minimum_successes=1,
                maximum_successes=1,
                allowed_errors=frozenset(
                    {
                        "quality_release_state_invalid",
                        "quality_release_publish_conflict",
                    }
                ),
                failure_code="same_release_concurrency_failed",
            )
            _published_release_id(left_database)

            left_release = _create_draft(
                left_database, left_service, installation.id, 2
            )
            right_release = _create_draft(
                left_database, left_service, installation.id, 3
            )
            different_results = _run_pair(
                left_database,
                right_database,
                lambda session: left_service.publish_quality_release(
                    session, left_release
                ),
                lambda session: right_service.publish_quality_release(
                    session, right_release
                ),
                timeout_seconds,
            )
            different_successes = _assert_results(
                different_results,
                minimum_successes=1,
                maximum_successes=2,
                allowed_errors=frozenset({"quality_release_publish_conflict"}),
                failure_code="different_release_concurrency_failed",
            )
            active_release = _published_release_id(left_database)

            rollback_results = _run_pair(
                left_database,
                right_database,
                lambda session: left_service.rollback_quality_release(
                    session, active_release
                ),
                lambda session: right_service.rollback_quality_release(
                    session, active_release
                ),
                timeout_seconds,
            )
            rollback_successes = _assert_results(
                rollback_results,
                minimum_successes=1,
                maximum_successes=1,
                allowed_errors=frozenset(
                    {
                        "quality_release_state_invalid",
                        "quality_release_publish_conflict",
                    }
                ),
                failure_code="rollback_concurrency_failed",
            )
            published_count = _published_count(left_database)
            if published_count != 1:
                raise SmokeFailure("rollback_invariant_failed")
            unique_index_verified = _verify_unique_index(left_database)
            if not unique_index_verified:
                raise SmokeFailure("quality_release_index_missing")
            metrics = {
                "same_release_successes": same_successes,
                "different_release_successes": different_successes,
                "rollback_successes": rollback_successes,
                "published_count": published_count,
                "unique_index_verified": True,
            }
    except SmokeFailure as error:
        failure = error
    except Exception:
        failure = SmokeFailure("postgres_smoke_failed")
    finally:
        if left_database is not None:
            try:
                left_database.close()
            except Exception:
                database_close_ok = False
        if right_database is not None:
            try:
                right_database.close()
            except Exception:
                database_close_ok = False
        if schema_created:
            try:
                with admin_engine.begin() as connection:
                    connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
                cleanup = True
            except Exception:
                cleanup = False
        admin_engine.dispose()

    if schema_created and not cleanup:
        failure = SmokeFailure("schema_cleanup_failed")
    elif not database_close_ok and failure is None:
        failure = SmokeFailure("database_cleanup_failed")
    if failure is not None:
        return _record(
            "error", schema_cleanup=cleanup, error_code=failure.code, **metrics
        )
    return _record("success", schema_cleanup=cleanup, **metrics)


def _parse_arguments(arguments: list[str] | None) -> argparse.Namespace:
    parser = SafeArgumentParser(
        description="Verify Reflex Cloud quality release concurrency on PostgreSQL."
    )
    parser.add_argument("--allow-remote-test-database", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=20)
    values = parser.parse_args(arguments)
    if not 5 <= values.timeout_seconds <= 60:
        raise SmokeFailure("invalid_arguments")
    return values


def main(arguments: list[str] | None = None) -> int:
    try:
        values = _parse_arguments(arguments)
        database_url = _database_url_from_environment(
            os.environ, allow_remote=values.allow_remote_test_database
        )
        record = _run_smoke(database_url, values.timeout_seconds)
    except SmokeFailure as error:
        record = _record("error", error_code=error.code)
    except Exception:
        record = _record("error", error_code="postgres_smoke_failed")
    _emit(record)
    return 0 if record["classification"] == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
