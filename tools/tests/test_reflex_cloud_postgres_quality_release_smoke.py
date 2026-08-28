from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import reflex_cloud_postgres_quality_release_smoke as smoke


TOOL = ROOT / "tools" / "reflex_cloud_postgres_quality_release_smoke.py"
WRAPPER = ROOT / "tools" / "verify_cloud_postgres_quality_release.ps1"


class ReflexCloudPostgresQualityReleaseSmokeContractTests(unittest.TestCase):
    def test_accepts_only_explicit_postgres_test_databases(self):
        accepted = smoke._validated_database_url(
            "postgresql+psycopg://fixture:test@127.0.0.1:5432/reflex_cloud_test",
            allow_remote=False,
        )
        self.assertEqual(accepted.database, "reflex_cloud_test")

        rejected = (
            ("sqlite:///reflex_cloud_test.db", "database_driver_invalid"),
            (
                "postgresql+psycopg://fixture:test@127.0.0.1/reflex_cloud",
                "database_name_unsafe",
            ),
            (
                "postgresql+psycopg://fixture:test@db.example/reflex_cloud_test",
                "remote_database_refused",
            ),
        )
        for value, code in rejected:
            with self.subTest(code=code):
                with self.assertRaises(smoke.SmokeFailure) as failure:
                    smoke._validated_database_url(value, allow_remote=False)
                self.assertEqual(failure.exception.code, code)

    def test_remote_database_requires_an_explicit_flag(self):
        value = "postgresql+psycopg://fixture:test@db.example/reflex_cloud_qa"
        accepted = smoke._validated_database_url(value, allow_remote=True)
        self.assertEqual(accepted.host, "db.example")

    def test_generated_schema_and_report_are_strict_and_redacted(self):
        schema = smoke._new_schema_name()
        self.assertRegex(schema, smoke.SCHEMA_NAME_PATTERN)
        report = smoke._record(
            "success",
            same_release_successes=1,
            different_release_successes=2,
            rollback_successes=1,
            published_count=1,
            unique_index_verified=True,
            schema_cleanup=True,
        )
        self.assertEqual(set(report), set(smoke.OUTPUT_FIELDS))
        visible = json.dumps(report)
        self.assertNotIn("postgresql", visible)
        self.assertNotIn(schema, visible)
        self.assertNotIn("request", visible)

    def test_missing_database_url_returns_one_safe_error_record(self):
        environment = dict(os.environ)
        environment.pop(smoke.DATABASE_URL_ENV, None)
        result = subprocess.run(
            [sys.executable, str(TOOL)],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stderr, "")
        records = [json.loads(line) for line in result.stdout.splitlines() if line]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["error_code"], "database_url_missing")
        self.assertEqual(set(records[0]), set(smoke.OUTPUT_FIELDS))

    def test_cli_never_accepts_or_echoes_a_database_url(self):
        private_value = "fixture-private-database-value"
        result = subprocess.run(
            [sys.executable, str(TOOL), "--database-url", private_value],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(private_value, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["error_code"], "invalid_arguments")

    def test_pair_waits_for_running_workers_before_returning_timeout(self):
        class Sessions:
            def __enter__(self):
                return object()

            def __exit__(self, *_):
                return False

        class Database:
            def sessions(self):
                return Sessions()

        completed = []

        def operation(_session):
            time.sleep(0.1)
            completed.append(True)

        with self.assertRaises(smoke.SmokeFailure) as failure:
            smoke._run_pair(Database(), Database(), operation, operation, 0)

        self.assertEqual(failure.exception.code, "database_operation_timeout")
        self.assertEqual(len(completed), 2)

    def test_windows_wrapper_enforces_resource_and_cleanup_guards(self):
        source = WRAPPER.read_text(encoding="utf-8")
        for required in (
            '$minimumFreePhysicalMB = 2048',
            '$minimumFreeVirtualMB = 4096',
            'insufficient_memory_for_postgres_smoke',
            '--memory=128m',
            '--cpus=0.5',
            '127.0.0.1:${postgresPort}:5432',
            '--isolated',
            '--frozen',
            'docker stop --time 10',
            'existing_container_interrupted',
            'Start-Process',
            'smokeWatchdogSeconds = 90',
            'taskkill.exe /PID',
            'postgres_smoke_timeout',
            '"--timeout-seconds"',
        ):
            self.assertIn(required, source)


if __name__ == "__main__":
    unittest.main()
