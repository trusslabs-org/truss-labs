"""Chain orchestrator + upstream forward."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from fastapi import HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from .base import RouteContext, TrussMiddleware


log = logging.getLogger("truss.audit.chain")


class MiddlewareChain:
    """Runs each middleware's before_upstream, forwards to upstream, then runs
    after_upstream. Short-circuits if any middleware sets ctx.block_payload.
    """

    def __init__(self, middlewares: List[TrussMiddleware]):
        self.middlewares = middlewares
        self.before = [
            mw for mw in middlewares
            if mw.__class__.before_upstream != TrussMiddleware.before_upstream
        ]
        self.after = [
            mw for mw in middlewares
            if mw.__class__.after_upstream != TrussMiddleware.after_upstream
        ]

    async def run(
        self,
        body: Dict[str, Any],
        ctx: RouteContext,
        forward: Callable[[Dict[str, Any], RouteContext], "asyncio.Future[Dict[str, Any]]"],
        stream_emitter: Callable[[Dict[str, Any]], Any],
    ):
        """Execute the chain.

        `forward` is an async callable that POSTs to the upstream provider and
        returns (payload, latency_ms). It's surface-specific (different URL,
        different auth header name) and is injected by the route handler.

        `stream_emitter` is a callable that wraps a payload dict in a
        StreamingResponse with the surface-appropriate SSE shape.
        """
        # Pre-upstream phase
        for mw in self.before:
            replacement = mw.before_upstream(body, ctx)
            if replacement is not None:
                body = replacement
            if ctx.block_payload is not None:
                return self._respond(ctx.block_payload, ctx, stream_emitter)

        # Upstream forward
        try:
            payload, latency_ms = await forward(body, ctx)
        except HTTPException:
            raise
        except Exception as e:
            log.exception("upstream forward failed")
            raise HTTPException(status_code=502, detail=f"upstream forward failed: {e}") from e

        # Upstream itself can return non-2xx — pass through as-is
        if isinstance(payload, JSONResponse):
            return payload

        ctx.upstream_payload = payload
        ctx.llm_meta = {"latency_ms": latency_ms}

        # Post-upstream phase
        for mw in self.after:
            replacement = mw.after_upstream(payload, ctx)
            if replacement is not None:
                payload = replacement
            if ctx.block_payload is not None:
                return self._respond(ctx.block_payload, ctx, stream_emitter)

        # Stamp the receipt path on the returned body
        if ctx.receipt_path:
            payload = dict(payload)
            payload["trussReceipt"] = ctx.receipt_path

        ctx.final_payload = payload
        return self._respond(payload, ctx, stream_emitter)

    @staticmethod
    def _respond(payload: Dict[str, Any], ctx: RouteContext, stream_emitter):
        if ctx.wants_stream:
            return stream_emitter(payload)
        return JSONResponse(payload)
