"""Surface adapters — API-shape-specific glue for Gemini + Anthropic.

Each adapter knows how to:
  - extract the latest user prompt text + the assistant response text
  - replace assistant message text in-place (for redaction swap-back)
  - redact a response payload in-place (collapse text parts/blocks)
  - construct a block payload in the surface's response shape

The middleware chain is otherwise surface-agnostic.
"""

from __future__ import annotations

import time
from typing import Any, Dict, Iterator, List, Tuple


# ---------------------------------------------------------------------------
# Gemini (generativelanguage.googleapis.com)
# ---------------------------------------------------------------------------


class GeminiSurface:
    name = "gemini"

    @staticmethod
    def extract_prompt_text(body: Dict[str, Any]) -> str:
        """systemInstruction + text parts of the LAST role=user content."""
        chunks: List[str] = []
        sys_inst = body.get("systemInstruction") or body.get("system_instruction")
        if isinstance(sys_inst, dict):
            for part in sys_inst.get("parts", []) or []:
                t = part.get("text") if isinstance(part, dict) else None
                if t:
                    chunks.append(t)
        for content in reversed(body.get("contents", []) or []):
            if not isinstance(content, dict) or content.get("role") != "user":
                continue
            for part in content.get("parts", []) or []:
                t = part.get("text") if isinstance(part, dict) else None
                if t:
                    chunks.append(t)
            break
        return "\n\n".join(chunks).strip()

    @staticmethod
    def extract_response_text(payload: Dict[str, Any]) -> str:
        chunks: List[str] = []
        for cand in payload.get("candidates", []) or []:
            if not isinstance(cand, dict):
                continue
            content = cand.get("content") or {}
            for part in content.get("parts", []) or []:
                if isinstance(part, dict):
                    t = part.get("text")
                    if t:
                        chunks.append(t)
        return "\n\n".join(chunks)

    @staticmethod
    def redact_response(payload: Dict[str, Any], new_text: str) -> Dict[str, Any]:
        out = dict(payload)
        candidates = list(payload.get("candidates", []) or [])
        if not candidates:
            out["candidates"] = [{
                "content": {"role": "model", "parts": [{"text": new_text}]},
                "finishReason": "STOP", "index": 0,
            }]
            return out
        first = dict(candidates[0])
        content = dict(first.get("content", {}))
        new_parts: List[Dict[str, Any]] = []
        replaced = False
        for part in content.get("parts", []) or []:
            if isinstance(part, dict) and "text" in part:
                if not replaced:
                    new_parts.append({"text": new_text})
                    replaced = True
            else:
                new_parts.append(part)
        if not replaced:
            new_parts.insert(0, {"text": new_text})
        content["parts"] = new_parts
        first["content"] = content
        candidates[0] = first
        out["candidates"] = candidates
        return out

    @staticmethod
    def assistant_message_iter(body: Dict[str, Any]) -> Iterator[Tuple[Dict[str, Any], str]]:
        """Yield (content_dict, concatenated_text) for each role=model entry."""
        for content in body.get("contents", []) or []:
            if not isinstance(content, dict) or content.get("role") != "model":
                continue
            text_parts: List[str] = []
            for part in content.get("parts", []) or []:
                if isinstance(part, dict):
                    t = part.get("text")
                    if t:
                        text_parts.append(t)
            yield content, "\n\n".join(text_parts)

    @staticmethod
    def replace_assistant_message_text(msg: Dict[str, Any], new_text: str) -> None:
        new_parts: List[Dict[str, Any]] = []
        replaced = False
        for part in msg.get("parts", []) or []:
            if isinstance(part, dict) and "text" in part:
                if not replaced:
                    new_parts.append({"text": new_text})
                    replaced = True
            else:
                new_parts.append(part)
        if not replaced:
            new_parts.insert(0, {"text": new_text})
        msg["parts"] = new_parts

    @staticmethod
    def build_block_payload(model: str, message: str) -> Dict[str, Any]:
        return {
            "candidates": [{
                "content": {"role": "model", "parts": [{"text": message}]},
                "finishReason": "OTHER",
                "index": 0,
                "safetyRatings": [],
            }],
            "modelVersion": model,
        }


# ---------------------------------------------------------------------------
# Anthropic (api.anthropic.com/v1/messages)
# ---------------------------------------------------------------------------


class AnthropicSurface:
    name = "anthropic"

    @staticmethod
    def extract_prompt_text(body: Dict[str, Any]) -> str:
        """`system` field + text blocks of the LAST role=user message."""
        chunks: List[str] = []
        system = body.get("system")
        if isinstance(system, str):
            chunks.append(system)
        elif isinstance(system, list):
            for block in system:
                if isinstance(block, dict) and block.get("type") == "text":
                    t = block.get("text")
                    if t:
                        chunks.append(t)
        for msg in reversed(body.get("messages", []) or []):
            if not isinstance(msg, dict) or msg.get("role") != "user":
                continue
            content = msg.get("content")
            if isinstance(content, str):
                chunks.append(content)
            elif isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        t = block.get("text")
                        if t:
                            chunks.append(t)
            break
        return "\n\n".join(chunks).strip()

    @staticmethod
    def extract_response_text(payload: Dict[str, Any]) -> str:
        chunks: List[str] = []
        for block in payload.get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "text":
                t = block.get("text")
                if t:
                    chunks.append(t)
        return "\n\n".join(chunks)

    @staticmethod
    def redact_response(payload: Dict[str, Any], new_text: str) -> Dict[str, Any]:
        out = dict(payload)
        new_content: List[Dict[str, Any]] = []
        replaced = False
        for block in payload.get("content", []) or []:
            if isinstance(block, dict) and block.get("type") == "text":
                if not replaced:
                    new_content.append({"type": "text", "text": new_text})
                    replaced = True
            else:
                new_content.append(block)
        if not replaced:
            new_content.insert(0, {"type": "text", "text": new_text})
        out["content"] = new_content
        return out

    @staticmethod
    def assistant_message_iter(body: Dict[str, Any]) -> Iterator[Tuple[Dict[str, Any], str]]:
        for msg in body.get("messages", []) or []:
            if not isinstance(msg, dict) or msg.get("role") != "assistant":
                continue
            content = msg.get("content")
            if isinstance(content, str):
                yield msg, content
            elif isinstance(content, list):
                text_parts: List[str] = []
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        t = block.get("text")
                        if t:
                            text_parts.append(t)
                yield msg, "\n\n".join(text_parts)

    @staticmethod
    def replace_assistant_message_text(msg: Dict[str, Any], new_text: str) -> None:
        content = msg.get("content")
        if isinstance(content, str):
            msg["content"] = new_text
            return
        if not isinstance(content, list):
            msg["content"] = new_text
            return
        new_content: List[Dict[str, Any]] = []
        replaced = False
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                if not replaced:
                    new_content.append({"type": "text", "text": new_text})
                    replaced = True
            else:
                new_content.append(block)
        if not replaced:
            new_content.insert(0, {"type": "text", "text": new_text})
        msg["content"] = new_content

    @staticmethod
    def build_block_payload(model: str, message: str) -> Dict[str, Any]:
        return {
            "id": f"msg_truss_block_{int(time.time() * 1000)}",
            "type": "message",
            "role": "assistant",
            "model": model,
            "content": [{"type": "text", "text": message}],
            "stop_reason": "end_turn",
            "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0},
        }
