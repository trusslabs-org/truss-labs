"""Unit tests for GeminiSurface, AnthropicSurface, ChatGPTSurface, ChatGPTWebSurface and ClaudeWebSurface.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from audit.surfaces import (
    GeminiSurface,
    AnthropicSurface,
    ChatGPTSurface,
    ChatGPTWebSurface,
    ClaudeWebSurface,
)


class TestGeminiSurface(unittest.TestCase):
    def test_extract_prompt_text(self) -> None:
        body = {
            "systemInstruction": {"parts": [{"text": "System instruction text"}]},
            "contents": [
                {"role": "user", "parts": [{"text": "Hello model"}]},
                {"role": "model", "parts": [{"text": "Hello user"}]},
                {"role": "user", "parts": [{"text": "Next prompt"}]}
            ]
        }
        prompt = GeminiSurface.extract_prompt_text(body)
        self.assertEqual(prompt, "System instruction text\n\nNext prompt")

    def test_extract_response_text(self) -> None:
        payload = {
            "candidates": [
                {"content": {"role": "model", "parts": [{"text": "Response text"}]}}
            ]
        }
        resp = GeminiSurface.extract_response_text(payload)
        self.assertEqual(resp, "Response text")

    def test_redact_response(self) -> None:
        payload = {
            "candidates": [
                {"content": {"role": "model", "parts": [{"text": "Original text"}]}}
            ]
        }
        redacted = GeminiSurface.redact_response(payload, "[redacted]")
        self.assertEqual(redacted["candidates"][0]["content"]["parts"][0]["text"], "[redacted]")


class TestAnthropicSurface(unittest.TestCase):
    def test_extract_prompt_text(self) -> None:
        body = {
            "system": "System instruction",
            "messages": [
                {"role": "user", "content": "Hello"},
                {"role": "assistant", "content": "Hi"},
                {"role": "user", "content": "How are you?"}
            ]
        }
        prompt = AnthropicSurface.extract_prompt_text(body)
        self.assertEqual(prompt, "System instruction\n\nHow are you?")

    def test_extract_response_text(self) -> None:
        payload = {
            "content": [
                {"type": "text", "text": "This is response content"}
            ]
        }
        resp = AnthropicSurface.extract_response_text(payload)
        self.assertEqual(resp, "This is response content")

    def test_redact_response(self) -> None:
        payload = {
            "content": [
                {"type": "text", "text": "Confidential details"}
            ]
        }
        redacted = AnthropicSurface.redact_response(payload, "[redacted]")
        self.assertEqual(redacted["content"][0]["text"], "[redacted]")


class TestChatGPTSurface(unittest.TestCase):
    def test_extract_prompt_text(self) -> None:
        body = {
            "messages": [
                {"role": "system", "content": "System prompt"},
                {"role": "user", "content": "Hello AI"},
                {"role": "assistant", "content": "Hello Human"},
                {"role": "user", "content": "Another prompt"}
            ]
        }
        prompt = ChatGPTSurface.extract_prompt_text(body)
        self.assertEqual(prompt, "System prompt\n\nAnother prompt")

    def test_extract_response_text(self) -> None:
        payload = {
            "choices": [
                {"message": {"role": "assistant", "content": "AI response content"}}
            ]
        }
        resp = ChatGPTSurface.extract_response_text(payload)
        self.assertEqual(resp, "AI response content")

    def test_redact_response(self) -> None:
        payload = {
            "choices": [
                {"message": {"role": "assistant", "content": "Unredacted response"}}
            ]
        }
        redacted = ChatGPTSurface.redact_response(payload, "[redacted]")
        self.assertEqual(redacted["choices"][0]["message"]["content"], "[redacted]")


class TestChatGPTWebSurface(unittest.TestCase):
    def test_extract_prompt_text(self) -> None:
        body = {
            "messages": [
                {
                    "id": "1",
                    "author": {"role": "system"},
                    "content": {"content_type": "text", "parts": ["You are a helpful assistant."]}
                },
                {
                    "id": "2",
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["Tell me a story."]}
                }
            ]
        }
        prompt = ChatGPTWebSurface.extract_prompt_text(body)
        self.assertEqual(prompt, "You are a helpful assistant.\n\nTell me a story.")

    def test_extract_response_text(self) -> None:
        payload = {
            "message": {
                "id": "msg-123",
                "author": {"role": "assistant"},
                "content": {"content_type": "text", "parts": ["Once upon a time..."]},
            }
        }
        resp = ChatGPTWebSurface.extract_response_text(payload)
        self.assertEqual(resp, "Once upon a time...")

    def test_redact_response(self) -> None:
        payload = {
            "message": {
                "id": "msg-123",
                "author": {"role": "assistant"},
                "content": {"content_type": "text", "parts": ["Confidential content"]},
            }
        }
        redacted = ChatGPTWebSurface.redact_response(payload, "[redacted]")
        self.assertEqual(redacted["message"]["content"]["parts"], ["[redacted]"])


class TestClaudeWebSurface(unittest.TestCase):
    def test_extract_prompt_text(self) -> None:
        body = {
            "messages": [
                {
                    "sender": "human",
                    "text": "Help me with coding."
                }
            ]
        }
        prompt = ClaudeWebSurface.extract_prompt_text(body)
        self.assertEqual(prompt, "Help me with coding.")

    def test_extract_response_text(self) -> None:
        payload = {
            "completion": "Sure, here'''s some code:"
        }
        resp = ClaudeWebSurface.extract_response_text(payload)
        self.assertEqual(resp, "Sure, here'''s some code:")

    def test_redact_response(self) -> None:
        payload = {
            "content": [
                {"type": "text", "text": "Secret code: 1234"}
            ]
        }
        redacted = ClaudeWebSurface.redact_response(payload, "[redacted]")
        self.assertEqual(redacted["content"][0]["text"], "[redacted]")
