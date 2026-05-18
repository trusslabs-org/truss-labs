"""Base middleware definitions for the truss audit chain."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


class Surface(Protocol):
    """API-shape adapter — knows how to extract text from / inject text into
    a specific upstream API's request and response bodies.
    """

    name: str

    def extract_prompt_text(self, body: Dict[str, Any]) -> str: ...
    def extract_response_text(self, payload: Dict[str, Any]) -> str: ...
    def redact_response(self, payload: Dict[str, Any], new_text: str) -> Dict[str, Any]: ...
    def assistant_message_iter(self, body: Dict[str, Any]): ...  # yields (msg_dict, text) pairs
    def replace_assistant_message_text(self, msg: Dict[str, Any], new_text: str) -> None: ...
    def build_block_payload(self, model: str, message: str) -> Dict[str, Any]: ...


@dataclass
class RouteContext:
    """Per-request state threaded through the middleware chain."""

    surface: Surface
    model: str
    actor: Dict[str, Any]
    tool: Dict[str, Any]
    wants_stream: bool

    # Filled by ClassifyMiddleware
    prompt_text: str = ""
    prompt_hits: List[Any] = field(default_factory=list)
    response_text: str = ""
    response_hits: List[Any] = field(default_factory=list)

    # Filled by PolicyMiddleware
    prompt_eval: Any = None
    response_eval: Any = None
    policy_evaluations: List[Any] = field(default_factory=list)

    # Filled when upstream is called
    upstream_payload: Optional[Dict[str, Any]] = None
    llm_meta: Optional[Dict[str, Any]] = None

    # Filled by RedactionMiddleware (tracks the original pre-redaction response
    # text so it can be stored in the swap table for next-turn history rewrite)
    original_response_text: str = ""
    final_response_text: str = ""
    final_payload: Optional[Dict[str, Any]] = None

    # Short-circuit signal — when set, chain skips upstream forward
    block_payload: Optional[Dict[str, Any]] = None
    block_reason: str = ""

    # Filled by ReceiptMiddleware
    receipt_path: Optional[str] = None


class TrussMiddleware(ABC):
    """Single-concern hook bundle. Override the phases you care about; the
    chain only invokes overridden methods.
    """

    def before_upstream(self, body: Dict[str, Any], ctx: RouteContext) -> Optional[Dict[str, Any]]:
        """Run before forwarding upstream. Return a mutated body to replace
        the in-flight body, or None to leave it alone. Set ctx.block_payload
        to short-circuit (skip upstream call and return that payload).
        """
        return None

    def after_upstream(self, payload: Dict[str, Any], ctx: RouteContext) -> Optional[Dict[str, Any]]:
        """Run after upstream returns. Return a mutated payload, or None.
        Set ctx.block_payload to short-circuit and return the block payload
        instead of upstream's response.
        """
        return None
