"""Receipt-writer middleware — emits the audit-trail JSON file at the end
of every turn (block, allow, or redact)."""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from ..classifier import ClassHit, to_data_classes_touched
from ..receipt_writer import ReceiptWriter
from .base import RouteContext, TrussMiddleware


class ReceiptMiddleware(TrussMiddleware):
    def __init__(self, writer: ReceiptWriter):
        self.writer = writer

    def before_upstream(self, body: Dict[str, Any], ctx: RouteContext) -> Optional[Dict[str, Any]]:
        # On a prompt-phase block the chain skips after_upstream entirely;
        # write the receipt here so the audit trail still lands.
        if ctx.block_payload is not None and ctx.block_reason == "prompt":
            self._write(ctx, prompt_only=True)
        return None

    def after_upstream(self, payload: Dict[str, Any], ctx: RouteContext) -> Optional[Dict[str, Any]]:
        self._write(ctx, prompt_only=False)
        return None

    def _write(self, ctx: RouteContext, prompt_only: bool) -> None:
        prompt_text = ctx.prompt_text
        response_text = "" if prompt_only else (ctx.final_response_text or ctx.response_text)
        prompt_hits: List[ClassHit] = ctx.prompt_hits
        response_hits: List[ClassHit] = [] if prompt_only else ctx.response_hits
        data_classes = to_data_classes_touched(prompt_hits + response_hits)

        policy_decisions: List[Dict[str, Any]] = []
        for ev in ctx.policy_evaluations:
            policy_decisions.extend(ev.receipt_payload())

        path = self.writer.write(
            actor=ctx.actor,
            tool=ctx.tool,
            prompt_text=prompt_text,
            response_text=response_text,
            data_classes=data_classes,
            policy_decisions=policy_decisions,
            retention_policy="default_seven_year",
            retention_years=7,
            retention_days=None,
            tokens_used=(ctx.llm_meta or {}).get("tokens_used"),
            latency_ms=(ctx.llm_meta or {}).get("latency_ms"),
        )
        ctx.receipt_path = str(path)
        # Stamp the receipt path onto a block payload too so the client sees it.
        if ctx.block_payload is not None and "trussReceipt" not in ctx.block_payload:
            ctx.block_payload["trussReceipt"] = str(path)
