"""Surface adapters — API-shape-specific glue for Gemini + Anthropic + ChatGPT.

Each adapter knows how to:
  - extract the latest user prompt text + the assistant response text
  - replace assistant message text in-place (for redaction swap-back)
  - strip prior block-exchange pairs from history (for block-history strip)
  - redact a response payload in-place (collapse text parts/blocks)
  - construct a block payload in the surface's response shape

The middleware chain is otherwise surface-agnostic.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, Iterator, List, Set, Tuple


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


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

    @staticmethod
    def strip_block_exchanges(body: Dict[str, Any], drop_hashes: Set[str]) -> Tuple[Dict[str, Any], int]:
        """Walk contents[]; for any model turn whose concatenated text hashes
        into `drop_hashes`, drop that turn AND the immediately preceding user
        turn. Preserves alternation; presents the exchange to the model as if
        it never happened. Returns (new_body, count_of_pairs_dropped).
        """
        contents = body.get("contents", []) or []
        new_contents: List[Dict[str, Any]] = []
        dropped = 0
        for content in contents:
            if not isinstance(content, dict):
                new_contents.append(content)
                continue
            if content.get("role") == "model":
                text_parts: List[str] = []
                for part in content.get("parts", []) or []:
                    if isinstance(part, dict):
                        t = part.get("text")
                        if t:
                            text_parts.append(t)
                text = "\n\n".join(text_parts)
                if text and _hash_text(text) in drop_hashes:
                    # Drop this model turn AND the immediately preceding user turn (if any)
                    if new_contents and isinstance(new_contents[-1], dict) and new_contents[-1].get("role") == "user":
                        new_contents.pop()
                    dropped += 1
                    continue
            new_contents.append(content)
        if dropped:
            body = dict(body)
            body["contents"] = new_contents
        return body, dropped


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

    @staticmethod
    def strip_block_exchanges(body: Dict[str, Any], drop_hashes: Set[str]) -> Tuple[Dict[str, Any], int]:
        """Walk messages[]; for any assistant message whose text hashes into
        `drop_hashes`, drop it AND the immediately preceding user message.
        Anthropic enforces alternation more strictly than Gemini — dropping
        the pair preserves it. Returns (new_body, count_of_pairs_dropped).
        """
        messages = body.get("messages", []) or []
        new_messages: List[Dict[str, Any]] = []
        dropped = 0
        for msg in messages:
            if not isinstance(msg, dict):
                new_messages.append(msg)
                continue
            if msg.get("role") == "assistant":
                content = msg.get("content")
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    text_parts: List[str] = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            t = block.get("text")
                            if t:
                                text_parts.append(t)
                    text = "\n\n".join(text_parts)
                else:
                    text = ""
                if text and _hash_text(text) in drop_hashes:
                    if new_messages and isinstance(new_messages[-1], dict) and new_messages[-1].get("role") == "user":
                        new_messages.pop()
                    dropped += 1
                    continue
            new_messages.append(msg)
        if dropped:
            body = dict(body)
            body["messages"] = new_messages
        return body, dropped


# ---------------------------------------------------------------------------
# ChatGPT / OpenAI Chat Completions (api.openai.com/v1/chat/completions)
# ---------------------------------------------------------------------------


class ChatGPTSurface:
    name = "chatgpt"

    @staticmethod
    def extract_prompt_text(body: Dict[str, Any]) -> str:
        """Extract prompt text: system message(s) + the LAST user message."""
        chunks: List[str] = []
        for msg in body.get("messages", []) or []:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            content = msg.get("content")
            if role == "system" and isinstance(content, str):
                chunks.append(content)
        for msg in reversed(body.get("messages", []) or []):
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            content = msg.get("content")
            if role == "user" and isinstance(content, str):
                chunks.append(content)
                break
        return "\n\n".join(chunks).strip()

    @staticmethod
    def extract_response_text(payload: Dict[str, Any]) -> str:
        """Extract response text from first choice."""
        chunks: List[str] = []
        for choice in payload.get("choices", []) or []:
            if not isinstance(choice, dict):
                continue
            msg = choice.get("message")
            if isinstance(msg, dict):
                content = msg.get("content")
                if content:
                    chunks.append(content)
        return "\n\n".join(chunks)

    @staticmethod
    def redact_response(payload: Dict[str, Any], new_text: str) -> Dict[str, Any]:
        """Redact response in-place on the first choice."""
        out = dict(payload)
        choices = list(payload.get("choices", []) or [])
        if not choices:
            out["choices"] = [{
                "message": {"role": "assistant", "content": new_text},
                "finish_reason": "stop", "index": 0,
            }]
            return out
        first = dict(choices[0])
        msg = dict(first.get("message", {}))
        msg["content"] = new_text
        first["message"] = msg
        choices[0] = first
        out["choices"] = choices
        return out

    @staticmethod
    def assistant_message_iter(body: Dict[str, Any]) -> Iterator[Tuple[Dict[str, Any], str]]:
        for msg in body.get("messages", []) or []:
            if not isinstance(msg, dict) or msg.get("role") != "assistant":
                continue
            content = msg.get("content")
            if isinstance(content, str):
                yield msg, content

    @staticmethod
    def replace_assistant_message_text(msg: Dict[str, Any], new_text: str) -> None:
        msg["content"] = new_text

    @staticmethod
    def build_block_payload(model: str, message: str) -> Dict[str, Any]:
        return {
            "id": f"chatcmpl-truss-block-{int(time.time() * 1000)}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": message},
                "finish_reason": "content_filter"
            }],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
        }

    @staticmethod
    def strip_block_exchanges(body: Dict[str, Any], drop_hashes: Set[str]) -> Tuple[Dict[str, Any], int]:
        messages = body.get("messages", []) or []
        new_messages: List[Dict[str, Any]] = []
        dropped = 0
        for msg in messages:
            if not isinstance(msg, dict):
                new_messages.append(msg)
                continue
            if msg.get("role") == "assistant":
                content = msg.get("content")
                if isinstance(content, str) and content and _hash_text(content) in drop_hashes:
                    if new_messages and isinstance(new_messages[-1], dict) and new_messages[-1].get("role") == "user":
                        new_messages.pop()
                    dropped += 1
                    continue
            new_messages.append(msg)
        if dropped:
            body = dict(body)
            body["messages"] = new_messages
        return body, dropped


# ---------------------------------------------------------------------------
# ChatGPT Web UI /backend-api/conversation shape
# ---------------------------------------------------------------------------


class ChatGPTWebSurface:
    name = "chatgpt_web"

    @staticmethod
    def extract_prompt_text(body: Dict[str, Any]) -> str:
        """Extract prompt text from ChatGPT Web /backend-api/conversation."""
        chunks: List[str] = []
        for msg in body.get("messages", []) or []:
            if not isinstance(msg, dict):
                continue
            role = msg.get("author", {}).get("role")
            content = msg.get("content", {})
            if role == "system" and isinstance(content, dict):
                parts = content.get("parts", []) or []
                for p in parts:
                    if isinstance(p, str) and p:
                        chunks.append(p)
        for msg in reversed(body.get("messages", []) or []):
            if not isinstance(msg, dict):
                continue
            role = msg.get("author", {}).get("role")
            content = msg.get("content", {})
            if role == "user" and isinstance(content, dict):
                parts = content.get("parts", []) or []
                for p in parts:
                    if isinstance(p, str) and p:
                        chunks.append(p)
                break
        return "\n\n".join(chunks).strip()

    @staticmethod
    def extract_response_text(payload: Dict[str, Any]) -> str:
        """Extract response text from ChatGPT Web response payload."""
        message = payload.get("message", {}) or {}
        content = message.get("content", {}) or {}
        parts = content.get("parts", []) or []
        chunks: List[str] = []
        for p in parts:
            if isinstance(p, str) and p:
                chunks.append(p)
        return "\n\n".join(chunks)

    @staticmethod
    def redact_response(payload: Dict[str, Any], new_text: str) -> Dict[str, Any]:
        """Redact response in-place on ChatGPT Web payload."""
        out = dict(payload)
        msg = dict(payload.get("message", {}) or {})
        content = dict(msg.get("content", {}) or {})
        content["parts"] = [new_text]
        msg["content"] = content
        out["message"] = msg
        return out

    @staticmethod
    def assistant_message_iter(body: Dict[str, Any]) -> Iterator[Tuple[Dict[str, Any], str]]:
        for msg in body.get("messages", []) or []:
            if not isinstance(msg, dict):
                continue
            role = msg.get("author", {}).get("role")
            if role != "assistant":
                continue
            content = msg.get("content", {}) or {}
            parts = content.get("parts", []) or []
            text_parts: List[str] = []
            for p in parts:
                if isinstance(p, str) and p:
                    text_parts.append(p)
            yield msg, "\n\n".join(text_parts)

    @staticmethod
    def replace_assistant_message_text(msg: Dict[str, Any], new_text: str) -> None:
        content = msg.get("content") or {}
        content["parts"] = [new_text]
        msg["content"] = content

    @staticmethod
    def build_block_payload(model: str, message: str) -> Dict[str, Any]:
        return {
            "message": {
                "id": "msg-truss-block",
                "author": {"role": "assistant"},
                "content": {"content_type": "text", "parts": [message]},
                "status": "finished"
            }
        }

    @staticmethod
    def strip_block_exchanges(body: Dict[str, Any], drop_hashes: Set[str]) -> Tuple[Dict[str, Any], int]:
        messages = body.get("messages", []) or []
        new_messages: List[Dict[str, Any]] = []
        dropped = 0
        for msg in messages:
            if not isinstance(msg, dict):
                new_messages.append(msg)
                continue
            role = msg.get("author", {}).get("role")
            if role == "assistant":
                content = msg.get("content", {}) or {}
                parts = content.get("parts", []) or []
                text = "\n\n".join([p for p in parts if isinstance(p, str)])
                if text and _hash_text(text) in drop_hashes:
                    if new_messages and isinstance(new_messages[-1], dict) and new_messages[-1].get("author", {}).get("role") == "user":
                        new_messages.pop()
                    dropped += 1
                    continue
            new_messages.append(msg)
        if dropped:
            body = dict(body)
            body["messages"] = new_messages
        return body, dropped


# ---------------------------------------------------------------------------
# Claude Web UI /api/ organizations/.../chat_conversations/.../completion shape
# ---------------------------------------------------------------------------


class ClaudeWebSurface:
    name = "claude_web"

    @staticmethod
    def extract_prompt_text(body: Dict[str, Any]) -> str:
        """Extract prompt text from Claude Web request payload."""
        chunks: List[str] = []
        
        # 1. Try to extract from top-level prompt or text keys (typical for Claude Web completions)
        for key in ["prompt", "text", "content"]:
            val = body.get(key)
            if isinstance(val, str) and val.strip():
                chunks.append(val.strip())
                break
            elif isinstance(val, list):
                for block in val:
                    if isinstance(block, dict) and block.get("type") == "text":
                        t = block.get("text")
                        if t: chunks.append(t)
                    elif isinstance(block, str):
                        chunks.append(block)
                if chunks:
                    break
        
        # 2. Fall back to messages array if top-level extraction didn't yield anything
        if not chunks:
            for msg in reversed(body.get("messages", []) or []):
                if not isinstance(msg, dict):
                    continue
                role = msg.get("role") or msg.get("sender")
                if role in ("user", "human"):
                    content = msg.get("content") or msg.get("text")
                    if isinstance(content, str):
                        chunks.append(content)
                    elif isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                t = block.get("text")
                                if t:
                                    chunks.append(t)
                            elif isinstance(block, str):
                                chunks.append(block)
                    break
                    
        return "\n\n".join(chunks).strip()
    def extract_response_text(payload: Dict[str, Any]) -> str:
        """Extract response text from Claude Web response payload."""
        completion = payload.get("completion")
        if isinstance(completion, str):
            return completion
        content = payload.get("content")
        if isinstance(content, str):
            return content
        elif isinstance(content, list):
            chunks: List[str] = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    t = block.get("text")
                    if t:
                        chunks.append(t)
            return "\n\n".join(chunks)
        return ""

    @staticmethod
    def redact_response(payload: Dict[str, Any], new_text: str) -> Dict[str, Any]:
        """Redact response in-place on Claude Web payload."""
        out = dict(payload)
        if "completion" in payload:
            out["completion"] = new_text
            return out
        content = payload.get("content")
        if isinstance(content, str):
            out["content"] = new_text
        elif isinstance(content, list):
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
            out["content"] = new_content
        else:
            out["content"] = new_text
        return out

    @staticmethod
    def assistant_message_iter(body: Dict[str, Any]) -> Iterator[Tuple[Dict[str, Any], str]]:
        for msg in body.get("messages", []) or []:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role") or msg.get("sender")
            if role not in ("assistant", "model"):
                continue
            content = msg.get("content") or msg.get("text")
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
        if "content" in msg:
            content = msg["content"]
            if isinstance(content, str):
                msg["content"] = new_text
            elif isinstance(content, list):
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
            else:
                msg["content"] = new_text
        elif "text" in msg:
            msg["text"] = new_text
        else:
            msg["text"] = new_text

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

    @staticmethod
    def strip_block_exchanges(body: Dict[str, Any], drop_hashes: Set[str]) -> Tuple[Dict[str, Any], int]:
        messages = body.get("messages", []) or []
        new_messages: List[Dict[str, Any]] = []
        dropped = 0
        for msg in messages:
            if not isinstance(msg, dict):
                new_messages.append(msg)
                continue
            role = msg.get("role") or msg.get("sender")
            if role in ("assistant", "model"):
                content = msg.get("content") or msg.get("text")
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    text_parts: List[str] = []
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            t = block.get("text")
                            if t:
                                text_parts.append(t)
                    text = "\n\n".join(text_parts)
                else:
                    text = ""
                if text and _hash_text(text) in drop_hashes:
                    if new_messages and isinstance(new_messages[-1], dict) and new_messages[-1].get("role", new_messages[-1].get("sender")) in ("user", "human"):
                        new_messages.pop()
                    dropped += 1
                    continue
            new_messages.append(msg)
        if dropped:
            body = dict(body)
            body["messages"] = new_messages
        return body, dropped
