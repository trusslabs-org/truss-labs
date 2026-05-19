"""Truss audit middleware chain.

Each middleware owns a single concern (classification, policy evaluation,
redaction state, receipt writing). The chain runs them in order across two
phases — `before_upstream` (mutate the request body or short-circuit with a
block) and `after_upstream` (mutate the upstream response, write receipts).

Mirrors the Soul OS kernel pattern at ~/dotfiles/soul/kernel/middleware/ but
HTTP-flavored instead of LLM-turn-flavored.
"""

from .base import RouteContext, TrussMiddleware
from .chain import MiddlewareChain
from .classify import ClassifyMiddleware
from .policy import PolicyMiddleware
from .redaction import RedactionMiddleware
from .receipt import ReceiptMiddleware

__all__ = [
    "RouteContext",
    "TrussMiddleware",
    "MiddlewareChain",
    "ClassifyMiddleware",
    "PolicyMiddleware",
    "RedactionMiddleware",
    "ReceiptMiddleware",
]
