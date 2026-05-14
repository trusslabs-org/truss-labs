"""Tests for primitives.audit.receipt_writer.

Run from the repo root:
    python3 -m pytest primitives/audit/tests/ -v

Or as a script (no pytest required):
    python3 primitives/audit/tests/test_receipt_writer.py
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

# Allow running this file directly without installing the package
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from audit.receipt_writer import (  # noqa: E402
    CAPTURED_BY_DEFAULT,
    ReceiptValidationError,
    ReceiptWriter,
    _canonical_json,
)
from audit.schema import RECEIPT_JSON_SCHEMA, SCHEMA_VERSION  # noqa: E402


SAMPLE_ACTOR = {
    "user_id": "alice@example.com",
    "user_role": "clinician",
    "department": "health_services",
    "auth_method": "saml_sso",
}

SAMPLE_TOOL = {
    "tool_id": "epic_chat_assistant",
    "tool_version": "v2.4.1",
    "model_id": "gpt-4o-2024-11-20",
    "model_vendor": "openai",
    "endpoint": "api.openai.com/v1/chat/completions",
}


class ReceiptWriterBasics(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.receipts_dir = Path(self.tmp.name)
        self.writer = ReceiptWriter(receipts_dir=self.receipts_dir)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    # ----- happy path -----

    def test_write_returns_existing_file(self) -> None:
        path = self.writer.write(
            actor=SAMPLE_ACTOR,
            tool=SAMPLE_TOOL,
            prompt_text="Test prompt",
            response_text="Test response",
        )
        self.assertTrue(path.exists())
        self.assertTrue(path.is_file())
        self.assertEqual(path.suffix, ".json")

    def test_receipt_validates_against_schema(self) -> None:
        path = self.writer.write(
            actor=SAMPLE_ACTOR,
            tool=SAMPLE_TOOL,
            prompt_text="Test prompt",
            response_text="Test response",
        )
        receipt = json.loads(path.read_text())
        # If schema validation failed, write would have raised.
        self.assertEqual(receipt["schema_version"], SCHEMA_VERSION)
        self.assertIn("receipt_id", receipt)

    def test_receipt_id_format(self) -> None:
        path = self.writer.write(
            actor=SAMPLE_ACTOR,
            tool=SAMPLE_TOOL,
            prompt_text="hi",
            response_text="hello",
        )
        receipt = json.loads(path.read_text())
        rid = receipt["receipt_id"]
        # rcp_2026-05-09T10-00-00_abcdef
        self.assertTrue(
            re.match(r"^rcp_\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}_[0-9a-f]{6,}$", rid),
            f"receipt_id {rid!r} does not match pattern",
        )

    def test_receipts_land_in_per_day_subdir(self) -> None:
        path = self.writer.write(
            actor=SAMPLE_ACTOR,
            tool=SAMPLE_TOOL,
            prompt_text="x",
            response_text="y",
        )
        # parent should be a YYYY-MM-DD directory
        self.assertRegex(path.parent.name, r"^\d{4}-\d{2}-\d{2}$")

    # ----- hash invariants -----

    def test_prompt_and_response_hashes_are_correct(self) -> None:
        prompt = "Draft a follow-up to patient 11248."
        response = "Dear patient, ..."
        path = self.writer.write(
            actor=SAMPLE_ACTOR,
            tool=SAMPLE_TOOL,
            prompt_text=prompt,
            response_text=response,
        )
        receipt = json.loads(path.read_text())
        expected_p = "sha256:" + hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        expected_r = "sha256:" + hashlib.sha256(response.encode("utf-8")).hexdigest()
        self.assertEqual(receipt["prompt"]["text_hash"], expected_p)
        self.assertEqual(receipt["response"]["text_hash"], expected_r)

    def test_evidence_receipt_hash_is_verifiable(self) -> None:
        """An auditor should be able to recompute the receipt hash."""
        path = self.writer.write(
            actor=SAMPLE_ACTOR,
            tool=SAMPLE_TOOL,
            prompt_text="audit this",
            response_text="audited",
        )
        receipt = json.loads(path.read_text())
        stored_hash = receipt["evidence"]["receipt_hash"]
        # Auditor reproduces by zeroing the hash field and re-canonicalizing
        receipt["evidence"]["receipt_hash"] = ""
        recomputed = "sha256:" + hashlib.sha256(
            _canonical_json(receipt).encode("utf-8")
        ).hexdigest()
        self.assertEqual(stored_hash, recomputed, "receipt_hash is not reproducible")

    # ----- grep-ability invariant -----

    def test_resource_id_is_grepable(self) -> None:
        path = self.writer.write(
            actor=SAMPLE_ACTOR,
            tool=SAMPLE_TOOL,
            prompt_text="follow-up for chart",
            response_text="ok",
            context_references=[
                {
                    "type": "patient_chart",
                    "resource_id": "patient:11248",
                    "fields_accessed": ["a1c_history"],
                    "access_method": "epic_fhir_api",
                }
            ],
        )
        text = path.read_text()
        self.assertIn('"resource_id": "patient:11248"', text)

    # ----- schema enforcement -----

    def test_invalid_actor_raises(self) -> None:
        with self.assertRaises(ReceiptValidationError):
            self.writer.write(
                actor={},  # missing required user_id
                tool=SAMPLE_TOOL,
                prompt_text="x",
                response_text="y",
            )

    def test_invalid_tool_raises(self) -> None:
        with self.assertRaises(ReceiptValidationError):
            self.writer.write(
                actor=SAMPLE_ACTOR,
                tool={"tool_id": "x"},  # missing required model_id
                prompt_text="x",
                response_text="y",
            )

    # ----- ID uniqueness at volume -----

    def test_no_duplicate_ids_in_burst(self) -> None:
        n = 100
        paths = [
            self.writer.write(
                actor=SAMPLE_ACTOR,
                tool=SAMPLE_TOOL,
                prompt_text=f"prompt {i}",
                response_text=f"response {i}",
            )
            for i in range(n)
        ]
        ids = [json.loads(p.read_text())["receipt_id"] for p in paths]
        self.assertEqual(len(ids), len(set(ids)), "duplicate receipt IDs in burst")
        self.assertEqual(len(paths), n)

    # ----- atomicity (best-effort assertion on filesystem) -----

    def test_no_temp_files_remain_after_write(self) -> None:
        for i in range(20):
            self.writer.write(
                actor=SAMPLE_ACTOR,
                tool=SAMPLE_TOOL,
                prompt_text=f"x{i}",
                response_text=f"y{i}",
            )
        leftover = list(self.receipts_dir.rglob(".receipt_*.json.tmp"))
        self.assertEqual(leftover, [], f"temp files leaked: {leftover}")


class ReceiptWriterDefaults(unittest.TestCase):
    def test_default_captured_by(self) -> None:
        self.assertTrue(CAPTURED_BY_DEFAULT.startswith("truss-audit"))

    def test_schema_const_matches_module_const(self) -> None:
        self.assertEqual(
            RECEIPT_JSON_SCHEMA["properties"]["schema_version"]["const"],
            SCHEMA_VERSION,
        )

    def test_schema_version_is_v1_1(self) -> None:
        self.assertEqual(SCHEMA_VERSION, "1.1")


class PolicyDecisionsV11(unittest.TestCase):
    """v1.1 policy_decisions[] contract per POLICY_ENGINE_SPEC v0.2."""

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.writer = ReceiptWriter(receipts_dir=Path(self.tmp.name))

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _write_with_decisions(self, decisions):
        path = self.writer.write(
            actor=SAMPLE_ACTOR,
            tool=SAMPLE_TOOL,
            prompt_text="x",
            response_text="y",
            policy_decisions=decisions,
        )
        return json.loads(path.read_text())

    def test_enforced_block_decision_validates(self) -> None:
        receipt = self._write_with_decisions([
            {
                "policy_id": "phi_block_address_in_external_prompt",
                "policy_version": "v1.0",
                "policy_set_version": "a3f8c7b29e10",
                "evaluated_at": "2026-05-10T14:32:08.380Z",
                "verdict": "blocked",
                "enforcement_mode": "enforced",
                "matched_classes": ["phi:patient_address"],
                "would_have_blocked": None,
                "redactions_applied": [],
                "error_reason": None,
                "alert_id": None,
            }
        ])
        self.assertEqual(receipt["policy_decisions"][0]["verdict"], "blocked")
        self.assertIsNone(receipt["policy_decisions"][0]["would_have_blocked"])

    def test_audit_only_decision_uses_would_have_blocked(self) -> None:
        receipt = self._write_with_decisions([
            {
                "policy_id": "phi_block_address_in_external_prompt",
                "policy_version": "v1.0",
                "policy_set_version": "a3f8c7b29e10",
                "evaluated_at": "2026-05-10T14:32:08.380Z",
                "verdict": "blocked",
                "enforcement_mode": "audit_only",
                "matched_classes": ["phi:patient_address"],
                "would_have_blocked": True,
                "redactions_applied": [],
                "error_reason": None,
                "alert_id": None,
            }
        ])
        d = receipt["policy_decisions"][0]
        self.assertEqual(d["enforcement_mode"], "audit_only")
        self.assertTrue(d["would_have_blocked"])

    def test_synthetic_allowed_with_null_policy_id(self) -> None:
        # When no rule matched, the engine writes a synthetic "allowed" entry
        # with null policy_id / policy_version per POLICY_ENGINE_SPEC.
        receipt = self._write_with_decisions([
            {
                "policy_id": None,
                "policy_version": None,
                "policy_set_version": "a3f8c7b29e10",
                "evaluated_at": "2026-05-10T14:32:08.380Z",
                "verdict": "allowed",
                "enforcement_mode": "enforced",
                "matched_classes": [],
                "would_have_blocked": None,
                "redactions_applied": [],
                "error_reason": None,
                "alert_id": None,
            }
        ])
        d = receipt["policy_decisions"][0]
        self.assertIsNone(d["policy_id"])
        self.assertEqual(d["matched_classes"], [])

    def test_classifier_timeout_error_reason_validates(self) -> None:
        receipt = self._write_with_decisions([
            {
                "policy_id": "phi_block_address_in_external_prompt",
                "policy_version": "v1.0",
                "policy_set_version": "a3f8c7b29e10",
                "evaluated_at": "2026-05-10T14:32:08.380Z",
                "verdict": "allowed",
                "enforcement_mode": "error",
                "matched_classes": [],
                "would_have_blocked": False,
                "redactions_applied": [],
                "error_reason": "classifier_timeout",
                "alert_id": None,
            }
        ])
        self.assertEqual(
            receipt["policy_decisions"][0]["error_reason"], "classifier_timeout"
        )

    def test_unknown_error_reason_rejected(self) -> None:
        with self.assertRaises(ReceiptValidationError):
            self._write_with_decisions([
                {
                    "policy_id": "p",
                    "policy_version": "v1",
                    "policy_set_version": "abc",
                    "evaluated_at": "2026-05-10T14:32:08.380Z",
                    "verdict": "allowed",
                    "enforcement_mode": "error",
                    "matched_classes": [],
                    "would_have_blocked": False,
                    "redactions_applied": [],
                    "error_reason": "some_freeform_string",  # not in closed enum
                    "alert_id": None,
                }
            ])

    def test_unknown_enforcement_mode_rejected(self) -> None:
        with self.assertRaises(ReceiptValidationError):
            self._write_with_decisions([
                {
                    "policy_id": "p",
                    "policy_version": "v1",
                    "policy_set_version": "abc",
                    "evaluated_at": "2026-05-10T14:32:08.380Z",
                    "verdict": "allowed",
                    "enforcement_mode": "shadow",  # not enforced/audit_only/error
                    "matched_classes": [],
                    "would_have_blocked": False,
                    "redactions_applied": [],
                    "error_reason": None,
                    "alert_id": None,
                }
            ])

    def test_alerted_decision_with_structured_alert_id(self) -> None:
        receipt = self._write_with_decisions([
            {
                "policy_id": "phi_alert_on_diagnosis_to_external",
                "policy_version": "v1.0",
                "policy_set_version": "a3f8c7b29e10",
                "evaluated_at": "2026-05-10T14:32:08.380Z",
                "verdict": "alerted",
                "enforcement_mode": "enforced",
                "matched_classes": ["phi:diagnosis_code"],
                "would_have_blocked": None,
                "redactions_applied": [],
                "error_reason": None,
                "alert_id": {
                    "id": "alert_2026-05-10_a1b2c3",
                    "delivery_status": "pending",
                    "delivered_at": None,
                },
            }
        ])
        alert = receipt["policy_decisions"][0]["alert_id"]
        self.assertEqual(alert["delivery_status"], "pending")
        self.assertIsNone(alert["delivered_at"])

    def test_redacted_decision_records_redactions(self) -> None:
        receipt = self._write_with_decisions([
            {
                "policy_id": "phi_redact_dob_in_response",
                "policy_version": "v1.0",
                "policy_set_version": "a3f8c7b29e10",
                "evaluated_at": "2026-05-10T14:32:09.120Z",
                "verdict": "redacted",
                "enforcement_mode": "enforced",
                "matched_classes": ["phi:patient_dob"],
                "would_have_blocked": None,
                "redactions_applied": [
                    {
                        "location": "response",
                        "before_hash": "sha256:" + "a" * 64,
                        "after_hash": "sha256:" + "b" * 64,
                    }
                ],
                "error_reason": None,
                "alert_id": None,
            }
        ])
        self.assertEqual(
            len(receipt["policy_decisions"][0]["redactions_applied"]), 1
        )

    def test_missing_policy_set_version_rejected(self) -> None:
        # policy_set_version is required at the entry level in v1.1.
        with self.assertRaises(ReceiptValidationError):
            self._write_with_decisions([
                {
                    "policy_id": "p",
                    "policy_version": "v1",
                    # no policy_set_version
                    "evaluated_at": "2026-05-10T14:32:08.380Z",
                    "verdict": "allowed",
                    "enforcement_mode": "enforced",
                    "matched_classes": [],
                    "would_have_blocked": None,
                    "redactions_applied": [],
                    "error_reason": None,
                    "alert_id": None,
                }
            ])


if __name__ == "__main__":
    unittest.main(verbosity=2)
