"""Redaction-state middleware — owns the swap table + block-strip set.

Solves two related "model sees its own modified history" failure modes:

1. REDACTION SWAP. When truss redacts a response, the client persists the
   redacted string as the assistant turn. On the next user turn it sends
   that history back upstream. The model sees its own apparent prior output
   as `[redacted], condition: ...` and starts investigating the filter source
   instead of answering. Fix: maintain `hash(redacted_text) → original_text`
   and rewrite assistant turns back to their pre-redaction form before
   forwarding.

2. BLOCK-PAYLOAD STRIP. When truss blocks a prompt, it synthesizes an
   assistant-shape response carrying the block message (e.g. "Patient address
   detected... Blocked per HIPAA review"). The client persists that as if the
   model wrote it. On every subsequent turn, the model sees its own apparent
   prior output as a structured HIPAA refusal it never wrote — and reasons
   "I apparently have safety filters active." Fix: track hashes of all truss-
   generated block payloads; in before_upstream, drop the matching assistant
   turn AND the preceding user turn (preserves alternation, presents the
   exchange to the model as if it never happened).

Both states are in-process memory only. Lost on proxy restart. That's a
deliberate trade-off — persisting plaintext PHI on disk would defeat the
redaction guarantee. See task #331 for the tokenized variant if persistence
ever becomes a real requirement.

Receipts for block + redact verdicts are unaffected by this middleware:
they record the full prompt and original response in the ledger, which is
disk you control. Only the upstream-history view changes.
"""

from __future__ import annotations

import hashlib
import sys
from typing import Any, Dict, Optional, Set

from .base import RouteContext, TrussMiddleware


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _log(msg: str) -> None:
    # Use sys.stderr.write directly (same path that works at module-import
    # time — confirmed during diagnosis). `print(..., file=sys.stderr)` and
    # `os.write(2, ...)` both silently dropped in async request context;
    # this path lands in proxy.log because truss exec wires the subprocess
    # stderr to that file.
    try:
        sys.stderr.write(f"[truss.redaction] {msg}\n")
        sys.stderr.flush()
    except Exception:
        pass


class RedactionMiddleware(TrussMiddleware):
    """Owns two pieces of in-process state:
      - `_table`: hash(redacted_text) → original_text (for swap-back)
      - `_block_hashes`: set of hashes of truss-generated block payload texts
        (for strip-from-history)

    Both run in `before_upstream` to mutate the body before upstream forward;
    both are populated in `before_upstream` (block-payload set this turn) or
    `after_upstream` (redaction recorded this turn).
    """

    def __init__(self):
        self._table: Dict[str, str] = {}
        self._block_hashes: Set[str] = set()

    def before_upstream(self, body: Dict[str, Any], ctx: RouteContext) -> Optional[Dict[str, Any]]:
        mutated = False

        # 1. Strip prior block exchanges (drop user+assistant pair where
        #    the assistant turn matches a known truss block payload).
        if self._block_hashes and hasattr(ctx.surface, "strip_block_exchanges"):
            body, stripped = ctx.surface.strip_block_exchanges(body, self._block_hashes)
            if stripped:
                _log(f"block-history: stripped {stripped} prior block exchange(s) from upstream history")
                mutated = True

        # 2. Swap prior redacted assistant turns back to original text.
        if self._table:
            swaps = 0
            for msg, text in ctx.surface.assistant_message_iter(body):
                if not text:
                    continue
                original = self._table.get(_hash(text))
                if original is not None and original != text:
                    ctx.surface.replace_assistant_message_text(msg, original)
                    swaps += 1
            if swaps:
                _log(f"redaction: swapped {swaps} assistant message(s) back to original before forwarding")
                mutated = True

        # 3. If THIS turn is being blocked at the prompt phase, record the
        #    block payload's text hash so future turns can strip it out of
        #    upstream history. PolicyMiddleware runs before this in the chain,
        #    so ctx.block_payload is already populated if the prompt blocked.
        if ctx.block_payload is not None and ctx.block_reason == "prompt":
            block_text = ctx.surface.extract_response_text(ctx.block_payload)
            if block_text:
                h = _hash(block_text)
                if h not in self._block_hashes:
                    self._block_hashes.add(h)
                    _log("block-history: recorded block payload hash (prompt-phase)")

        return body if mutated else None

    def after_upstream(self, payload: Dict[str, Any], ctx: RouteContext) -> Optional[Dict[str, Any]]:
        """Two recording paths:
          - If response was redacted, store swap entry for the next turn.
          - If response was blocked, record the block payload hash for stripping.
        """
        if ctx.response_eval is None:
            return None

        verdict = ctx.response_eval.final_verdict

        if verdict == "redacted":
            if ctx.original_response_text and ctx.final_response_text:
                self._table[_hash(ctx.final_response_text)] = ctx.original_response_text
                _log("redaction: stored swap entry (redacted -> original)")

        elif verdict == "blocked":
            # Response-phase block — block_payload set by PolicyMiddleware.after_upstream
            if ctx.block_payload is not None:
                block_text = ctx.surface.extract_response_text(ctx.block_payload)
                if block_text:
                    h = _hash(block_text)
                    if h not in self._block_hashes:
                        self._block_hashes.add(h)
                        _log("block-history: recorded block payload hash (response-phase)")

        return None
