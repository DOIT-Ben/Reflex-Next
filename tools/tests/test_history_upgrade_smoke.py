from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import history_upgrade_smoke


TOOL = ROOT / "tools" / "history_upgrade_smoke.py"


class HistoryUpgradeSmokeContractTests(unittest.TestCase):
    def test_legacy_fixture_is_v0_and_does_not_contain_plaintext_bodies(self):
        with tempfile.TemporaryDirectory(prefix="reflex-history-contract-") as temporary:
            database, record_id = history_upgrade_smoke._create_legacy_database(Path(temporary))
            raw = database.read_bytes()
            self.assertEqual(record_id, history_upgrade_smoke.LEGACY_RECORD_ID)
            self.assertNotIn(history_upgrade_smoke.LEGACY_INPUT.encode(), raw)
            self.assertNotIn(history_upgrade_smoke.LEGACY_OUTPUT.encode(), raw)
            import sqlite3

            connection = sqlite3.connect(database)
            try:
                self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 0)
                self.assertEqual(
                    connection.execute("SELECT value FROM legacy_marker").fetchone()[0],
                    "preserved",
                )
            finally:
                connection.close()

    def test_output_schema_is_bounded_and_redacted(self):
        record = history_upgrade_smoke._record(
            "minimax",
            "MiniMax-M2.7-highspeed",
            "success",
            legacy_schema=0,
            current_schema=1,
            backup_schema=0,
            legacy_detail_read=True,
            new_record_saved=True,
            list_read=True,
        )
        self.assertEqual(set(record), set(history_upgrade_smoke.OUTPUT_FIELDS))
        self.assertNotIn(history_upgrade_smoke.FIXTURE_KEY_HEX, json.dumps(record))
        self.assertNotIn(history_upgrade_smoke.LEGACY_INPUT, json.dumps(record))

    def test_cli_does_not_accept_plaintext_secret_options(self):
        result = subprocess.run(
            [sys.executable, str(TOOL), "--secret", "fixture-private-value"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn("fixture-private-value", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
