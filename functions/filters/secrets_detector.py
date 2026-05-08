"""
title: Secrets Detector
description: Hard-blocks messages that contain credentials or secrets before they
             reach the LLM provider. Covered: API keys (OpenAI, Anthropic, AWS,
             Google, GitHub), PEM private keys, database connection strings,
             JWT tokens, and Bearer tokens.
author: openweb-ui-local
version: 0.1.0
"""

import re
from typing import Optional

from pydantic import BaseModel, Field


_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("OpenAI API key",
     re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),

    ("Anthropic API key",
     re.compile(r"\bsk-ant-[A-Za-z0-9\-]{20,}\b")),

    ("AWS access key",
     re.compile(r"\bAKIA[0-9A-Z]{16}\b")),

    ("Google API key",
     re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b")),

    ("GitHub token",
     re.compile(r"\bgh[pousr]_[A-Za-z0-9]{36}\b")),

    ("PEM private key",
     re.compile(r"-----BEGIN [A-Z ]{0,30}PRIVATE KEY-----")),

    ("database connection string",
     re.compile(
         r"\b(postgresql|mysql|mongodb(?:\+srv)?|redis|amqp)://[^\s\"']{8,}",
         re.IGNORECASE,
     )),

    ("JWT token",
     re.compile(r"\beyJ[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+\b")),

    ("Bearer token",
     re.compile(r"\bBearer\s+[A-Za-z0-9\-._~+/]{20,}=*\b", re.IGNORECASE)),
]


def _extract_text(msg: dict) -> str:
    content = msg.get("content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=10, description="Execution order (lower runs first)")
        enabled: bool = Field(default=True)

    def __init__(self):
        self.valves = self.Valves()

    async def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        if not self.valves.enabled:
            return body

        messages = body.get("messages", [])
        user_messages = [m for m in messages if m.get("role") == "user"]
        if not user_messages:
            return body

        # Only scan the last user message — prior turns were already checked
        text = _extract_text(user_messages[-1])
        hits = [name for name, pattern in _PATTERNS if pattern.search(text)]

        if hits:
            raise Exception(
                "Your message was blocked because it contains sensitive credentials: "
                f"{', '.join(hits)}. Please remove them before sending."
            )

        return body
