"""Tests for primitives.audit.policy_schema.

Run from the repo root:
    python3 -m pytest primitives/audit/tests/ -v

Or as a script:
    python3 primitives/audit/tests/test_policy_schema.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from pydantic import ValidationError  # noqa: E402

from audit.policy_schema import (  # noqa: E402
    AlertConfig,
    BlockConfig,
    Match,
    MatchClasses,
    Policy,
    RedactConfig,
)


# ---------------------------------------------------------------------------
# Reference YAML payloads from POLICY_ENGINE_SPEC v0.2
# ---------------------------------------------------------------------------


BLOCK_POLICY = {
    "schema_version": "1.0",
    "policy_id": "phi_block_address_in_external_prompt",
    "policy_version": "v1.2",
    "description": "Block patient address to external vendors.",
    "match": {
        "direction": "prompt",
        "destination": "external_vendor",
        "classes": {"any_of": ["phi:patient_address"]},
    },
    "verdict": "block",
    "block_config": {
        "user_message": "Patient address detected; blocked.",
    },
    "audit_only": False,
    "on_classifier_error": "fail_open",
}


REDACT_POLICY = {
    "schema_version": "1.0",
    "policy_id": "phi_redact_dob_in_response",
    "policy_version": "v1.0",
    "match": {
        "direction": "response",
        "destination": "any",
        "classes": {"any_of": ["phi:patient_dob"]},
    },
    "verdict": "redact",
    "redact_config": {
        "redact_with": "[REDACTED:{class}]",
    },
}


ALERT_POLICY = {
    "schema_version": "1.0",
    "policy_id": "phi_alert_on_diagnosis_to_external",
    "policy_version": "v1.0",
    "match": {
        "direction": "prompt",
        "destination": "external_vendor",
        "classes": {"any_of": ["phi:diagnosis_code"]},
    },
    "verdict": "alert",
    "alert_config": {
        "webhook": "https://internal.example.com/truss/alerts",
    },
}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class HappyPath(unittest.TestCase):
    def test_block_policy_validates(self) -> None:
        p = Policy.model_validate(BLOCK_POLICY)
        self.assertEqual(p.verdict, "block")
        self.assertIsNotNone(p.block_config)
        self.assertEqual(p.match.classes.as_list(), ["phi:patient_address"])
        self.assertEqual(p.match.classes.mode, "any_of")
        self.assertEqual(p.on_classifier_error, "fail_open")

    def test_redact_policy_validates(self) -> None:
        p = Policy.model_validate(REDACT_POLICY)
        self.assertEqual(p.verdict, "redact")
        self.assertEqual(p.redact_config.redact_with, "[REDACTED:{class}]")

    def test_alert_policy_validates(self) -> None:
        p = Policy.model_validate(ALERT_POLICY)
        self.assertEqual(p.verdict, "alert")
        self.assertEqual(
            p.alert_config.webhook, "https://internal.example.com/truss/alerts"
        )

    def test_alert_policy_with_no_webhook_validates(self) -> None:
        # Webhook is optional — alert can fire log-only.
        payload = {**ALERT_POLICY, "alert_config": {}}
        p = Policy.model_validate(payload)
        self.assertIsNone(p.alert_config.webhook)

    def test_audit_only_default_is_false(self) -> None:
        # audit_only defaults to False if absent.
        payload = {k: v for k, v in BLOCK_POLICY.items() if k != "audit_only"}
        p = Policy.model_validate(payload)
        self.assertFalse(p.audit_only)

    def test_on_classifier_error_default_is_fail_open(self) -> None:
        payload = {
            k: v for k, v in BLOCK_POLICY.items() if k != "on_classifier_error"
        }
        p = Policy.model_validate(payload)
        self.assertEqual(p.on_classifier_error, "fail_open")


# ---------------------------------------------------------------------------
# Verdict ↔ config block discrimination
# ---------------------------------------------------------------------------


class VerdictConfigDiscrimination(unittest.TestCase):
    def test_block_without_block_config_rejected(self) -> None:
        payload = {**BLOCK_POLICY}
        del payload["block_config"]
        with self.assertRaises(ValidationError) as ctx:
            Policy.model_validate(payload)
        self.assertIn("block_config", str(ctx.exception))

    def test_redact_without_redact_config_rejected(self) -> None:
        payload = {**REDACT_POLICY}
        del payload["redact_config"]
        with self.assertRaises(ValidationError):
            Policy.model_validate(payload)

    def test_alert_without_alert_config_rejected(self) -> None:
        payload = {**ALERT_POLICY}
        del payload["alert_config"]
        with self.assertRaises(ValidationError):
            Policy.model_validate(payload)

    def test_block_with_extra_redact_config_rejected(self) -> None:
        # Verdict=block but redact_config is also set → reject.
        payload = {
            **BLOCK_POLICY,
            "redact_config": {"redact_with": "[X]"},
        }
        with self.assertRaises(ValidationError) as ctx:
            Policy.model_validate(payload)
        self.assertIn("redact_config", str(ctx.exception))

    def test_no_verdict_allow(self) -> None:
        # Spec: there is no verdict:allow. Absence of any matching rule = allowed.
        payload = {**BLOCK_POLICY, "verdict": "allow"}
        with self.assertRaises(ValidationError):
            Policy.model_validate(payload)


# ---------------------------------------------------------------------------
# Match.classes — exactly one of any_of / all_of
# ---------------------------------------------------------------------------


class MatchClassesValidation(unittest.TestCase):
    def test_neither_any_of_nor_all_of_rejected(self) -> None:
        payload = {**BLOCK_POLICY}
        payload["match"] = {**payload["match"], "classes": {}}
        with self.assertRaises(ValidationError):
            Policy.model_validate(payload)

    def test_both_any_of_and_all_of_rejected(self) -> None:
        payload = {**BLOCK_POLICY}
        payload["match"] = {
            **payload["match"],
            "classes": {
                "any_of": ["phi:patient_address"],
                "all_of": ["phi:patient_address"],
            },
        }
        with self.assertRaises(ValidationError):
            Policy.model_validate(payload)

    def test_empty_class_list_rejected(self) -> None:
        payload = {**BLOCK_POLICY}
        payload["match"] = {**payload["match"], "classes": {"any_of": []}}
        with self.assertRaises(ValidationError):
            Policy.model_validate(payload)

    def test_unnamespaced_class_rejected(self) -> None:
        payload = {**BLOCK_POLICY}
        payload["match"] = {
            **payload["match"],
            "classes": {"any_of": ["patient_address"]},  # no namespace
        }
        with self.assertRaises(ValidationError) as ctx:
            Policy.model_validate(payload)
        self.assertIn("namespaced", str(ctx.exception))

    def test_all_of_mode_works(self) -> None:
        payload = {**BLOCK_POLICY}
        payload["match"] = {
            **payload["match"],
            "classes": {"all_of": ["phi:patient_address", "phi:patient_name"]},
        }
        p = Policy.model_validate(payload)
        self.assertEqual(p.match.classes.mode, "all_of")
        self.assertEqual(len(p.match.classes.as_list()), 2)


# ---------------------------------------------------------------------------
# Redact template grammar
# ---------------------------------------------------------------------------


class RedactTemplateValidation(unittest.TestCase):
    def test_class_token_allowed(self) -> None:
        cfg = RedactConfig(redact_with="[REDACTED:{class}]")
        self.assertEqual(cfg.redact_with, "[REDACTED:{class}]")

    def test_no_tokens_allowed(self) -> None:
        cfg = RedactConfig(redact_with="[REDACTED]")
        self.assertEqual(cfg.redact_with, "[REDACTED]")

    def test_unknown_token_rejected(self) -> None:
        with self.assertRaises(ValidationError) as ctx:
            RedactConfig(redact_with="[REDACTED:{instance_index}]")
        self.assertIn("unsupported token", str(ctx.exception))

    def test_policy_id_token_rejected(self) -> None:
        # Future tokens MUST be rejected so v0.1 doesn't silently accept them.
        with self.assertRaises(ValidationError):
            RedactConfig(redact_with="[REDACTED-by-{policy_id}]")

    def test_classes_to_redact_must_be_subset(self) -> None:
        payload = {
            **REDACT_POLICY,
            "match": {
                "direction": "response",
                "destination": "any",
                "classes": {"any_of": ["phi:patient_dob"]},
            },
            "redact_config": {
                "redact_with": "[X]",
                "classes_to_redact": ["phi:patient_address"],  # not in match
            },
        }
        with self.assertRaises(ValidationError) as ctx:
            Policy.model_validate(payload)
        self.assertIn("not in match.classes", str(ctx.exception))

    def test_classes_to_redact_subset_ok(self) -> None:
        payload = {
            **REDACT_POLICY,
            "match": {
                "direction": "response",
                "destination": "any",
                "classes": {"any_of": ["phi:patient_dob", "phi:patient_name"]},
            },
            "redact_config": {
                "redact_with": "[X]",
                "classes_to_redact": ["phi:patient_dob"],
            },
        }
        p = Policy.model_validate(payload)
        self.assertEqual(p.redact_config.classes_to_redact, ["phi:patient_dob"])


# ---------------------------------------------------------------------------
# Webhook validation
# ---------------------------------------------------------------------------


class WebhookValidation(unittest.TestCase):
    def test_https_webhook_ok(self) -> None:
        AlertConfig(webhook="https://example.com/hook")

    def test_http_webhook_ok(self) -> None:
        # Allowed but discouraged; demos often use http for local dev.
        AlertConfig(webhook="http://localhost:8000/hook")

    def test_relative_webhook_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            AlertConfig(webhook="/hook")

    def test_random_string_webhook_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            AlertConfig(webhook="not-a-url")


# ---------------------------------------------------------------------------
# policy_id / schema_version
# ---------------------------------------------------------------------------


class PolicyIdValidation(unittest.TestCase):
    def test_uppercase_rejected(self) -> None:
        payload = {**BLOCK_POLICY, "policy_id": "Phi_Block_Address"}
        with self.assertRaises(ValidationError):
            Policy.model_validate(payload)

    def test_dashes_rejected(self) -> None:
        payload = {**BLOCK_POLICY, "policy_id": "phi-block-address"}
        with self.assertRaises(ValidationError):
            Policy.model_validate(payload)

    def test_too_short_rejected(self) -> None:
        payload = {**BLOCK_POLICY, "policy_id": "ab"}
        with self.assertRaises(ValidationError):
            Policy.model_validate(payload)

    def test_starts_with_digit_rejected(self) -> None:
        payload = {**BLOCK_POLICY, "policy_id": "1phi_block"}
        with self.assertRaises(ValidationError):
            Policy.model_validate(payload)


class SchemaVersionValidation(unittest.TestCase):
    def test_unknown_schema_version_rejected(self) -> None:
        payload = {**BLOCK_POLICY, "schema_version": "2.0"}
        with self.assertRaises(ValidationError):
            Policy.model_validate(payload)

    def test_extra_top_level_field_rejected(self) -> None:
        # extra='forbid' on Policy means unknown YAML keys hard-fail at parse.
        payload = {**BLOCK_POLICY, "future_feature": "bool_compose"}
        with self.assertRaises(ValidationError):
            Policy.model_validate(payload)


if __name__ == "__main__":
    unittest.main(verbosity=2)
