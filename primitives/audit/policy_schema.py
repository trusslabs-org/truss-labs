"""Policy YAML schema — pydantic v2 models.

Source of truth for the YAML rule shape is docs/research/POLICY_ENGINE_SPEC.md
v0.2. This file mirrors that doc as code; when the doc changes, update both.

Usage:
    from primitives.audit.policy_schema import Policy
    raw = yaml.safe_load(open("~/.truss/policies/foo.yaml"))
    policy = Policy.model_validate(raw)   # raises pydantic.ValidationError on bad YAML

Design invariants:
  - One Policy = one YAML file (default; multi-rule files not yet supported in v0.1).
  - Verdict-discriminated config: a `block` policy MUST have block_config, a
    `redact` policy MUST have redact_config, an `alert` policy MUST have
    alert_config. There is no `verdict: allow` — absence of a matching rule
    means allowed.
  - Match classes are exactly one of {any_of, all_of}, not both, not neither.
  - The redact_with template only supports the `{class}` substitution token in
    v0.1; literal braces are rejected to keep the closed grammar honest.
  - schema_version is a string Literal["1.0"]; the loader rejects unknown
    versions rather than auto-migrating.
"""

from __future__ import annotations

import re
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


POLICY_SCHEMA_VERSION = "1.0"

# Closed grammar for redact_with templates in v0.1. Only {class} is supported.
# Future tokens (e.g. {instance_index}, {policy_id}) are NOT parsed; literal
# braces are forbidden so operators don't accidentally rely on undefined behavior.
_ALLOWED_REDACT_TOKENS = {"class"}
_BRACE_TOKEN_RE = re.compile(r"\{([^{}]*)\}")

# Policy IDs follow snake_case: lowercase letters, digits, underscores.
# Letters required somewhere — no all-numeric IDs.
_POLICY_ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,127}$")

# Namespaced class names: "phi:patient_address", "pii:ssn", etc.
# Namespace and local part both required, both snake-cased.
_NAMESPACED_CLASS_RE = re.compile(r"^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$")


# ---------------------------------------------------------------------------
# Match block
# ---------------------------------------------------------------------------


class MatchClasses(BaseModel):
    """Exactly one of any_of / all_of. Not both, not neither."""

    model_config = ConfigDict(extra="forbid")

    any_of: Optional[List[str]] = None
    all_of: Optional[List[str]] = None

    @model_validator(mode="after")
    def _exactly_one(self) -> "MatchClasses":
        any_set = self.any_of is not None
        all_set = self.all_of is not None
        if any_set == all_set:
            raise ValueError(
                "match.classes must declare exactly one of 'any_of' or 'all_of'"
            )
        chosen = self.any_of if any_set else self.all_of
        assert chosen is not None  # for type-checker
        if not chosen:
            raise ValueError(
                "match.classes any_of/all_of must contain at least one class"
            )
        for cls_name in chosen:
            if not _NAMESPACED_CLASS_RE.match(cls_name):
                raise ValueError(
                    f"match class {cls_name!r} is not namespaced "
                    "(expected 'namespace:local_name', e.g. 'phi:patient_address')"
                )
        return self

    def as_list(self) -> List[str]:
        """Return the active class list regardless of any_of vs all_of."""
        return list(self.any_of if self.any_of is not None else self.all_of or [])

    @property
    def mode(self) -> Literal["any_of", "all_of"]:
        return "any_of" if self.any_of is not None else "all_of"


class Match(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: Literal["prompt", "response"]
    destination: Literal["external_vendor", "internal", "any"]
    classes: MatchClasses


# ---------------------------------------------------------------------------
# Verdict-specific config blocks
# ---------------------------------------------------------------------------


class BlockConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_message: str = Field(
        ...,
        min_length=1,
        description="Shown to the user as-is when this policy blocks. "
        "No redaction applied; operators must not embed PII.",
    )


class RedactConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    redact_with: str = Field(
        ...,
        min_length=1,
        description="Template applied to every matched span. v0.1 supports "
        "only the {class} substitution token; literal braces are forbidden.",
    )
    classes_to_redact: Optional[List[str]] = Field(
        default=None,
        description="Subset of match.classes; defaults to all matched classes.",
    )

    @field_validator("redact_with")
    @classmethod
    def _validate_template(cls, v: str) -> str:
        for token in _BRACE_TOKEN_RE.findall(v):
            if token not in _ALLOWED_REDACT_TOKENS:
                raise ValueError(
                    f"redact_with template uses unsupported token {{{token}}}; "
                    f"v0.1 supports only {sorted(_ALLOWED_REDACT_TOKENS)}"
                )
        return v

    @field_validator("classes_to_redact")
    @classmethod
    def _validate_classes(cls, v: Optional[List[str]]) -> Optional[List[str]]:
        if v is None:
            return v
        if not v:
            raise ValueError("classes_to_redact, if set, must be non-empty")
        for cls_name in v:
            if not _NAMESPACED_CLASS_RE.match(cls_name):
                raise ValueError(
                    f"classes_to_redact entry {cls_name!r} is not namespaced"
                )
        return v


class AlertConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    webhook: Optional[str] = Field(
        default=None,
        description="HTTPS URL fired async on every match. v0.1 has no retry; "
        "delivery_status lands in the receipt as pending|delivered|failed.",
    )

    @field_validator("webhook")
    @classmethod
    def _validate_webhook(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return v
        if not (v.startswith("https://") or v.startswith("http://")):
            raise ValueError(
                "alert_config.webhook must be a fully qualified http(s):// URL"
            )
        return v


# ---------------------------------------------------------------------------
# Top-level Policy
# ---------------------------------------------------------------------------


class Policy(BaseModel):
    """A single YAML policy file parsed and validated.

    The verdict field discriminates which *_config block is required:
      - verdict=block  -> block_config required, others must be absent
      - verdict=redact -> redact_config required, others must be absent
      - verdict=alert  -> alert_config required, others must be absent
    """

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    policy_id: str
    policy_version: str = Field(..., min_length=1)
    description: Optional[str] = None

    match: Match
    verdict: Literal["block", "redact", "alert"]

    block_config: Optional[BlockConfig] = None
    redact_config: Optional[RedactConfig] = None
    alert_config: Optional[AlertConfig] = None

    audit_only: bool = False
    on_classifier_error: Literal["fail_open", "fail_closed"] = "fail_open"

    @field_validator("policy_id")
    @classmethod
    def _validate_policy_id(cls, v: str) -> str:
        if not _POLICY_ID_RE.match(v):
            raise ValueError(
                f"policy_id {v!r} must be snake_case "
                "(lowercase letters/digits/underscores, 3-128 chars, "
                "starts with a letter)"
            )
        return v

    @model_validator(mode="after")
    def _verdict_has_matching_config(self) -> "Policy":
        configs = {
            "block": self.block_config,
            "redact": self.redact_config,
            "alert": self.alert_config,
        }
        required = configs[self.verdict]
        if required is None:
            raise ValueError(
                f"verdict={self.verdict!r} requires a {self.verdict}_config block"
            )
        for verdict_name, cfg in configs.items():
            if verdict_name != self.verdict and cfg is not None:
                raise ValueError(
                    f"verdict={self.verdict!r} but {verdict_name}_config is "
                    "also set; only the matching config block is allowed"
                )
        return self

    @model_validator(mode="after")
    def _redact_classes_are_subset(self) -> "Policy":
        if self.verdict != "redact" or self.redact_config is None:
            return self
        ctr = self.redact_config.classes_to_redact
        if ctr is None:
            return self
        match_classes = set(self.match.classes.as_list())
        rogue = [c for c in ctr if c not in match_classes]
        if rogue:
            raise ValueError(
                f"redact_config.classes_to_redact contains classes not in "
                f"match.classes: {rogue}"
            )
        return self


__all__ = [
    "POLICY_SCHEMA_VERSION",
    "Policy",
    "Match",
    "MatchClasses",
    "BlockConfig",
    "RedactConfig",
    "AlertConfig",
]
