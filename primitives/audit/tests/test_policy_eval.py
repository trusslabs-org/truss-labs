"""Tests for primitives.audit.policy_eval (CLI dry-run)."""

from __future__ import annotations

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from audit.policy_eval import main  # noqa: E402


# Path to the shipped phi taxonomy. Tests use it directly so we exercise
# the same recognizers operators run.
_REPO_ROOT = Path(__file__).resolve().parents[3]
PHI_TAXONOMY = _REPO_ROOT / "primitives" / "audit" / "taxonomies" / "phi.yaml"


BLOCK_POLICY_YAML = """\
schema_version: "1.0"
policy_id: phi_block_address_in_external_prompt
policy_version: v1.0
match:
  direction: prompt
  destination: external_vendor
  classes:
    any_of:
      - phi:patient_address
verdict: block
block_config:
  user_message: "Patient address detected; blocked per HIPAA review."
audit_only: false
on_classifier_error: fail_open
"""


REDACT_POLICY_YAML = """\
schema_version: "1.0"
policy_id: phi_redact_dob_in_response
policy_version: v1.0
match:
  direction: response
  destination: any
  classes:
    any_of:
      - phi:patient_dob
verdict: redact
redact_config:
  redact_with: "[REDACTED:{class}]"
audit_only: false
on_classifier_error: fail_open
"""


class CLIBase(unittest.TestCase):
    """Shared setup: a tmpdir of two demo policies + capture stdout/stderr."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.policies_dir = Path(self.tmp.name)
        (self.policies_dir / "block.yaml").write_text(BLOCK_POLICY_YAML)
        (self.policies_dir / "redact.yaml").write_text(REDACT_POLICY_YAML)

        self._stdout = sys.stdout
        self._stderr = sys.stderr
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()

    def tearDown(self) -> None:
        self.tmp.cleanup()
        self.captured_stdout = sys.stdout.getvalue()
        self.captured_stderr = sys.stderr.getvalue()
        sys.stdout = self._stdout
        sys.stderr = self._stderr


class HappyPath(CLIBase):
    def test_prompt_with_address_blocks(self) -> None:
        rc = main(
            [
                "--policies",
                str(self.policies_dir),
                "--taxonomy",
                str(PHI_TAXONOMY),
                "--prompt",
                "Patient lives at 1234 Main St.",
                "--destination",
                "external_vendor",
            ]
        )
        self.assertEqual(rc, 0)
        out = sys.stdout.getvalue()
        self.assertIn("BLOCKED", out)
        self.assertIn("phi_block_address_in_external_prompt", out)
        self.assertIn("Patient address detected", out)

    def test_response_with_dob_redacts(self) -> None:
        rc = main(
            [
                "--policies",
                str(self.policies_dir),
                "--taxonomy",
                str(PHI_TAXONOMY),
                "--response",
                "DOB 1978-04-12 on file.",
            ]
        )
        self.assertEqual(rc, 0)
        out = sys.stdout.getvalue()
        self.assertIn("REDACTED", out)
        self.assertIn("[REDACTED:phi:patient_dob]", out)

    def test_benign_text_passes_allowed(self) -> None:
        rc = main(
            [
                "--policies",
                str(self.policies_dir),
                "--taxonomy",
                str(PHI_TAXONOMY),
                "--prompt",
                "What is the mitochondrial role in cellular respiration?",
            ]
        )
        self.assertEqual(rc, 0)
        out = sys.stdout.getvalue()
        self.assertIn("ALLOWED", out)
        self.assertIn("(synthetic)", out)  # synthetic null-policy_id entry

    def test_both_phases_evaluated(self) -> None:
        rc = main(
            [
                "--policies",
                str(self.policies_dir),
                "--taxonomy",
                str(PHI_TAXONOMY),
                "--prompt",
                "Patient lives at 1234 Main St.",
                "--response",
                "DOB 1978-04-12 noted.",
            ]
        )
        self.assertEqual(rc, 0)
        out = sys.stdout.getvalue()
        self.assertIn("=== PROMPT phase ===", out)
        self.assertIn("=== RESPONSE phase ===", out)
        self.assertIn("BLOCKED", out)
        self.assertIn("REDACTED", out)


class JsonOutput(CLIBase):
    def test_json_output_is_valid(self) -> None:
        rc = main(
            [
                "--policies",
                str(self.policies_dir),
                "--taxonomy",
                str(PHI_TAXONOMY),
                "--prompt",
                "Patient lives at 1234 Main St.",
                "--json",
            ]
        )
        self.assertEqual(rc, 0)
        payload = json.loads(sys.stdout.getvalue())
        self.assertIn("policy_set_version", payload)
        self.assertIn("prompt", payload["phases"])
        self.assertEqual(payload["phases"]["prompt"]["final_verdict"], "blocked")

    def test_json_carries_v11_fields(self) -> None:
        # JSON output must surface every v1.1 receipt field.
        rc = main(
            [
                "--policies",
                str(self.policies_dir),
                "--taxonomy",
                str(PHI_TAXONOMY),
                "--response",
                "DOB 1978-04-12.",
                "--json",
            ]
        )
        self.assertEqual(rc, 0)
        payload = json.loads(sys.stdout.getvalue())
        d = payload["phases"]["response"]["decisions"][0]
        for key in (
            "policy_id",
            "policy_version",
            "policy_set_version",
            "evaluated_at",
            "verdict",
            "enforcement_mode",
            "matched_classes",
            "would_have_blocked",
            "redactions_applied",
            "error_reason",
            "alert_id",
        ):
            self.assertIn(key, d)


class FileInputs(CLIBase):
    def test_prompt_file_loaded(self) -> None:
        prompt_path = Path(self.tmp.name) / "prompt.txt"
        prompt_path.write_text("Patient lives at 1234 Main St.")
        rc = main(
            [
                "--policies",
                str(self.policies_dir),
                "--taxonomy",
                str(PHI_TAXONOMY),
                "--prompt-file",
                str(prompt_path),
            ]
        )
        self.assertEqual(rc, 0)
        self.assertIn("BLOCKED", sys.stdout.getvalue())

    def test_prompt_and_prompt_file_mutually_exclusive(self) -> None:
        prompt_path = Path(self.tmp.name) / "prompt.txt"
        prompt_path.write_text("x")
        with self.assertRaises(SystemExit):
            main(
                [
                    "--policies",
                    str(self.policies_dir),
                    "--taxonomy",
                    str(PHI_TAXONOMY),
                    "--prompt",
                    "x",
                    "--prompt-file",
                    str(prompt_path),
                ]
            )

    def test_missing_prompt_file_exits(self) -> None:
        with self.assertRaises(SystemExit):
            main(
                [
                    "--policies",
                    str(self.policies_dir),
                    "--taxonomy",
                    str(PHI_TAXONOMY),
                    "--prompt-file",
                    "/nonexistent/path",
                ]
            )

    def test_neither_prompt_nor_response_exits(self) -> None:
        with self.assertRaises(SystemExit):
            main(
                [
                    "--policies",
                    str(self.policies_dir),
                    "--taxonomy",
                    str(PHI_TAXONOMY),
                ]
            )


class ErrorPaths(CLIBase):
    def test_bad_policy_dir_exits_with_1(self) -> None:
        # Override setUp's policies dir with a broken one.
        bad_policies = Path(self.tmp.name) / "bad"
        bad_policies.mkdir()
        (bad_policies / "broken.yaml").write_text(":::not yaml:::")
        rc = main(
            [
                "--policies",
                str(bad_policies),
                "--taxonomy",
                str(PHI_TAXONOMY),
                "--prompt",
                "x",
            ]
        )
        self.assertEqual(rc, 1)
        self.assertIn("policy load failed", sys.stderr.getvalue())

    def test_missing_policy_dir_exits_with_1(self) -> None:
        rc = main(
            [
                "--policies",
                "/nonexistent/policies/path",
                "--taxonomy",
                str(PHI_TAXONOMY),
                "--prompt",
                "x",
            ]
        )
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
