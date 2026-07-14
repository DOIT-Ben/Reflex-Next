from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import provider_smoke


TOOL = ROOT / "tools" / "provider_smoke.py"
FIXTURE = ROOT / "tools" / "tests" / "fixtures" / "provider_smoke_runtime.py"
OVERSIZED_FIXTURE = (
    ROOT / "tools" / "tests" / "fixtures" / "provider_smoke_oversized_runtime.py"
)
ALLOWED_FIELDS = {
    "operation",
    "provider_id",
    "model_id",
    "classification",
    "first_status_ms",
    "first_chunk_ms",
    "total_ms",
    "chunk_count",
    "cancel_latency_ms",
    "error_code",
}
PRIVATE_VALUES = {
    "fixture-smoke-private-credential",
    "fixture-private-response-body",
    "fixture-private-late-body",
    "https://fixture.invalid/v1/chat/completions",
    "Authorization",
    "Bearer",
}


class ProviderSmokeContractTests(unittest.TestCase):
    def run_tool(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(TOOL),
                "--fixture-runtime",
                str(FIXTURE),
                *arguments,
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=10,
            check=False,
        )

    def parse_output(self, result: subprocess.CompletedProcess[str]) -> list[dict]:
        self.assertEqual(result.stderr, "")
        records = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
        self.assertTrue(records)
        for record in records:
            self.assertEqual(set(record), ALLOWED_FIELDS)
            self.assertRegex(record["provider_id"], r"^[a-z0-9_.-]{1,64}$")
            self.assertRegex(record["model_id"], r"^[A-Za-z0-9_.:/-]{1,128}$")
        visible = result.stdout + result.stderr
        for private_value in PRIVATE_VALUES:
            self.assertNotIn(private_value, visible)
        return records

    def test_all_mode_reports_catalog_stream_and_cancel_without_private_content(self):
        started = time.monotonic()
        result = self.run_tool("--operation", "all", "--cancel-after-ms", "10")
        elapsed = time.monotonic() - started

        self.assertEqual(result.returncode, 0, result.stdout)
        records = self.parse_output(result)
        self.assertEqual([record["operation"] for record in records], ["list", "stream", "cancel"])
        self.assertEqual([record["classification"] for record in records], ["catalog_ok", "success", "cancelled"])
        self.assertGreaterEqual(records[1]["chunk_count"], 1)
        self.assertIsInstance(records[1]["first_status_ms"], int)
        self.assertIsInstance(records[1]["first_chunk_ms"], int)
        self.assertIsInstance(records[2]["cancel_latency_ms"], int)
        self.assertEqual(records[2]["error_code"], None)
        self.assertGreaterEqual(elapsed, 0.5)

    def test_list_mode_uses_the_runtime_provider_catalog(self):
        result = self.run_tool("--operation", "list")

        self.assertEqual(result.returncode, 0, result.stdout)
        record = self.parse_output(result)[0]
        self.assertEqual(record["provider_id"], "minimax")
        self.assertEqual(record["model_id"], "fixture-model")
        self.assertEqual(record["classification"], "catalog_ok")

    def test_model_ids_with_provider_scopes_are_accepted(self):
        self.assertIsNotNone(provider_smoke.MODEL_ID_PATTERN.fullmatch("deepseek-ai/DeepSeek-V3"))

    def test_untrusted_provider_and_model_are_rejected_with_fixed_safe_codes(self):
        provider = self.run_tool("--operation", "list", "--provider", "unknown")
        model = self.run_tool("--operation", "list", "--model", "unknown-model")

        self.assertNotEqual(provider.returncode, 0)
        self.assertEqual(self.parse_output(provider)[0]["error_code"], "provider_not_trusted")
        self.assertNotEqual(model.returncode, 0)
        self.assertEqual(self.parse_output(model)[0]["error_code"], "model_not_trusted")

    def test_runtime_failure_keeps_only_the_stable_error_code(self):
        result = self.run_tool("--operation", "stream", "--provider", "failure")

        self.assertEqual(result.returncode, 1)
        records = self.parse_output(result)
        self.assertEqual(records[-1]["classification"], "error")
        self.assertEqual(records[-1]["error_code"], "auth_error")

    def test_legacy_runtime_protocol_is_reported_with_a_stable_safe_code(self):
        class LegacyRuntime:
            def send(self, _request_id, _command_type, _payload):
                pass

            def receive(self, request_id, _timeout):
                return {
                    "version": 1,
                    "request_id": request_id,
                    "event": {
                        "type": "error",
                        "data": {
                            "code": "protocol_error",
                            "message": "fixture-private-response-body",
                        },
                    },
                }

        with self.assertRaises(provider_smoke.SmokeFailure) as failure:
            provider_smoke._list_catalog(LegacyRuntime(), 1)

        self.assertEqual(failure.exception.code, "runtime_contract_outdated")

    def test_late_chunk_or_done_after_cancel_is_rejected(self):
        for provider_id in ("late-chunk", "late-done"):
            with self.subTest(provider_id=provider_id):
                result = self.run_tool(
                    "--operation",
                    "cancel",
                    "--provider",
                    provider_id,
                    "--cancel-after-ms",
                    "10",
                )

                self.assertEqual(result.returncode, 2)
                records = self.parse_output(result)
                self.assertEqual(records[-1]["classification"], "tool_error")
                self.assertEqual(records[-1]["error_code"], "late_event_after_cancel")

    def test_oversized_runtime_line_is_rejected_and_process_is_terminated(self):
        runtime = provider_smoke.RuntimeProcess(
            [sys.executable, str(OVERSIZED_FIXTURE)], cwd=ROOT
        )
        try:
            runtime.send("smoke-list-providers", "list_providers", {})
            with self.assertRaises(provider_smoke.SmokeFailure) as failure:
                runtime.receive("smoke-list-providers", 3)
            self.assertEqual(failure.exception.code, "invalid_runtime_output")
            deadline = time.monotonic() + 2
            while runtime._process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertIsNotNone(runtime._process.poll())
        finally:
            runtime.close()

    def test_cli_has_no_plaintext_secret_prompt_or_endpoint_options(self):
        for forbidden_option in ["--key", "--secret", "--prompt", "--endpoint", "--base-url"]:
            result = subprocess.run(
                [sys.executable, str(TOOL), forbidden_option, "fixture-private-value"],
                cwd=ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                timeout=5,
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("fixture-private-value", result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
