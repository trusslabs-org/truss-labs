"""Receipt schema — Python types + JSON Schema for v1.1 receipts.

Source of truth for the format is docs/research/RECEIPT_SCHEMA.md (v1.1).
This file mirrors that doc as code. When the doc changes, update both.

Two representations are exposed:
  - `Receipt` and friends: TypedDicts for IDE / type-checker support
  - `RECEIPT_JSON_SCHEMA`: JSON Schema dict for runtime validation via `jsonschema`

Schema separation note (2026-05-08): receipts have NO TWP fields. Audit and
Steering are separate products. The optional top-level `external_trace_uri`
field bridges orgs running both, but receipts are fully interpretable without it.

v1.1 (2026-05-10): policy_decisions[] expanded to match POLICY_ENGINE_SPEC v0.2.
Added policy_set_version, enforcement_mode, error_reason. would_have_blocked
is now nullable (null when enforcement_mode == enforced). alert_id is
structured ({id, delivery_status, delivered_at}) when verdict is alerted.
policy_id and policy_version are nullable for synthetic "allowed" entries
that record "no rule matched" against a phase.
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, TypedDict


SCHEMA_VERSION = "1.1"


# Closed enums per POLICY_ENGINE_SPEC v0.2.
ENFORCEMENT_MODES = ("enforced", "audit_only", "error")
ERROR_REASONS = (
    "classifier_timeout",
    "classifier_exception",
    "taxonomy_load_error",
    "policy_eval_exception",
)
ALERT_DELIVERY_STATUSES = ("pending", "delivered", "failed")


# ---------------------------------------------------------------------------
# TypedDict definitions (for type-hint / dev ergonomics)
# ---------------------------------------------------------------------------


class ContextReference(TypedDict, total=False):
    type: str
    resource_id: str
    fields_accessed: List[str]
    access_method: str


class Prompt(TypedDict, total=False):
    text: str
    text_hash: str
    text_length_chars: int
    context_references: List[ContextReference]


class Response(TypedDict, total=False):
    text: str
    text_hash: str
    text_length_chars: int
    tokens_used: Optional[int]
    latency_ms: Optional[int]


class DataClassTouched(TypedDict, total=False):
    cls: str  # serialized as "class" — see _python_to_json_field below
    instances: int
    in_prompt: bool
    in_response: bool


class DownstreamAction(TypedDict, total=False):
    action_id: str
    type: str
    target_path: str
    target_size_bytes: int
    content_hash: str
    diff_from_response: bool
    timestamp: str


class PolicyRedaction(TypedDict, total=False):
    location: Literal["prompt", "response"]
    before_hash: str
    after_hash: str


class AlertDelivery(TypedDict, total=False):
    id: str
    delivery_status: Literal["pending", "delivered", "failed"]
    delivered_at: Optional[str]  # ISO 8601, null if not yet delivered


class PolicyDecision(TypedDict, total=False):
    policy_id: Optional[str]            # null on synthetic "allowed" entries
    policy_version: Optional[str]       # null on synthetic "allowed" entries
    policy_set_version: str             # always present; "empty" sentinel when no policies loaded
    evaluated_at: str
    verdict: Literal["allowed", "blocked", "redacted", "alerted"]
    enforcement_mode: Literal["enforced", "audit_only", "error"]
    matched_classes: List[str]
    would_have_blocked: Optional[bool]  # null when enforcement_mode == enforced
    redactions_applied: List[PolicyRedaction]
    error_reason: Optional[str]         # null unless enforcement_mode == error
    alert_id: Optional[AlertDelivery]   # null unless verdict == alerted


class Actor(TypedDict, total=False):
    user_id: str
    user_role: str
    department: str
    auth_method: str


class Tool(TypedDict, total=False):
    tool_id: str
    tool_version: str
    model_id: str
    model_vendor: str
    endpoint: str


class Evidence(TypedDict, total=False):
    receipt_hash: str
    captured_by: str
    capture_method: str
    signature: Optional[str]


class Retention(TypedDict, total=False):
    retain_until: str
    retention_policy: str
    deletable_after: str
    legal_hold: bool


class Receipt(TypedDict, total=False):
    schema_version: str
    receipt_id: str
    timestamp: str
    external_trace_uri: Optional[str]
    actor: Actor
    tool: Tool
    prompt: Prompt
    response: Response
    data_classes_touched: List[DataClassTouched]
    downstream_actions: List[DownstreamAction]
    policy_decisions: List[PolicyDecision]
    evidence: Evidence
    retention: Retention


# ---------------------------------------------------------------------------
# JSON Schema (for jsonschema runtime validation)
# ---------------------------------------------------------------------------


RECEIPT_JSON_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Truss Audit Receipt v1.1",
    "type": "object",
    "additionalProperties": False,
    "required": [
        "schema_version",
        "receipt_id",
        "timestamp",
        "actor",
        "tool",
        "prompt",
        "response",
        "data_classes_touched",
        "downstream_actions",
        "policy_decisions",
        "evidence",
        "retention",
    ],
    "properties": {
        "schema_version": {"type": "string", "const": SCHEMA_VERSION},
        "receipt_id": {
            "type": "string",
            "pattern": r"^rcp_\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}_[0-9a-f]{6,}$",
        },
        "timestamp": {"type": "string", "format": "date-time"},
        "external_trace_uri": {"type": ["string", "null"]},
        "actor": {
            "type": "object",
            "required": ["user_id"],
            "properties": {
                "user_id": {"type": "string"},
                "user_role": {"type": "string"},
                "department": {"type": "string"},
                "auth_method": {"type": "string"},
            },
        },
        "tool": {
            "type": "object",
            "required": ["tool_id", "model_id"],
            "properties": {
                "tool_id": {"type": "string"},
                "tool_version": {"type": "string"},
                "model_id": {"type": "string"},
                "model_vendor": {"type": "string"},
                "endpoint": {"type": "string"},
            },
        },
        "prompt": {
            "type": "object",
            "required": ["text", "text_hash", "text_length_chars"],
            "properties": {
                "text": {"type": "string"},
                "text_hash": {"type": "string", "pattern": r"^sha256:[0-9a-f]{64}$"},
                "text_length_chars": {"type": "integer", "minimum": 0},
                "context_references": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string"},
                            "resource_id": {"type": "string"},
                            "fields_accessed": {"type": "array", "items": {"type": "string"}},
                            "access_method": {"type": "string"},
                        },
                    },
                },
            },
        },
        "response": {
            "type": "object",
            "required": ["text", "text_hash", "text_length_chars"],
            "properties": {
                "text": {"type": "string"},
                "text_hash": {"type": "string", "pattern": r"^sha256:[0-9a-f]{64}$"},
                "text_length_chars": {"type": "integer", "minimum": 0},
                "tokens_used": {"type": ["integer", "null"]},
                "latency_ms": {"type": ["integer", "null"]},
            },
        },
        "data_classes_touched": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["class", "instances"],
                "properties": {
                    "class": {"type": "string"},
                    "instances": {"type": "integer", "minimum": 0},
                    "in_prompt": {"type": "boolean"},
                    "in_response": {"type": "boolean"},
                },
            },
        },
        "downstream_actions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["action_id", "type", "timestamp"],
                "properties": {
                    "action_id": {"type": "string"},
                    "type": {"type": "string"},
                    "target_path": {"type": "string"},
                    "target_size_bytes": {"type": "integer", "minimum": 0},
                    "content_hash": {"type": "string"},
                    "diff_from_response": {"type": "boolean"},
                    "timestamp": {"type": "string", "format": "date-time"},
                },
            },
        },
        "policy_decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
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
                ],
                "properties": {
                    # Nullable for synthetic "allowed" entries (no rule matched).
                    "policy_id": {"type": ["string", "null"]},
                    "policy_version": {"type": ["string", "null"]},
                    "policy_set_version": {"type": "string"},
                    "evaluated_at": {"type": "string", "format": "date-time"},
                    "verdict": {
                        "type": "string",
                        "enum": ["allowed", "blocked", "redacted", "alerted"],
                    },
                    "enforcement_mode": {
                        "type": "string",
                        "enum": list(ENFORCEMENT_MODES),
                    },
                    "matched_classes": {"type": "array", "items": {"type": "string"}},
                    # null when enforcement_mode == enforced; bool otherwise.
                    "would_have_blocked": {"type": ["boolean", "null"]},
                    "redactions_applied": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["location", "before_hash", "after_hash"],
                            "properties": {
                                "location": {"type": "string", "enum": ["prompt", "response"]},
                                "before_hash": {"type": "string"},
                                "after_hash": {"type": "string"},
                            },
                        },
                    },
                    # Closed enum or null.
                    "error_reason": {
                        "anyOf": [
                            {"type": "null"},
                            {"type": "string", "enum": list(ERROR_REASONS)},
                        ],
                    },
                    # Structured AlertDelivery or null.
                    "alert_id": {
                        "anyOf": [
                            {"type": "null"},
                            {
                                "type": "object",
                                "required": ["id", "delivery_status"],
                                "properties": {
                                    "id": {"type": "string"},
                                    "delivery_status": {
                                        "type": "string",
                                        "enum": list(ALERT_DELIVERY_STATUSES),
                                    },
                                    "delivered_at": {
                                        "type": ["string", "null"],
                                        "format": "date-time",
                                    },
                                },
                            },
                        ],
                    },
                },
            },
        },
        "evidence": {
            "type": "object",
            "required": ["receipt_hash", "captured_by", "capture_method"],
            "properties": {
                "receipt_hash": {"type": "string", "pattern": r"^sha256:[0-9a-f]{64}$"},
                "captured_by": {"type": "string"},
                "capture_method": {"type": "string"},
                "signature": {"type": ["string", "null"]},
            },
        },
        "retention": {
            "type": "object",
            "required": ["retain_until", "retention_policy"],
            "properties": {
                "retain_until": {"type": "string", "format": "date"},
                "retention_policy": {"type": "string"},
                "deletable_after": {"type": "string", "format": "date-time"},
                "legal_hold": {"type": "boolean"},
            },
        },
    },
}
