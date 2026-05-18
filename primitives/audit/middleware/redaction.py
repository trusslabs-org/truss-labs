"""Redaction-state middleware — owns the swap table that lets truss undo
its own response redactions before forwarding subsequent-turn history
upstream, so the model never sees a modified version of its own past output.

Why this exists: when truss redacts a response, the client (gemini-cli,
claude) stores the redacted string as the assistant turn in its history.
On the next user turn it sends that history back upstream. The model sees
its own apparent prior output as "[redacted], condition: ..." and starts
investigating the filter source instead of answering. This middleware
maintains a mapping from `hash(redacted_text) -> original_text` and rewrites
assistant turns in the incoming body back to their pre-redaction form.

Result: the upstream model sees an unbroken view of its own outputs; the
client/user continues to see the redacted form they already received.

Storage: in-process memory only. Lost on proxy restart. That's a deliberate
trade-off — persisting plaintext PHI alongside the redaction would defeat
the purpose. For multi-process or persistent deployments, see receipt-
anchored or tokenized variants (future work).
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, Optional

from .base import RouteContext, TrussMiddleware


log = logging.getLogger("truss.audit.redaction")


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class RedactionMiddleware(TrussMiddleware):
    """Swap-table for reversing response-phase redactions in subsequent-turn
    history. Single-process, in-memory."""

    def __init__(self):
        self._table: Dict[str, str] = {}

    def before_upstream(self, body: Dict[str, Any], ctx: RouteContext) -> Optional[Dict[str, Any]]:
        """Walk every assistant/model message in the body. If any of them
        exactly matches a known redacted output, swap it back to the original
        before forwarding upstream.
        """
        if not self._table:
            return None  # nothing to swap

        swaps = 0
        for msg, text in ctx.surface.assistant_message_iter(body):
            if not text:
                continue
            original = self._table.get(_hash(text))
            if original is not None and original != text:
                ctx.surface.replace_assistant_message_text(msg, original)
                swaps += 1
        if swaps:
            log.info("redaction: swapped %d assistant message(s) back to original before forwarding", swaps)
        return body if swaps else None

    def after_upstream(self, payload: Dict[str, Any], ctx: RouteContext) -> Optional[Dict[str, Any]]:
        """If the response was redacted this turn, record the mapping so the
        NEXT turn's history rewrite finds it.
        """
        if ctx.response_eval is None:
            return None
        if ctx.response_eval.final_verdict != "redacted":
            return None
        if not ctx.original_response_text or not ctx.final_response_text:
            return None
        # Key on the *redacted* (client-visible) text; value is what we'd
        # want the model to see on the next turn.
        self._table[_hash(ctx.final_response_text)] = ctx.original_response_text
        log.info("redaction: stored swap entry (redacted -> original)")
        return None
