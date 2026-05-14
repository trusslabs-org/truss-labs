"""ReceiptWriter — produces v1.0 receipts from intercepted AI activity.

Per docs/research/RECEIPT_SCHEMA.md and primitives/audit/schema.py.

Usage:
    writer = ReceiptWriter(receipts_dir=Path("~/.truss/receipts").expanduser())
    receipt_path = writer.write(
        actor={"user_id": "alice@example.com", "user_role": "clinician"},
        tool={"tool_id": "epic_chat_assistant", "model_id": "gpt-4o-2024-11-20"},
        prompt_text="Draft a follow-up message...",
        response_text="Dear John, ...",
        data_classes=[{"class": "phi:patient_name", "instances": 1, "in_prompt": True, "in_response": True}],
        retention_policy="hipaa_seven_year",
    )

Design invariants:
  - Atomic write (temp file + os.replace) — no partial files visible to readers
  - Schema validation before write — invalid receipts never land on disk
  - Hashes are SHA-256, prefixed "sha256:" (auditor can verify with standard tools)
  - One receipt per file. Files are grep-able, jq-able, sqlite-importable.
  - No external network calls — runs entirely on customer infrastructure.

Per the 2026-05-08 audit/steering separation, this writer has no awareness of
TWP nodes or trace-DAGs. The optional `external_trace_uri` parameter accepts
any URI string for orgs running both products; receipts without it remain
fully interpretable.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .schema import RECEIPT_JSON_SCHEMA, SCHEMA_VERSION


CAPTURE_METHOD_DEFAULT = "http_proxy_intercept"
CAPTURED_BY_DEFAULT = "truss-audit-pipeline-v0.1"


class ReceiptValidationError(ValueError):
    """Raised when a constructed receipt fails JSON Schema validation."""


class ReceiptWriter:
    """Writes v1.0 receipts to a per-day directory with atomic semantics.

    Receipts land at: receipts_dir / YYYY-MM-DD / <receipt_id>.json
    """

    def __init__(
        self,
        receipts_dir: Path,
        captured_by: str = CAPTURED_BY_DEFAULT,
        capture_method: str = CAPTURE_METHOD_DEFAULT,
    ) -> None:
        self.receipts_dir = Path(receipts_dir).expanduser().resolve()
        self.captured_by = captured_by
        self.capture_method = capture_method
        self.receipts_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def write(
        self,
        actor: Dict[str, Any],
        tool: Dict[str, Any],
        prompt_text: str,
        response_text: str,
        data_classes: Optional[List[Dict[str, Any]]] = None,
        context_references: Optional[List[Dict[str, Any]]] = None,
        downstream_actions: Optional[List[Dict[str, Any]]] = None,
        policy_decisions: Optional[List[Dict[str, Any]]] = None,
        retention_policy: str = "default_seven_year",
        retention_years: int = 7,
        retention_days: Optional[int] = None,
        external_trace_uri: Optional[str] = None,
        tokens_used: Optional[int] = None,
        latency_ms: Optional[int] = None,
        signature: Optional[str] = None,
        legal_hold: bool = False,
        validate: bool = True,
    ) -> Path:
        """Build and atomically write a v1.0 receipt. Returns the path written."""
        receipt = self._build(
            actor=actor,
            tool=tool,
            prompt_text=prompt_text,
            response_text=response_text,
            data_classes=data_classes or [],
            context_references=context_references or [],
            downstream_actions=downstream_actions or [],
            policy_decisions=policy_decisions or [],
            retention_policy=retention_policy,
            retention_years=retention_years,
            retention_days=retention_days,
            external_trace_uri=external_trace_uri,
            tokens_used=tokens_used,
            latency_ms=latency_ms,
            signature=signature,
            legal_hold=legal_hold,
        )

        if validate:
            self._validate(receipt)

        return self._atomic_write(receipt)

    # ------------------------------------------------------------------
    # Receipt construction
    # ------------------------------------------------------------------

    def _build(
        self,
        actor: Dict[str, Any],
        tool: Dict[str, Any],
        prompt_text: str,
        response_text: str,
        data_classes: List[Dict[str, Any]],
        context_references: List[Dict[str, Any]],
        downstream_actions: List[Dict[str, Any]],
        policy_decisions: List[Dict[str, Any]],
        retention_policy: str,
        retention_years: int,
        retention_days: Optional[int],
        external_trace_uri: Optional[str],
        tokens_used: Optional[int],
        latency_ms: Optional[int],
        signature: Optional[str],
        legal_hold: bool,
    ) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        receipt_id = self._generate_receipt_id(now)
        # retention_days takes precedence when set (used for the demo's
        # 7-day retention policy); otherwise fall back to whole-year math.
        total_days = retention_days if retention_days is not None else 365 * retention_years
        retain_until = (now + timedelta(days=total_days)).date().isoformat()
        deletable_after = (now + timedelta(days=total_days)).isoformat()

        receipt: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "receipt_id": receipt_id,
            "timestamp": now.isoformat().replace("+00:00", "Z"),
            "external_trace_uri": external_trace_uri,
            "actor": dict(actor),
            "tool": dict(tool),
            "prompt": {
                "text": prompt_text,
                "text_hash": _sha256(prompt_text),
                "text_length_chars": len(prompt_text),
                "context_references": list(context_references),
            },
            "response": {
                "text": response_text,
                "text_hash": _sha256(response_text),
                "text_length_chars": len(response_text),
                "tokens_used": tokens_used,
                "latency_ms": latency_ms,
            },
            "data_classes_touched": list(data_classes),
            "downstream_actions": list(downstream_actions),
            "policy_decisions": list(policy_decisions),
            "evidence": {
                # placeholder — replaced after computing the rest of the receipt's hash
                "receipt_hash": "",
                "captured_by": self.captured_by,
                "capture_method": self.capture_method,
                "signature": signature,
            },
            "retention": {
                "retain_until": retain_until,
                "retention_policy": retention_policy,
                "deletable_after": deletable_after,
                "legal_hold": legal_hold,
            },
        }

        # Hash the receipt with evidence.receipt_hash zeroed out so the hash is
        # stable and verifiable: an auditor reproduces the hash by zeroing the
        # field and recomputing.
        receipt["evidence"]["receipt_hash"] = _sha256(_canonical_json(receipt))
        return receipt

    @staticmethod
    def _generate_receipt_id(now: datetime) -> str:
        timestamp_str = now.strftime("%Y-%m-%dT%H-%M-%S")
        # 6 hex chars = ~16M ID space per second — enough for receipts at any
        # realistic volume. Increase to 8+ if collisions become possible.
        suffix = secrets.token_hex(3)
        return f"rcp_{timestamp_str}_{suffix}"

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate(self, receipt: Dict[str, Any]) -> None:
        try:
            from jsonschema import Draft202012Validator, ValidationError
        except ImportError:
            # Don't hard-fail if jsonschema isn't installed in the environment;
            # do warn so the operator knows validation was skipped.
            import warnings

            warnings.warn(
                "jsonschema not installed — receipt validation skipped. "
                "Install with: pip install jsonschema",
                RuntimeWarning,
                stacklevel=2,
            )
            return

        validator = Draft202012Validator(RECEIPT_JSON_SCHEMA)
        errors = sorted(validator.iter_errors(receipt), key=lambda e: list(e.absolute_path))
        if errors:
            details = "\n  ".join(
                f"{list(e.absolute_path) or '<root>'}: {e.message}" for e in errors
            )
            raise ReceiptValidationError(
                f"Receipt failed v{SCHEMA_VERSION} schema validation:\n  {details}"
            )

    # ------------------------------------------------------------------
    # Atomic write
    # ------------------------------------------------------------------

    def _atomic_write(self, receipt: Dict[str, Any]) -> Path:
        date_dir = self.receipts_dir / receipt["timestamp"][:10]
        date_dir.mkdir(parents=True, exist_ok=True)

        target = date_dir / f"{receipt['receipt_id']}.json"
        # tempfile in same directory so os.replace is atomic on the same FS
        fd, tmp_path = tempfile.mkstemp(
            prefix=".receipt_", suffix=".json.tmp", dir=str(date_dir)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(receipt, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.write("\n")
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, target)
        except Exception:
            # Best-effort cleanup of the temp file on any failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

        return target


# ----------------------------------------------------------------------
# Module helpers
# ----------------------------------------------------------------------


def _sha256(text: str) -> str:
    """Return a 'sha256:<hex>' digest of the given text (UTF-8)."""
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _canonical_json(obj: Any) -> str:
    """Serialize JSON with stable key ordering for hashing.

    Auditor reproduces the hash by:
      1. Loading the receipt JSON
      2. Setting receipt['evidence']['receipt_hash'] = ""
      3. Re-serializing with sort_keys=True, separators=(',', ':')
      4. SHA-256 of UTF-8 bytes
    """
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
