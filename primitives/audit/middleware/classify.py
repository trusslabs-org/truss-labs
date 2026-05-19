"""Classifier middleware — runs taxonomies against prompt + response text."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from ..classifier import ClassHit, Classifier
from .base import RouteContext, TrussMiddleware


class ClassifyMiddleware(TrussMiddleware):
    """Extracts text from the request (latest user turn) and response (model
    text). Runs every configured taxonomy classifier against both. The hits
    flow into PolicyMiddleware via ctx.
    """

    def __init__(self, classifiers: List[Classifier]):
        self.classifiers = classifiers

    def before_upstream(self, body: Dict[str, Any], ctx: RouteContext) -> Optional[Dict[str, Any]]:
        ctx.prompt_text = ctx.surface.extract_prompt_text(body)
        ctx.prompt_hits = self._classify_all(ctx.prompt_text, "prompt")
        return None

    def after_upstream(self, payload: Dict[str, Any], ctx: RouteContext) -> Optional[Dict[str, Any]]:
        text = ctx.surface.extract_response_text(payload)
        ctx.original_response_text = text
        ctx.response_text = text
        ctx.response_hits = self._classify_all(text, "response")
        return None

    def _classify_all(self, text: str, location: str) -> List[ClassHit]:
        hits: List[ClassHit] = []
        for clf in self.classifiers:
            hits.extend(clf.classify(text, location=location))
        return hits
