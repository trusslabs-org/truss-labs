"""End-to-end tests for primitives.audit.proxy.

Exercises the full pipeline classifier → policy_engine → receipt_writer
against the two shipped example policies, using a deterministic
StubLLMClient so tests don't need network or API keys.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from fastapi.testclient import TestClient  # noqa: E402

from audit.classifier import Classifier  # noqa: E402
from audit.policy_loader import load_policies  # noqa: E402
from audit.proxy import StubLLMClient, create_app  # noqa: E402


_REPO_ROOT = Path(__file__).resolve().parents[3]
PHI_TAXONOMY = _REPO_ROOT / "primitives" / "audit" / "taxonomies" / "phi.yaml"
EXAMPLE_POLICIES_DIR = _REPO_ROOT / "examples" / "policies"


def _actor() -> dict:
    return {"user_id": "alice@example.com", "user_role": "clinician"}


class ProxyBase(unittest.TestCase):
    """Boots an app with the shipped example policies + a stub LLM client."""

    canned_response: str = "OK"

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.receipts_dir = Path(self.tmp.name)
        policy_set = load_policies(EXAMPLE_POLICIES_DIR)
        classifiers = [Classifier.from_taxonomy_file(PHI_TAXONOMY)]
        self.client_stub = StubLLMClient(canned_response=self.canned_response)
        app = create_app(
            policy_set=policy_set,
            classifiers=classifiers,
            receipts_dir=self.receipts_dir,
            llm_client=self.client_stub,
        )
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _read_receipt(self, path_str: str) -> dict:
        return json.loads(Path(path_str).read_text())


# ---------------------------------------------------------------------------
# Block path: address in prompt → blocked, no LLM call, receipt records the block
# ---------------------------------------------------------------------------


class BlockPath(ProxyBase):
    canned_response = "should-never-be-returned"

    def test_address_in_prompt_blocks(self) -> None:
        resp = self.client.post(
            "/v1/chat",
            json={
                "prompt": "Patient lives at 1234 Main St.",
                "actor": _actor(),
                "destination": "external_vendor",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["verdict"], "blocked")
        self.assertIn("Patient address detected", body["block_message"])
        self.assertIsNone(body["response"])

    def test_blocked_request_writes_receipt_with_block_decision(self) -> None:
        resp = self.client.post(
            "/v1/chat",
            json={
                "prompt": "Patient lives at 1234 Main St.",
                "actor": _actor(),
            },
        )
        receipt = self._read_receipt(resp.json()["receipt_path"])
        # Receipt has an empty response and exactly one prompt-phase block decision.
        self.assertEqual(receipt["response"]["text"], "")
        verdicts = [d["verdict"] for d in receipt["policy_decisions"]]
        self.assertIn("blocked", verdicts)
        # Block decision carries the policy_id of the example block policy.
        block_ids = [
            d["policy_id"] for d in receipt["policy_decisions"] if d["verdict"] == "blocked"
        ]
        self.assertIn("phi_block_address_in_external_prompt", block_ids)


# ---------------------------------------------------------------------------
# Redact path: DOB in response → response returned with [REDACTED:phi:patient_dob]
# ---------------------------------------------------------------------------


class RedactPath(ProxyBase):
    # The stub returns this verbatim; the engine should redact the DOB span.
    canned_response = "DOB 1978-04-12 noted on chart."

    def test_dob_in_response_redacted(self) -> None:
        resp = self.client.post(
            "/v1/chat",
            json={
                "prompt": "Summarize the case note.",
                "actor": _actor(),
                "destination": "external_vendor",
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["verdict"], "redacted")
        self.assertIn("[REDACTED:phi:patient_dob]", body["response"])
        self.assertNotIn("1978-04-12", body["response"])

    def test_redacted_response_receipt_carries_redaction(self) -> None:
        resp = self.client.post(
            "/v1/chat",
            json={
                "prompt": "Summarize the case note.",
                "actor": _actor(),
            },
        )
        receipt = self._read_receipt(resp.json()["receipt_path"])
        verdicts = [d["verdict"] for d in receipt["policy_decisions"]]
        self.assertIn("redacted", verdicts)
        redact = next(
            d for d in receipt["policy_decisions"] if d["verdict"] == "redacted"
        )
        self.assertEqual(redact["policy_id"], "phi_redact_dob_in_response")
        self.assertEqual(len(redact["redactions_applied"]), 1)
        self.assertEqual(redact["redactions_applied"][0]["location"], "response")


# ---------------------------------------------------------------------------
# Allowed path: benign prompt + benign response → response passes through
# ---------------------------------------------------------------------------


class AllowedPath(ProxyBase):
    canned_response = "Mitochondria are the powerhouse of the cell."

    def test_benign_request_allowed(self) -> None:
        resp = self.client.post(
            "/v1/chat",
            json={
                "prompt": "What is the role of mitochondria?",
                "actor": _actor(),
            },
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["verdict"], "allowed")
        self.assertEqual(body["response"], self.canned_response)

    def test_allowed_receipt_has_only_synthetic_decisions(self) -> None:
        resp = self.client.post(
            "/v1/chat",
            json={
                "prompt": "What is the role of mitochondria?",
                "actor": _actor(),
            },
        )
        receipt = self._read_receipt(resp.json()["receipt_path"])
        # Both phases yield synthetic null-policy_id "allowed" entries.
        for d in receipt["policy_decisions"]:
            self.assertEqual(d["verdict"], "allowed")
            self.assertIsNone(d["policy_id"])


# ---------------------------------------------------------------------------
# Healthz reflects loaded policy set
# ---------------------------------------------------------------------------


class RootRoute(ProxyBase):
    """Verify the root route serves demo.html when configured."""

    def setUp(self) -> None:
        # Override base setUp so we can pass demo_html_path.
        self.tmp = tempfile.TemporaryDirectory()
        self.receipts_dir = Path(self.tmp.name)
        policy_set = load_policies(EXAMPLE_POLICIES_DIR)
        classifiers = [Classifier.from_taxonomy_file(PHI_TAXONOMY)]
        self.client_stub = StubLLMClient()
        self.demo_html = _REPO_ROOT / "examples" / "demo.html"
        from audit.proxy import create_app  # local import to avoid base setUp clash
        app = create_app(
            policy_set=policy_set,
            classifiers=classifiers,
            receipts_dir=self.receipts_dir,
            llm_client=self.client_stub,
            demo_html_path=self.demo_html,
        )
        self.client = TestClient(app)

    def test_root_serves_demo_html(self) -> None:
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("text/html", resp.headers["content-type"])
        self.assertIn("DEMO ENVIRONMENT", resp.text)
        self.assertIn("Truss Audit Proxy", resp.text)


class RootRouteFallback(ProxyBase):
    """Verify the root route falls back to a JSON pointer when no demo.html is configured."""

    def test_root_returns_json_pointer_when_unconfigured(self) -> None:
        # ProxyBase's create_app omits demo_html_path entirely.
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["see"], "/healthz")


class RetentionDays(ProxyBase):
    """retention_days request field should propagate to the receipt's retain_until."""

    canned_response = "fine"

    def test_retention_days_overrides_years_in_receipt(self) -> None:
        resp = self.client.post(
            "/v1/chat",
            json={
                "prompt": "What is the role of mitochondria?",
                "actor": _actor(),
                "retention_policy": "demo_seven_day",
                "retention_days": 7,
            },
        )
        self.assertEqual(resp.status_code, 200)
        receipt = self._read_receipt(resp.json()["receipt_path"])
        # retain_until should be ~7 days from now, not ~7 years.
        from datetime import datetime, timezone
        retain_until = datetime.fromisoformat(receipt["retention"]["retain_until"])
        delta_days = (retain_until.replace(tzinfo=timezone.utc) - datetime.now(timezone.utc)).days
        self.assertGreaterEqual(delta_days, 5)
        self.assertLessEqual(delta_days, 8)
        self.assertEqual(receipt["retention"]["retention_policy"], "demo_seven_day")


class Healthz(ProxyBase):
    def test_healthz_reports_policy_count_and_set_version(self) -> None:
        resp = self.client.get("/healthz")
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["policy_count"], 2)
        self.assertNotEqual(body["policy_set_version"], "empty")
        self.assertEqual(body["model_id"], "stub-echo")


# ---------------------------------------------------------------------------
# Validation: missing actor field → 422 from FastAPI body validator
# ---------------------------------------------------------------------------


class RequestValidation(ProxyBase):
    def test_missing_actor_returns_422(self) -> None:
        resp = self.client.post("/v1/chat", json={"prompt": "hello"})
        self.assertEqual(resp.status_code, 422)

    def test_empty_prompt_returns_422(self) -> None:
        resp = self.client.post(
            "/v1/chat", json={"prompt": "", "actor": _actor()}
        )
        self.assertEqual(resp.status_code, 422)


if __name__ == "__main__":
    unittest.main(verbosity=2)
