"""Tests for primitives.audit.policy_engine."""

from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from audit.classifier import ClassHit  # noqa: E402
from audit.policy_engine import PolicyEvaluation, evaluate  # noqa: E402
from audit.policy_loader import PolicySet  # noqa: E402
from audit.policy_schema import (  # noqa: E402
    AlertConfig,
    BlockConfig,
    Match,
    MatchClasses,
    Policy,
    RedactConfig,
)


# ---------------------------------------------------------------------------
# Fixed clock for deterministic timestamps.
# ---------------------------------------------------------------------------


def fixed_clock(iso_str: str = "2026-05-10T14:32:08+00:00"):
    fixed = datetime.fromisoformat(iso_str)
    return lambda: fixed


# ---------------------------------------------------------------------------
# Policy / PolicySet builders
# ---------------------------------------------------------------------------


def block_policy(
    policy_id: str = "phi_block_address_in_external_prompt",
    classes=("phi:patient_address",),
    direction: str = "prompt",
    destination: str = "external_vendor",
    audit_only: bool = False,
    on_error: str = "fail_open",
    user_message: str = "Blocked.",
) -> Policy:
    return Policy(
        schema_version="1.0",
        policy_id=policy_id,
        policy_version="v1.0",
        match=Match(
            direction=direction,
            destination=destination,
            classes=MatchClasses(any_of=list(classes)),
        ),
        verdict="block",
        block_config=BlockConfig(user_message=user_message),
        audit_only=audit_only,
        on_classifier_error=on_error,
    )


def redact_policy(
    policy_id: str = "phi_redact_dob_in_response",
    classes=("phi:patient_dob",),
    direction: str = "response",
    destination: str = "any",
    redact_with: str = "[REDACTED:{class}]",
    audit_only: bool = False,
) -> Policy:
    return Policy(
        schema_version="1.0",
        policy_id=policy_id,
        policy_version="v1.0",
        match=Match(
            direction=direction,
            destination=destination,
            classes=MatchClasses(any_of=list(classes)),
        ),
        verdict="redact",
        redact_config=RedactConfig(redact_with=redact_with),
        audit_only=audit_only,
    )


def alert_policy(
    policy_id: str = "phi_alert_on_diagnosis",
    classes=("phi:diagnosis_code",),
    direction: str = "prompt",
    destination: str = "external_vendor",
    audit_only: bool = False,
) -> Policy:
    return Policy(
        schema_version="1.0",
        policy_id=policy_id,
        policy_version="v1.0",
        match=Match(
            direction=direction,
            destination=destination,
            classes=MatchClasses(any_of=list(classes)),
        ),
        verdict="alert",
        alert_config=AlertConfig(webhook="https://example.com/alerts"),
        audit_only=audit_only,
    )


def make_set(*policies: Policy, version: str = "abc123def456") -> PolicySet:
    return PolicySet(
        policies=tuple(policies),
        policy_set_version=version,
        source_dir=None,
    )


def hit(cls: str, start: int, end: int, location: str, text: str) -> ClassHit:
    return ClassHit(cls=cls, span=(start, end), text=text, location=location)


# ---------------------------------------------------------------------------
# Empty / no-match path
# ---------------------------------------------------------------------------


class EmptyAndNoMatch(unittest.TestCase):
    def test_empty_policy_set_synthesizes_allowed(self) -> None:
        ev = evaluate(
            text="hello",
            direction="prompt",
            destination="external_vendor",
            class_hits=[],
            policy_set=make_set(),
            now=fixed_clock(),
        )
        self.assertEqual(ev.final_verdict, "allowed")
        self.assertEqual(ev.mutated_text, "hello")
        self.assertEqual(len(ev.decisions), 1)
        self.assertIsNone(ev.decisions[0].policy_id)
        self.assertEqual(ev.decisions[0].verdict, "allowed")
        self.assertEqual(ev.decisions[0].enforcement_mode, "enforced")
        self.assertIsNone(ev.block_user_message)

    def test_no_classes_match_synthesizes_allowed(self) -> None:
        ps = make_set(block_policy())
        ev = evaluate(
            text="benign text",
            direction="prompt",
            destination="external_vendor",
            class_hits=[],  # no hits
            policy_set=ps,
            now=fixed_clock(),
        )
        self.assertEqual(ev.final_verdict, "allowed")
        self.assertEqual(len(ev.decisions), 1)
        self.assertIsNone(ev.decisions[0].policy_id)

    def test_direction_filter_excludes_response_only_policy(self) -> None:
        # A response-only policy should not see prompt traffic.
        ps = make_set(redact_policy(direction="response"))
        ev = evaluate(
            text="x",
            direction="prompt",
            destination="external_vendor",
            class_hits=[hit("phi:patient_dob", 0, 1, "prompt", "x")],
            policy_set=ps,
            now=fixed_clock(),
        )
        self.assertEqual(ev.final_verdict, "allowed")
        self.assertEqual(len(ev.decisions), 1)
        self.assertIsNone(ev.decisions[0].policy_id)

    def test_destination_filter_excludes_internal_only(self) -> None:
        ps = make_set(block_policy(destination="internal"))
        ev = evaluate(
            text="x",
            direction="prompt",
            destination="external_vendor",
            class_hits=[hit("phi:patient_address", 0, 1, "prompt", "x")],
            policy_set=ps,
            now=fixed_clock(),
        )
        self.assertEqual(ev.final_verdict, "allowed")

    def test_destination_any_matches_external(self) -> None:
        ps = make_set(block_policy(destination="any"))
        ev = evaluate(
            text="123 Main St",
            direction="prompt",
            destination="external_vendor",
            class_hits=[hit("phi:patient_address", 0, 11, "prompt", "123 Main St")],
            policy_set=ps,
            now=fixed_clock(),
        )
        self.assertEqual(ev.final_verdict, "blocked")


# ---------------------------------------------------------------------------
# Block path
# ---------------------------------------------------------------------------


class BlockPath(unittest.TestCase):
    def test_block_returns_user_message_and_no_text(self) -> None:
        ps = make_set(
            block_policy(user_message="Patient address blocked per HIPAA review.")
        )
        ev = evaluate(
            text="123 Main St",
            direction="prompt",
            destination="external_vendor",
            class_hits=[hit("phi:patient_address", 0, 11, "prompt", "123 Main St")],
            policy_set=ps,
            now=fixed_clock(),
        )
        self.assertEqual(ev.final_verdict, "blocked")
        self.assertIsNone(ev.mutated_text)
        self.assertEqual(
            ev.block_user_message, "Patient address blocked per HIPAA review."
        )
        self.assertEqual(len(ev.decisions), 1)
        d = ev.decisions[0]
        self.assertEqual(d.verdict, "blocked")
        self.assertEqual(d.enforcement_mode, "enforced")
        self.assertIsNone(d.would_have_blocked)  # null when enforced
        self.assertEqual(d.matched_classes, ("phi:patient_address",))


# ---------------------------------------------------------------------------
# Redact path
# ---------------------------------------------------------------------------


class RedactPath(unittest.TestCase):
    def test_single_redaction_rewrites_text(self) -> None:
        text = "DOB: 1978-04-12 visit"
        ps = make_set(
            redact_policy(
                direction="response", redact_with="[REDACTED:{class}]"
            )
        )
        ev = evaluate(
            text=text,
            direction="response",
            destination="any",
            class_hits=[hit("phi:patient_dob", 5, 15, "response", "1978-04-12")],
            policy_set=ps,
            now=fixed_clock(),
        )
        self.assertEqual(ev.final_verdict, "redacted")
        self.assertEqual(
            ev.mutated_text, "DOB: [REDACTED:phi:patient_dob] visit"
        )
        d = ev.decisions[0]
        self.assertEqual(len(d.redactions_applied), 1)
        self.assertEqual(d.redactions_applied[0]["location"], "response")
        self.assertTrue(d.redactions_applied[0]["before_hash"].startswith("sha256:"))

    def test_multiple_classes_one_policy_two_spans(self) -> None:
        text = "1978-04-12 then 2002-09-30"
        ps = make_set(redact_policy(direction="response"))
        ev = evaluate(
            text=text,
            direction="response",
            destination="any",
            class_hits=[
                hit("phi:patient_dob", 0, 10, "response", "1978-04-12"),
                hit("phi:patient_dob", 16, 26, "response", "2002-09-30"),
            ],
            policy_set=ps,
            now=fixed_clock(),
        )
        self.assertEqual(
            ev.mutated_text,
            "[REDACTED:phi:patient_dob] then [REDACTED:phi:patient_dob]",
        )
        self.assertEqual(len(ev.decisions[0].redactions_applied), 2)

    def test_overlapping_redactions_skipped(self) -> None:
        # Two redact policies, one matches a wider span, the other matches an
        # inner span. The inner one's span is fully covered by the outer one,
        # so it's a no-op once the outer redaction lands.
        text = "John Smith DOB 1978-04-12"
        outer = redact_policy(
            policy_id="phi_redact_full_phrase",
            classes=("phi:patient_full_phrase",),
            direction="response",
            redact_with="[OUTER]",
        )
        inner = redact_policy(
            policy_id="phi_redact_dob_inner",
            classes=("phi:patient_dob",),
            direction="response",
            redact_with="[INNER]",
        )
        ps = make_set(outer, inner)
        ev = evaluate(
            text=text,
            direction="response",
            destination="any",
            class_hits=[
                hit("phi:patient_full_phrase", 0, 25, "response", text),
                hit("phi:patient_dob", 15, 25, "response", "1978-04-12"),
            ],
            policy_set=ps,
            now=fixed_clock(),
        )
        # Outer wins because span_start=0 < 15 (sorted by span_start ascending).
        self.assertEqual(ev.mutated_text, "[OUTER]")
        # Outer policy gets a redaction recorded; inner gets none (covered).
        outer_decision = next(
            d for d in ev.decisions if d.policy_id == "phi_redact_full_phrase"
        )
        inner_decision = next(
            d for d in ev.decisions if d.policy_id == "phi_redact_dob_inner"
        )
        self.assertEqual(len(outer_decision.redactions_applied), 1)
        self.assertEqual(len(inner_decision.redactions_applied), 0)
        # Both still recorded as fired.
        self.assertEqual(outer_decision.verdict, "redacted")
        self.assertEqual(inner_decision.verdict, "redacted")

    def test_redactions_applied_in_span_order(self) -> None:
        # Two redact policies on disjoint spans. Sort by (span_start, policy_id).
        text = "AAA BBB"
        p1 = redact_policy(
            policy_id="z_late",
            classes=("phi:cls_a",),
            direction="response",
            redact_with="[A]",
        )
        p2 = redact_policy(
            policy_id="a_early",
            classes=("phi:cls_b",),
            direction="response",
            redact_with="[B]",
        )
        ps = make_set(p1, p2)
        ev = evaluate(
            text=text,
            direction="response",
            destination="any",
            class_hits=[
                hit("phi:cls_a", 0, 3, "response", "AAA"),
                hit("phi:cls_b", 4, 7, "response", "BBB"),
            ],
            policy_set=ps,
            now=fixed_clock(),
        )
        self.assertEqual(ev.mutated_text, "[A] [B]")


# ---------------------------------------------------------------------------
# Alert path
# ---------------------------------------------------------------------------


class AlertPath(unittest.TestCase):
    def test_alert_does_not_modify_text(self) -> None:
        text = "diag: J45.20 asthma"
        ps = make_set(alert_policy())
        ev = evaluate(
            text=text,
            direction="prompt",
            destination="external_vendor",
            class_hits=[hit("phi:diagnosis_code", 6, 12, "prompt", "J45.20")],
            policy_set=ps,
            now=fixed_clock(),
        )
        self.assertEqual(ev.final_verdict, "alerted")
        self.assertEqual(ev.mutated_text, text)
        d = ev.decisions[0]
        self.assertEqual(d.verdict, "alerted")
        self.assertIsNotNone(d.alert_id)
        self.assertEqual(d.alert_id["delivery_status"], "pending")
        self.assertIsNone(d.alert_id["delivered_at"])


# ---------------------------------------------------------------------------
# Precedence
# ---------------------------------------------------------------------------


class Precedence(unittest.TestCase):
    def test_block_beats_redact(self) -> None:
        # Two rules match: block and redact. Block wins enforcement.
        ps = make_set(
            block_policy(policy_id="b_block", classes=("phi:patient_address",)),
            redact_policy(
                policy_id="a_redact",
                classes=("phi:patient_dob",),
                direction="prompt",
            ),
        )
        ev = evaluate(
            text="John 1978-04-12 at 123 Main",
            direction="prompt",
            destination="external_vendor",
            class_hits=[
                hit("phi:patient_dob", 5, 15, "prompt", "1978-04-12"),
                hit("phi:patient_address", 19, 27, "prompt", "123 Main"),
            ],
            policy_set=ps,
            now=fixed_clock(),
        )
        self.assertEqual(ev.final_verdict, "blocked")
        self.assertIsNone(ev.mutated_text)
        # Both decisions recorded.
        verdicts = sorted(d.verdict for d in ev.decisions)
        self.assertEqual(verdicts, ["blocked", "redacted"])

    def test_alert_beats_redact(self) -> None:
        ps = make_set(
            alert_policy(policy_id="a_alert", classes=("phi:diagnosis_code",)),
            redact_policy(
                policy_id="b_redact",
                classes=("phi:patient_dob",),
                direction="prompt",
            ),
        )
        ev = evaluate(
            text="DOB 1978-04-12 J45.20",
            direction="prompt",
            destination="external_vendor",
            class_hits=[
                hit("phi:patient_dob", 4, 14, "prompt", "1978-04-12"),
                hit("phi:diagnosis_code", 15, 21, "prompt", "J45.20"),
            ],
            policy_set=ps,
            now=fixed_clock(),
        )
        # Operator-intent severity: alert > redact.
        self.assertEqual(ev.final_verdict, "alerted")
        # Text is NOT redacted because alert wins enforcement (alert leaves
        # text unchanged; redact would have rewritten — spec says alert outranks).
        self.assertEqual(ev.mutated_text, "DOB 1978-04-12 J45.20")

    def test_block_beats_alert(self) -> None:
        ps = make_set(
            block_policy(policy_id="a_block"),
            alert_policy(policy_id="b_alert"),
        )
        ev = evaluate(
            text="diag J45.20 addr 123 Main",
            direction="prompt",
            destination="external_vendor",
            class_hits=[
                hit("phi:diagnosis_code", 5, 11, "prompt", "J45.20"),
                hit("phi:patient_address", 17, 25, "prompt", "123 Main"),
            ],
            policy_set=ps,
            now=fixed_clock(),
        )
        self.assertEqual(ev.final_verdict, "blocked")

    def test_block_message_from_first_alphabetical(self) -> None:
        # Two block rules match. user_message comes from policy_id alphabetical first.
        ps = make_set(
            block_policy(
                policy_id="z_late_block",
                classes=("phi:patient_address",),
                user_message="late",
            ),
            block_policy(
                policy_id="a_first_block",
                classes=("phi:patient_address",),
                user_message="first",
            ),
        )
        ev = evaluate(
            text="123 Main St",
            direction="prompt",
            destination="external_vendor",
            class_hits=[
                hit("phi:patient_address", 0, 11, "prompt", "123 Main St")
            ],
            policy_set=ps,
            now=fixed_clock(),
        )
        self.assertEqual(ev.block_user_message, "first")


# ---------------------------------------------------------------------------
# Audit-only mode
# ---------------------------------------------------------------------------


class AuditOnlyMode(unittest.TestCase):
    def test_audit_only_block_does_not_enforce(self) -> None:
        ps = make_set(block_policy(audit_only=True))
        ev = evaluate(
            text="123 Main St",
            direction="prompt",
            destination="external_vendor",
            class_hits=[
                hit("phi:patient_address", 0, 11, "prompt", "123 Main St")
            ],
            policy_set=ps,
            now=fixed_clock(),
        )
        # Final verdict is allowed because no enforced rule fired.
        self.assertEqual(ev.final_verdict, "allowed")
        self.assertEqual(ev.mutated_text, "123 Main St")
        self.assertIsNone(ev.block_user_message)
        # But the receipt records the would-have-blocked counterfactual.
        d = ev.decisions[0]
        self.assertEqual(d.verdict, "blocked")
        self.assertEqual(d.enforcement_mode, "audit_only")
        self.assertTrue(d.would_have_blocked)

    def test_audit_only_redact_records_counterfactual(self) -> None:
        ps = make_set(redact_policy(audit_only=True))
        text = "DOB 1978-04-12"
        ev = evaluate(
            text=text,
            direction="response",
            destination="any",
            class_hits=[hit("phi:patient_dob", 4, 14, "response", "1978-04-12")],
            policy_set=ps,
            now=fixed_clock(),
        )
        self.assertEqual(ev.final_verdict, "allowed")
        self.assertEqual(ev.mutated_text, text)  # NOT redacted
        d = ev.decisions[0]
        self.assertEqual(d.verdict, "redacted")
        self.assertEqual(d.enforcement_mode, "audit_only")
        self.assertFalse(d.would_have_blocked)  # redact wouldn't have blocked
        self.assertEqual(d.redactions_applied, ())  # not applied

    def test_audit_only_alongside_enforced(self) -> None:
        # One audit-only block + one enforced redact. Enforced redact wins
        # final_verdict; audit-only block records counterfactual.
        ps = make_set(
            block_policy(
                policy_id="a_audit_block",
                classes=("phi:patient_address",),
                audit_only=True,
            ),
            redact_policy(
                policy_id="b_enforced_redact",
                classes=("phi:patient_dob",),
                direction="prompt",
            ),
        )
        ev = evaluate(
            text="DOB 1978-04-12 at 123 Main",
            direction="prompt",
            destination="external_vendor",
            class_hits=[
                hit("phi:patient_dob", 4, 14, "prompt", "1978-04-12"),
                hit("phi:patient_address", 18, 26, "prompt", "123 Main"),
            ],
            policy_set=ps,
            now=fixed_clock(),
        )
        # Enforced redact wins; block was audit-only.
        self.assertEqual(ev.final_verdict, "redacted")
        self.assertEqual(
            ev.mutated_text, "DOB [REDACTED:phi:patient_dob] at 123 Main"
        )
        modes = sorted(d.enforcement_mode for d in ev.decisions)
        self.assertEqual(modes, ["audit_only", "enforced"])


# ---------------------------------------------------------------------------
# Classifier error path
# ---------------------------------------------------------------------------


class ClassifierErrorPath(unittest.TestCase):
    def test_fail_open_allows_request(self) -> None:
        ps = make_set(block_policy(on_error="fail_open"))
        ev = evaluate(
            text="anything",
            direction="prompt",
            destination="external_vendor",
            class_hits=[],
            policy_set=ps,
            classifier_error="classifier_timeout",
            now=fixed_clock(),
        )
        self.assertEqual(ev.final_verdict, "allowed")
        self.assertEqual(ev.mutated_text, "anything")
        d = ev.decisions[0]
        self.assertEqual(d.enforcement_mode, "error")
        self.assertEqual(d.error_reason, "classifier_timeout")
        self.assertEqual(d.verdict, "allowed")
        self.assertFalse(d.would_have_blocked)

    def test_fail_closed_blocks_request(self) -> None:
        ps = make_set(block_policy(on_error="fail_closed", user_message="locked"))
        ev = evaluate(
            text="anything",
            direction="prompt",
            destination="external_vendor",
            class_hits=[],
            policy_set=ps,
            classifier_error="classifier_exception",
            now=fixed_clock(),
        )
        self.assertEqual(ev.final_verdict, "blocked")
        self.assertIsNone(ev.mutated_text)
        self.assertEqual(ev.block_user_message, "locked")
        d = ev.decisions[0]
        self.assertEqual(d.enforcement_mode, "error")
        self.assertEqual(d.verdict, "blocked")
        self.assertTrue(d.would_have_blocked)

    def test_mixed_fail_modes_blocks_wins(self) -> None:
        # One fail_open, one fail_closed. Block takes precedence.
        ps = make_set(
            block_policy(
                policy_id="a_open",
                on_error="fail_open",
                user_message="open",
            ),
            block_policy(
                policy_id="b_closed",
                on_error="fail_closed",
                user_message="closed",
            ),
        )
        ev = evaluate(
            text="x",
            direction="prompt",
            destination="external_vendor",
            class_hits=[],
            policy_set=ps,
            classifier_error="classifier_timeout",
            now=fixed_clock(),
        )
        self.assertEqual(ev.final_verdict, "blocked")
        self.assertEqual(ev.block_user_message, "closed")
        # Both decisions recorded with enforcement_mode=error.
        modes = {d.enforcement_mode for d in ev.decisions}
        self.assertEqual(modes, {"error"})

    def test_no_eligible_policies_synthesizes_error_allowed(self) -> None:
        # Classifier error but no policies match this direction.
        ps = make_set(redact_policy(direction="response"))
        ev = evaluate(
            text="x",
            direction="prompt",
            destination="external_vendor",
            class_hits=[],
            policy_set=ps,
            classifier_error="taxonomy_load_error",
            now=fixed_clock(),
        )
        self.assertEqual(ev.final_verdict, "allowed")
        self.assertEqual(len(ev.decisions), 1)
        d = ev.decisions[0]
        self.assertIsNone(d.policy_id)
        self.assertEqual(d.enforcement_mode, "error")
        self.assertEqual(d.error_reason, "taxonomy_load_error")


# ---------------------------------------------------------------------------
# Receipt serialization + ordering
# ---------------------------------------------------------------------------


class ReceiptSerialization(unittest.TestCase):
    def test_decisions_sorted_alphabetical_by_policy_id(self) -> None:
        ps = make_set(
            block_policy(policy_id="z_block", user_message="z"),
            redact_policy(
                policy_id="a_redact", direction="prompt", classes=("phi:cls_x",)
            ),
        )
        ev = evaluate(
            text="hi",
            direction="prompt",
            destination="external_vendor",
            class_hits=[
                hit("phi:cls_x", 0, 1, "prompt", "h"),
                hit("phi:patient_address", 1, 2, "prompt", "i"),
            ],
            policy_set=ps,
            now=fixed_clock(),
        )
        ids = [d.policy_id for d in ev.decisions]
        self.assertEqual(ids, ["a_redact", "z_block"])

    def test_to_receipt_dict_round_trips(self) -> None:
        ps = make_set(block_policy())
        ev = evaluate(
            text="123 Main",
            direction="prompt",
            destination="external_vendor",
            class_hits=[hit("phi:patient_address", 0, 8, "prompt", "123 Main")],
            policy_set=ps,
            now=fixed_clock(),
        )
        payload = ev.receipt_payload()
        self.assertEqual(len(payload), 1)
        d = payload[0]
        # All v1.1 fields present.
        for key in [
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
        ]:
            self.assertIn(key, d)


# ---------------------------------------------------------------------------
# any_of vs all_of
# ---------------------------------------------------------------------------


class AnyOfAllOf(unittest.TestCase):
    def test_all_of_requires_every_class_present(self) -> None:
        # all_of policy: requires both classes present.
        policy = Policy(
            schema_version="1.0",
            policy_id="phi_all_of_test",
            policy_version="v1.0",
            match=Match(
                direction="prompt",
                destination="any",
                classes=MatchClasses(
                    all_of=["phi:patient_dob", "phi:patient_name"]
                ),
            ),
            verdict="block",
            block_config=BlockConfig(user_message="dual"),
        )
        ps = make_set(policy)
        # Only one class hit — should NOT match.
        ev = evaluate(
            text="x",
            direction="prompt",
            destination="any",
            class_hits=[hit("phi:patient_dob", 0, 1, "prompt", "x")],
            policy_set=ps,
            now=fixed_clock(),
        )
        self.assertEqual(ev.final_verdict, "allowed")
        # Both classes hit — should match.
        ev2 = evaluate(
            text="xy",
            direction="prompt",
            destination="any",
            class_hits=[
                hit("phi:patient_dob", 0, 1, "prompt", "x"),
                hit("phi:patient_name", 1, 2, "prompt", "y"),
            ],
            policy_set=ps,
            now=fixed_clock(),
        )
        self.assertEqual(ev2.final_verdict, "blocked")


# ---------------------------------------------------------------------------
# End-to-end: engine output → receipt_writer → v1.1 schema validation
# ---------------------------------------------------------------------------


class EndToEndReceiptIntegration(unittest.TestCase):
    def test_engine_output_validates_as_v11_receipt(self) -> None:
        import tempfile

        from audit.receipt_writer import ReceiptWriter

        with tempfile.TemporaryDirectory() as tmp:
            writer = ReceiptWriter(receipts_dir=Path(tmp))
            ps = make_set(
                block_policy(user_message="Address blocked."),
                redact_policy(direction="prompt", classes=("phi:patient_dob",)),
            )
            ev = evaluate(
                text="DOB 1978-04-12 at 123 Main",
                direction="prompt",
                destination="external_vendor",
                class_hits=[
                    hit("phi:patient_dob", 4, 14, "prompt", "1978-04-12"),
                    hit("phi:patient_address", 18, 26, "prompt", "123 Main"),
                ],
                policy_set=ps,
                now=fixed_clock(),
            )
            # Engine says blocked; proxy would short-circuit, but we still
            # write a receipt for the audit trail. Use original text since
            # the receipt records what was sent, not what was forwarded.
            path = writer.write(
                actor={
                    "user_id": "alice@example.com",
                    "user_role": "clinician",
                },
                tool={
                    "tool_id": "epic_chat_assistant",
                    "model_id": "gpt-4o-2024-11-20",
                },
                prompt_text="DOB 1978-04-12 at 123 Main",
                response_text="(blocked)",
                policy_decisions=ev.receipt_payload(),
            )
            self.assertTrue(path.exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
