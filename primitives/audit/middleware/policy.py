"""Policy-engine middleware — evaluates classifier hits against the loaded
PolicySet and produces verdicts. Short-circuits the chain on block."""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..policy_engine import evaluate
from ..policy_loader import PolicySet
from .base import RouteContext, TrussMiddleware


class PolicyMiddleware(TrussMiddleware):
    """Runs policy evaluation in both phases. On a prompt-phase block the
    chain short-circuits before upstream is called. On a response-phase
    block, upstream's reply is replaced with the block payload (receipt
    still gets written by ReceiptMiddleware).
    """

    def __init__(self, policy_set: PolicySet):
        self.policy_set = policy_set

    def before_upstream(self, body: Dict[str, Any], ctx: RouteContext) -> Optional[Dict[str, Any]]:
        ev = evaluate(
            text=ctx.prompt_text,
            direction="prompt",
            destination="external_vendor",
            class_hits=ctx.prompt_hits,
            policy_set=self.policy_set,
        )
        ctx.prompt_eval = ev
        ctx.policy_evaluations.append(ev)

        if ev.final_verdict == "blocked":
            ctx.block_payload = ctx.surface.build_block_payload(
                ctx.model,
                ev.block_user_message or "[blocked by truss policy]",
            )
            ctx.block_reason = "prompt"
        return None

    def after_upstream(self, payload: Dict[str, Any], ctx: RouteContext) -> Optional[Dict[str, Any]]:
        ev = evaluate(
            text=ctx.response_text,
            direction="response",
            destination="external_vendor",
            class_hits=ctx.response_hits,
            policy_set=self.policy_set,
        )
        ctx.response_eval = ev
        ctx.policy_evaluations.append(ev)

        if ev.final_verdict == "blocked":
            ctx.block_payload = ctx.surface.build_block_payload(
                ctx.model,
                ev.block_user_message or "[blocked by truss policy]",
            )
            ctx.block_reason = "response"
            return None

        if ev.final_verdict == "redacted" and ev.mutated_text:
            ctx.final_response_text = ev.mutated_text
            return ctx.surface.redact_response(payload, ev.mutated_text)

        ctx.final_response_text = ctx.response_text
        return None
