"""Normalized policy events for contextual policy evaluation."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


PolicyEventType = Literal[
    "prompt",
    "response",
    "browser_prompt",
    "browser_response",
    "browser_upload",
    "browser_download",
    "browser_navigation",
]

PolicyDestination = Literal["external_vendor", "internal", "any"]


class PolicyEvent(BaseModel):
    """One normalized event handed to the policy engine."""

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1)
    type: PolicyEventType
    surface: str = Field(..., min_length=1)
    vendor: str | None = None
    actor: dict[str, Any] = Field(default_factory=dict)
    destination: PolicyDestination
    data: dict[str, Any] = Field(default_factory=dict)
    context: dict[str, Any] = Field(default_factory=dict)
    session_state: dict[str, Any] = Field(default_factory=dict)

    @property
    def direction(self) -> Literal["prompt", "response"]:
        """Map event type to the legacy prompt/response direction."""
        if self.type in {"response", "browser_response"}:
            return "response"
        return "prompt"

    @property
    def text(self) -> str:
        """Return the event text payload, defaulting to an empty string."""
        value = self.data.get("text")
        return value if isinstance(value, str) else ""


def event_type_for_direction(
    direction: Literal["prompt", "response"],
    *,
    surface: str,
) -> PolicyEventType:
    """Choose the normalized event type for a legacy direction/surface pair."""
    if surface == "chrome_extension":
        return "browser_prompt" if direction == "prompt" else "browser_response"
    return direction


__all__ = [
    "PolicyDestination",
    "PolicyEvent",
    "PolicyEventType",
    "event_type_for_direction",
]
