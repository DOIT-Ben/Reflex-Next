from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import cross_version_history_upgrade_smoke as cross_version


TOOL = ROOT / "tools" / "cross_version_history_upgrade_smoke.py"


class CrossVersionHistoryUpgradeContractTests(unittest.TestCase):
    def test_success_output_is_bounded_and_contains_no_fixture_secret(self):
        record = cross_version._record(
            "success",
            legacy_schema=1,
            current_schema=1,
            backup_schema=1,
            legacy_layout="legacy",
            current_layout=3,
            legacy_detail_read=True,
            legacy_list_read=True,
            new_record_saved=True,
            migration_backup_preserved=True,
        )
        self.assertEqual(set(record), set(cross_version.OUTPUT_FIELDS))
        encoded = json.dumps(record)
        self.assertNotIn(cross_version.FIXTURE_KEY_HEX, encoded)
        self.assertNotIn("legacy input fixture", encoded)
        self.assertNotIn("legacy output fixture", encoded)

    def test_cli_rejects_plaintext_secret_and_body_options(self):
        for forbidden in ("--secret", "--key", "--prompt", "--endpoint", "--base-url"):
            result = subprocess.run(
                [sys.executable, str(TOOL), forbidden, "fixture-private-value"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=5,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("fixture-private-value", result.stdout + result.stderr)

    def test_invalid_timeout_is_a_fixed_error(self):
        result = subprocess.run(
            [
                sys.executable,
                str(TOOL),
                "--legacy-runtime",
                "fixture-runtime.exe",
                "--timeout-seconds",
                "1",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=5,
            check=False,
        )
        self.assertEqual(result.returncode, 2)
        record = json.loads(result.stdout)
        self.assertEqual(record["error_code"], "invalid_arguments")
        self.assertEqual(set(record), set(cross_version.OUTPUT_FIELDS))


if __name__ == "__main__":
    unittest.main()
