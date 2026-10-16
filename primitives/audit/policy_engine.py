"""Policy engine — synchronous evaluator for one prompt/response phase.

Per docs/research/POLICY_ENGINE_SPEC.md v0.2:
  - Consumes List[ClassHit] from the classifier (offsets + namespaced classes).
  - Walks the loaded PolicySet, evaluates each rule whose match.direction +
    match.destination filter the request, and records a PolicyDecision for
    every fired rule.
  - Resolves precedence: block > alert > redact > allow (operator-intent
    severity, NOT request-mutation severity).
  - Applies the mutation: builds mutated_text for redact, surfaces
    block_user_message for block, leaves text untouched for alert/allow.
  - Handles audit_only (decision recorded, NOT enforced) and classifier
    errors (per-policy fail_open / fail_closed).
  - Returns a PolicyEvaluation the proxy threads into the receipt writer.

The engine never imports from the proxy. The proxy imports the engine.
This keeps the engine testable without spinning up FastAPI.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

from .classifier import ClassHit
from .policy_event import PolicyEvent
from .policy_loader import PolicySet
from .policy_schema import Policy
from .session_state import StateUpdate


# ---------------------------------------------------------------------------
# Constants — vocabulary lives in primitives.audit.schema (closed enums)
# ---------------------------------------------------------------------------


# Receipt-side verdict vocabulary (past-tense). Maps from YAML verdict via _yaml_to_receipt_verdict.
_VERDICT_PRECEDENCE: Dict[str, int] = {
    "blocked": 3,
    "alerted": 2,
    "redacted": 1,
    "allowed": 0,
}


def _yaml_to_receipt_verdict(yaml_verdict: str) -> str:
    return {"block": "blocked", "redact": "redacted", "alert": "alerted"}[yaml_verdict]


# ---------------------------------------------------------------------------
# Output dataclasses — proxy↔engine contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PolicyDecision:
    """One row of receipt.policy_decisions[] per RECEIPT_SCHEMA.md v1.1."""

    policy_id: Optional[str]
    policy_version: Optional[str]
    policy_set_version: str
    evaluated_at: str  # ISO 8601
    verdict: str  # "allowed" | "blocked" | "redacted" | "alerted"
    enforcement_mode: str  # "enforced" | "audit_only" | "error"
    matched_classes: Tuple[str, ...]
    would_have_blocked: Optional[bool]
    redactions_applied: Tuple[Dict[str, Any], ...]
    error_reason: Optional[str]
    alert_id: Optional[Dict[str, Any]]

    def to_receipt_dict(self) -> Dict[str, Any]:
        """Serialize for receipt_writer.policy_decisions parameter."""
        return {
            "policy_id": self.policy_id,
            "policy_version": self.policy_version,
            "policy_set_version": self.policy_set_version,
            "evaluated_at": self.evaluated_at,
            "verdict": self.verdict,
            "enforcement_mode": self.enforcement_mode,
            "matched_classes": list(self.matched_classes),
            "would_have_blocked": self.would_have_blocked,
            "redactions_applied": [dict(r) for r in self.redactions_applied],
            "error_reason": self.error_reason,
            "alert_id": dict(self.alert_id) if self.alert_id is not None else None,
        }


@dataclass(frozen=True)
class PolicyEvaluation:
    """The engine's verdict on one phase (prompt OR response) of one request."""

    decisions: Tuple[PolicyDecision, ...]
    final_verdict: str  # operator-intent severity winner
    mutated_text: Optional[str]  # None when blocked
    block_user_message: Optional[str]  # set when final_verdict == "blocked"
    policy_set_version: str
    state_updates: Tuple[StateUpdate, ...] = ()

    def receipt_payload(self) -> List[Dict[str, Any]]:
        """Convenience wrapper for receipt_writer.write(policy_decisions=...)."""
        return [d.to_receipt_dict() for d in self.decisions]


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


_DirectionT = Literal["prompt", "response"]
_DestinationT = Literal["external_vendor", "internal", "any"]
_ErrorReasonT = Literal[
    "classifier_timeout",
    "classifier_exception",
    "taxonomy_load_error",
    "policy_eval_exception",
]


def evaluate(
    text: str,
    direction: _DirectionT,
    destination: _DestinationT,
    class_hits: List[ClassHit],
    policy_set: PolicySet,
    classifier_error: Optional[_ErrorReasonT] = None,
    *,
    now: Optional[Callable[[], datetime]] = None,
) -> PolicyEvaluation:
    """Evaluate one legacy prompt/response phase against the loaded PolicySet.

    Args:
      text: The prompt or response text. The engine returns a possibly-mutated
        version (redactions applied) or None when blocked.
      direction: Which phase this evaluation is for ("prompt" or "response").
      destination: The request destination tag the proxy attaches.
      class_hits: Output of classifier.Classifier.classify(text, location=direction).
        Empty list is fine and means "classifier ran, found nothing."
      policy_set: Loaded by primitives.audit.policy_loader.load_policies(...).
      classifier_error: When the classifier failed. Triggers per-policy fail mode.
        When set, class_hits is ignored.
      now: Optional clock injection for tests. Defaults to datetime.now(UTC).
    """
    event = PolicyEvent(
        event_id="legacy_event",
        session_id="legacy_session",
        type=direction,
        surface="legacy",
        actor={},
        destination=destination,
        data={"text": text},
        context={"policy_set_version": policy_set.policy_set_version},
        session_state={},
    )
    return evaluate_event(
        event=event,
        class_hits=class_hits,
        policy_set=policy_set,
        classifier_error=classifier_error,
        now=now,
    )


def evaluate_event(
    *,
    event: PolicyEvent,
    class_hits: List[ClassHit],
    policy_set: PolicySet,
    classifier_error: Optional[_ErrorReasonT] = None,
    now: Optional[Callable[[], datetime]] = None,
) -> PolicyEvaluation:
    """Evaluate one normalized policy event against the loaded PolicySet."""
    clock = now or (lambda: datetime.now(timezone.utc))
    evaluated_at = _iso8601(clock())
    text = event.text
    direction = event.direction

    # Filter to policies whose direction+destination match this phase.
    eligible = [
        p
        for p in policy_set.policies
        if _event_matches(p, event)
        and _direction_matches(p, direction)
        and _destination_matches(p, event.destination)
        and _state_condition_matches(p, event.session_state, event=event)
    ]

    if classifier_error is not None:
        return _evaluate_error_path(
            text=text,
            eligible=eligible,
            policy_set_version=policy_set.policy_set_version,
            classifier_error=classifier_error,
            evaluated_at=evaluated_at,
        )

    return _evaluate_happy_path(
        text=text,
        direction=direction,
        event=event,
        eligible=eligible,
        class_hits=class_hits,
        policy_set_version=policy_set.policy_set_version,
        evaluated_at=evaluated_at,
        clock=clock,
        block_lookup=_block_lookup_from(eligible),
    )


def evaluate_state_error(
    *,
    event: PolicyEvent,
    class_hits: List[ClassHit],
    policy_set: PolicySet,
    now: Optional[Callable[[], datetime]] = None,
) -> PolicyEvaluation:
    """Evaluate fail-open/fail-closed behavior when session state is unavailable."""
    clock = now or (lambda: datetime.now(timezone.utc))
    evaluated_at = _iso8601(clock())
    direction = event.direction
    direction_hits = [h for h in class_hits if h.location == direction]
    hit_classes_set = {h.cls for h in direction_hits}
    stateful = [
        p
        for p in policy_set.policies
        if (p.event is not None or p.condition is not None or p.state_updates)
        and _event_matches(p, event)
        and _direction_matches(p, direction)
        and _destination_matches(p, event.destination)
    ]

    decisions: List[PolicyDecision] = []
    block_user_message: Optional[str] = None
    for policy in sorted(stateful, key=lambda p: p.policy_id):
        matched_classes = _match_classes(policy, hit_classes_set)
        if matched_classes is None:
            continue
        if policy.on_state_error == "fail_open":
            verdict = "allowed"
            would_have_blocked = False
        else:
            verdict = "blocked"
            would_have_blocked = True
            if block_user_message is None and policy.block_config is not None:
                block_user_message = policy.block_config.user_message
        decisions.append(
            PolicyDecision(
                policy_id=policy.policy_id,
                policy_version=policy.policy_version,
                policy_set_version=policy_set.policy_set_version,
                evaluated_at=evaluated_at,
                verdict=verdict,
                enforcement_mode="error",
                matched_classes=tuple(matched_classes),
                would_have_blocked=would_have_blocked,
                redactions_applied=(),
                error_reason="policy_eval_exception",
                alert_id=None,
            )
        )

    if not decisions:
        decisions.append(
            PolicyDecision(
                policy_id=None,
                policy_version=None,
                policy_set_version=policy_set.policy_set_version,
                evaluated_at=evaluated_at,
                verdict="allowed",
                enforcement_mode="error",
                matched_classes=(),
                would_have_blocked=False,
                redactions_applied=(),
                error_reason="policy_eval_exception",
                alert_id=None,
            )
        )

    final_verdict = _highest_precedence(d.verdict for d in decisions)
    if final_verdict == "blocked" and block_user_message is None:
        block_user_message = "Request blocked: session state unavailable and policy is fail-closed."
    return PolicyEvaluation(
        decisions=tuple(_sort_decisions(decisions)),
        final_verdict=final_verdict,
        mutated_text=None if final_verdict == "blocked" else event.text,
        block_user_message=block_user_message,
        policy_set_version=policy_set.policy_set_version,
        state_updates=(),
    )


def _block_lookup_from(policies: List[Policy]) -> Dict[str, str]:
    """policy_id → block user_message, for finalize-time resolution."""
    return {
        p.policy_id: p.block_config.user_message
        for p in policies
        if p.verdict == "block" and p.block_config is not None
    }


# ---------------------------------------------------------------------------
# Happy path (classifier produced hits)
# ---------------------------------------------------------------------------


def _evaluate_happy_path(
    *,
    text: str,
    direction: _DirectionT,
    event: PolicyEvent,
    eligible: List[Policy],
    class_hits: List[ClassHit],
    policy_set_version: str,
    evaluated_at: str,
    clock: Callable[[], datetime],
    block_lookup: Dict[str, str],
) -> PolicyEvaluation:
    # For class matching we only consider hits in this direction. The engine
    # accepts the classifier's full hit list but filters defensively.
    direction_hits = [h for h in class_hits if h.location == direction]
    hit_classes_set = {h.cls for h in direction_hits}

    decisions: List[PolicyDecision] = []
    redact_ops: List[_RedactOp] = []  # collected for mutation pass
    state_updates: List[StateUpdate] = []

    for policy in eligible:
        matched_classes = _match_classes(policy, hit_classes_set)
        if matched_classes is None:
            continue  # class filter didn't fire; no receipt entry for this rule

        yaml_verdict = policy.verdict
        receipt_verdict = _yaml_to_receipt_verdict(yaml_verdict)

        if policy.audit_only:
            enforcement_mode = "audit_only"
            would_have_blocked = receipt_verdict == "blocked"
            redactions_applied: Tuple[Dict[str, Any], ...] = ()
            alert_id: Optional[Dict[str, Any]] = None
        else:
            enforcement_mode = "enforced"
            would_have_blocked = None
            redactions_applied = ()  # filled in mutation pass for redact rules
            alert_id = (
                _build_alert_id(clock) if yaml_verdict == "alert" else None
            )
            if yaml_verdict == "redact":
                # Defer actual redaction to the mutation pass (precedence-aware).
                ops = _build_redact_ops(
                    policy=policy,
                    direction=direction,
                    direction_hits=direction_hits,
                    matched_classes=matched_classes,
                )
                redact_ops.extend(ops)

        decisions.append(
            PolicyDecision(
                policy_id=policy.policy_id,
                policy_version=policy.policy_version,
                policy_set_version=policy_set_version,
                evaluated_at=evaluated_at,
                verdict=receipt_verdict,
                enforcement_mode=enforcement_mode,
                matched_classes=tuple(matched_classes),
                would_have_blocked=would_have_blocked,
                redactions_applied=redactions_applied,
                error_reason=None,
                alert_id=alert_id,
            )
        )
        if enforcement_mode == "enforced":
            for update in policy.state_updates:
                state_updates.append(
                    update.model_copy(
                        update={"policy_id": update.policy_id or policy.policy_id}
                    )
                )

    if not decisions:
        # Synthetic "allowed" — one entry per phase per spec.
        decisions.append(_synthetic_allowed(policy_set_version, evaluated_at))

    return _resolve_and_finalize(
        text=text,
        direction=direction,
        decisions=decisions,
        redact_ops=redact_ops,
        state_updates=state_updates,
        policy_set_version=policy_set_version,
        block_lookup=block_lookup,
    )


# ---------------------------------------------------------------------------
# Error path (classifier failed; per-policy fail mode)
# ---------------------------------------------------------------------------


def _evaluate_error_path(
    *,
    text: str,
    eligible: List[Policy],
    policy_set_version: str,
    classifier_error: str,
    evaluated_at: str,
) -> PolicyEvaluation:
    decisions: List[PolicyDecision] = []
    block_user_message: Optional[str] = None

    for policy in sorted(eligible, key=lambda p: p.policy_id):
        if policy.on_classifier_error == "fail_open":
            verdict = "allowed"
            would_have_blocked = False
        else:  # fail_closed
            verdict = "blocked"
            would_have_blocked = True
            if block_user_message is None and policy.block_config is not None:
                block_user_message = policy.block_config.user_message

        decisions.append(
            PolicyDecision(
                policy_id=policy.policy_id,
                policy_version=policy.policy_version,
                policy_set_version=policy_set_version,
                evaluated_at=evaluated_at,
                verdict=verdict,
                enforcement_mode="error",
                matched_classes=(),
                would_have_blocked=would_have_blocked,
                redactions_applied=(),
                error_reason=classifier_error,
                alert_id=None,
            )
        )

    if not decisions:
        # No eligible policies at all — synthesize an error-allowed entry. The
        # request still proceeds; an auditor sees the classifier failed but
        # nothing was configured to care.
        decisions.append(
            PolicyDecision(
                policy_id=None,
                policy_version=None,
                policy_set_version=policy_set_version,
                evaluated_at=evaluated_at,
                verdict="allowed",
                enforcement_mode="error",
                matched_classes=(),
                would_have_blocked=False,
                redactions_applied=(),
                error_reason=classifier_error,
                alert_id=None,
            )
        )

    final_verdict = _highest_precedence(d.verdict for d in decisions)
    if final_verdict == "blocked":
        if block_user_message is None:
            block_user_message = (
                "Request blocked: classifier unavailable and policy is fail-closed."
            )
        mutated_text: Optional[str] = None
    else:
        mutated_text = text

    decisions_sorted = _sort_decisions(decisions)
    return PolicyEvaluation(
        decisions=tuple(decisions_sorted),
        final_verdict=final_verdict,
        mutated_text=mutated_text,
        block_user_message=block_user_message,
        policy_set_version=policy_set_version,
        state_updates=(),
    )


# ---------------------------------------------------------------------------
# Resolution + mutation
# ---------------------------------------------------------------------------


def _resolve_and_finalize(
    *,
    text: str,
    direction: _DirectionT,
    decisions: List[PolicyDecision],
    redact_ops: List["_RedactOp"],
    state_updates: List[StateUpdate],
    policy_set_version: str,
    block_lookup: Dict[str, str],
) -> PolicyEvaluation:
    enforced_verdicts = [
        d.verdict for d in decisions if d.enforcement_mode == "enforced"
    ]
    final_verdict = _highest_precedence(enforced_verdicts) if enforced_verdicts else "allowed"

    mutated_text: Optional[str] = text
    block_user_message: Optional[str] = None
    redactions_by_policy: Dict[str, List[Dict[str, Any]]] = {}

    if final_verdict == "blocked":
        # First block decision by policy_id alphabetical wins user_message.
        block_decisions = sorted(
            (
                d
                for d in decisions
                if d.verdict == "blocked" and d.enforcement_mode == "enforced"
            ),
            key=lambda d: d.policy_id or "",
        )
        for d in block_decisions:
            if d.policy_id and d.policy_id in block_lookup:
                block_user_message = block_lookup[d.policy_id]
                break
        mutated_text = None

    if final_verdict == "redacted" and redact_ops:
        mutated_text, redactions_by_policy = _apply_redactions(
            text=text, direction=direction, ops=redact_ops
        )

    # Re-emit decisions with redactions_applied filled in for the redact rules.
    finalized: List[PolicyDecision] = []
    for d in decisions:
        applied = redactions_by_policy.get(d.policy_id or "")
        if applied is not None and d.enforcement_mode == "enforced" and d.verdict == "redacted":
            finalized.append(
                _with_redactions(d, tuple(applied))
            )
        else:
            finalized.append(d)

    return PolicyEvaluation(
        decisions=tuple(_sort_decisions(finalized)),
        final_verdict=final_verdict,
        mutated_text=mutated_text,
        block_user_message=block_user_message,
        policy_set_version=policy_set_version,
        state_updates=tuple(state_updates),
    )


def _with_redactions(
    d: PolicyDecision, redactions: Tuple[Dict[str, Any], ...]
) -> PolicyDecision:
    return PolicyDecision(
        policy_id=d.policy_id,
        policy_version=d.policy_version,
        policy_set_version=d.policy_set_version,
        evaluated_at=d.evaluated_at,
        verdict=d.verdict,
        enforcement_mode=d.enforcement_mode,
        matched_classes=d.matched_classes,
        would_have_blocked=d.would_have_blocked,
        redactions_applied=redactions,
        error_reason=d.error_reason,
        alert_id=d.alert_id,
    )


# ---------------------------------------------------------------------------
# Class matching
# ---------------------------------------------------------------------------


def _match_classes(policy: Policy, hit_classes: set) -> Optional[List[str]]:
    """Return the matched class list for receipt, or None if class filter missed."""
    rule_classes = policy.match.classes.as_list()
    rule_set = set(rule_classes)
    if policy.match.classes.mode == "any_of":
        intersection = rule_set & hit_classes
        if not intersection:
            return None
        # Preserve the order declared in the policy for receipt determinism.
        return [c for c in rule_classes if c in intersection]
    # all_of
    if not rule_set.issubset(hit_classes):
        return None
    return list(rule_classes)


# ---------------------------------------------------------------------------
# Direction / destination matching
# ---------------------------------------------------------------------------


def _direction_matches(policy: Policy, request_direction: str) -> bool:
    return policy.match.direction == "any" or policy.match.direction == request_direction


def _destination_matches(policy: Policy, request_destination: str) -> bool:
    return (
        policy.match.destination == "any"
        or policy.match.destination == request_destination
    )


def _event_matches(policy: Policy, event: PolicyEvent) -> bool:
    if policy.event is None:
        if policy.match.direction == "prompt":
            return event.type in {"prompt", "browser_prompt"}
        if policy.match.direction == "response":
            return event.type in {"response", "browser_response"}
        return True
    return event.type in set(policy.event.types)


def _state_condition_matches(
    policy: Policy,
    state: dict[str, Any],
    *,
    event: Optional[PolicyEvent] = None,
) -> bool:
    condition = policy.condition
    if condition is None:
        return True
    for key in condition.state_missing or []:
        if key in state:
            return False
    for key, expected in (condition.state or {}).items():
        if not _state_value_matches(state, key, expected, event=event):
            return False
    return True


def _resolve_event_path(event: Optional[PolicyEvent], path: str) -> Tuple[bool, Any]:
    if event is None or not isinstance(path, str) or not path:
        return False, None
    current: Any = event.model_dump()
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list) and part.isdigit():
            idx = int(part)
            if 0 <= idx < len(current):
                current = current[idx]
                continue
        return False, None
    return True, current


def _state_value_matches(
    state: dict[str, Any],
    key: str,
    expected: Any,
    *,
    event: Optional[PolicyEvent] = None,
) -> bool:
    exists = key in state
    actual = state.get(key)
    if not isinstance(expected, dict):
        return exists and actual == expected
    for comparator, operand in expected.items():
        if comparator == "exists":
            if bool(operand) != exists:
                return False
            continue
        if comparator == "missing":
            if bool(operand) != (not exists):
                return False
            continue
        if not exists:
            return False
        if comparator == "eq" and actual != operand:
            return False
        if comparator == "neq" and actual == operand:
            return False
        if comparator == "eq_from_event":
            found, ev_val = _resolve_event_path(event, str(operand))
            if not found or actual != ev_val:
                return False
            continue
        if comparator == "neq_from_event":
            found, ev_val = _resolve_event_path(event, str(operand))
            if not found or actual == ev_val:
                return False
            continue
        if comparator == "gt" and not _compare(actual, operand, lambda a, b: a > b):
            return False
        if comparator == "gte" and not _compare(actual, operand, lambda a, b: a >= b):
            return False
        if comparator == "lt" and not _compare(actual, operand, lambda a, b: a < b):
            return False
        if comparator == "lte" and not _compare(actual, operand, lambda a, b: a <= b):
            return False
        if comparator == "contains":
            try:
                if operand not in actual:
                    return False
            except TypeError:
                return False
        if comparator not in {
            "eq",
            "neq",
            "eq_from_event",
            "neq_from_event",
            "gt",
            "gte",
            "lt",
            "lte",
            "contains",
            "exists",
            "missing",
        }:
            return False
    return True


def _compare(actual: Any, operand: Any, fn: Callable[[Any, Any], bool]) -> bool:
    try:
        return bool(fn(actual, operand))
    except TypeError:
        return False


# ---------------------------------------------------------------------------
# Redaction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _RedactOp:
    policy_id: str
    cls: str
    span_start: int
    span_end: int
    original_text: str
    template: str  # already rendered (e.g. "[REDACTED:phi:patient_dob]")


def _build_redact_ops(
    *,
    policy: Policy,
    direction: _DirectionT,
    direction_hits: List[ClassHit],
    matched_classes: List[str],
) -> List[_RedactOp]:
    assert policy.redact_config is not None
    template_raw = policy.redact_config.redact_with
    classes_to_redact = (
        set(policy.redact_config.classes_to_redact)
        if policy.redact_config.classes_to_redact is not None
        else set(matched_classes)
    )

    ops: List[_RedactOp] = []
    for hit in direction_hits:
        if hit.cls not in classes_to_redact:
            continue
        rendered = template_raw.replace("{class}", hit.cls)
        ops.append(
            _RedactOp(
                policy_id=policy.policy_id,
                cls=hit.cls,
                span_start=hit.span[0],
                span_end=hit.span[1],
                original_text=hit.text,
                template=rendered,
            )
        )
    return ops


def _apply_redactions(
    *, text: str, direction: _DirectionT, ops: List[_RedactOp]
) -> Tuple[str, Dict[str, List[Dict[str, Any]]]]:
    """Apply redactions in (span_start, policy_id) order.

    Subsequent ops whose span is fully inside an already-redacted region are
    skipped (per POLICY_ENGINE_SPEC: "subsequent redactions operate on
    already-redacted text"). Each successful redaction lands in the per-policy
    list as {location, before_hash, after_hash}.
    """
    import hashlib

    sorted_ops = sorted(ops, key=lambda o: (o.span_start, o.policy_id))
    pieces: List[str] = []
    cursor = 0
    redactions_by_policy: Dict[str, List[Dict[str, Any]]] = {}

    for op in sorted_ops:
        if op.span_start < cursor:
            # Already covered by an earlier redaction; skip.
            continue
        pieces.append(text[cursor:op.span_start])
        pieces.append(op.template)
        cursor = op.span_end

        before_hash = "sha256:" + hashlib.sha256(
            op.original_text.encode("utf-8")
        ).hexdigest()
        after_hash = "sha256:" + hashlib.sha256(
            op.template.encode("utf-8")
        ).hexdigest()
        redactions_by_policy.setdefault(op.policy_id, []).append(
            {
                "location": direction,
                "before_hash": before_hash,
                "after_hash": after_hash,
            }
        )

    pieces.append(text[cursor:])
    new_text = "".join(pieces)
    return new_text, redactions_by_policy


# ---------------------------------------------------------------------------
# Synthesis + helpers
# ---------------------------------------------------------------------------


def _synthetic_allowed(policy_set_version: str, evaluated_at: str) -> PolicyDecision:
    return PolicyDecision(
        policy_id=None,
        policy_version=None,
        policy_set_version=policy_set_version,
        evaluated_at=evaluated_at,
        verdict="allowed",
        enforcement_mode="enforced",
        matched_classes=(),
        would_have_blocked=None,
        redactions_applied=(),
        error_reason=None,
        alert_id=None,
    )


def _build_alert_id(clock: Callable[[], datetime]) -> Dict[str, Any]:
    timestamp = clock().strftime("%Y-%m-%d_%H-%M-%S")
    suffix = secrets.token_hex(3)
    return {
        "id": f"alert_{timestamp}_{suffix}",
        "delivery_status": "pending",
        "delivered_at": None,
    }


def _highest_precedence(verdicts) -> str:
    best = "allowed"
    best_score = _VERDICT_PRECEDENCE[best]
    for v in verdicts:
        score = _VERDICT_PRECEDENCE[v]
        if score > best_score:
            best = v
            best_score = score
    return best


def _sort_decisions(decisions: List[PolicyDecision]) -> List[PolicyDecision]:
    """Sort by policy_id alphabetical; synthetic null-id entries sort last."""
    return sorted(
        decisions,
        key=lambda d: (d.policy_id is None, d.policy_id or ""),
    )


def _iso8601(now: datetime) -> str:
    return now.isoformat().replace("+00:00", "Z")


__all__ = [
    "PolicyDecision",
    "PolicyEvaluation",
    "evaluate",
    "evaluate_event",
]
