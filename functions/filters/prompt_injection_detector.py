"""
title: Prompt Injection Detector
description: Hard-blocks messages that contain common jailbreak and system-prompt
             override patterns: instruction overrides, role hijacking, system-prompt
             extraction attempts, DAN/jailbreak keywords, and LLM template injection
             markers. Logs the user ID and matched pattern name when enabled.
author: openweb-ui-local
version: 0.1.0
"""

import re
from typing import Optional

from pydantic import BaseModel, Field


_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("instruction override", re.compile(
        r"ignore\s+(all\s+|the\s+|previous\s+|above\s+|prior\s+){0,3}instructions?",
        re.IGNORECASE,
    )),

    ("role hijack", re.compile(
        r"\b(you\s+are\s+now|act\s+as(\s+a[n]?)?|pretend\s+(you\s+are|to\s+be))\b",
        re.IGNORECASE,
    )),

    ("system prompt extraction", re.compile(
        r"\b(repeat|print|output|show|reveal|disclose|tell\s+me|what\s+(are|is))\b"
        r".{0,60}"
        r"\b(system\s+prompt|system\s+message|instructions?|configuration|persona|rules|guidelines|directives?)\b",
        re.IGNORECASE | re.DOTALL,
    )),

    ("DAN / jailbreak keyword", re.compile(
        r"\b(DAN|jailbreak|developer\s+mode|god\s+mode|unrestricted\s+mode|no\s+restrictions|do\s+anything\s+now)\b",
        re.IGNORECASE,
    )),

    ("LLM template injection marker", re.compile(
        r"(\[INST\]|\[\/INST\]|<\|system\|>|<\|user\|>|<\|assistant\|>|<\|im_start\|>|<\|im_end\|>|<s>|</s>)",
        re.IGNORECASE,
    )),
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
        priority: int = Field(default=30, description="Execution order (lower runs first)")
        enabled: bool = Field(default=True)
        log_attempts: bool = Field(
            default=True,
            description="Log user ID and matched pattern name to container stdout on block",
        )

    def __init__(self):
        self.valves = self.Valves()

    async def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        if not self.valves.enabled:
            return body

        messages = body.get("messages", [])
        user_messages = [m for m in messages if m.get("role") == "user"]
        if not user_messages:
            return body

        text = _extract_text(user_messages[-1])

        for name, pattern in _PATTERNS:
            if pattern.search(text):
                if self.valves.log_attempts:
                    user_id = __user__.get("id", "unknown") if __user__ else "unknown"
                    print(
                        f"[prompt-injection-detector] blocked | user={user_id} | pattern={name}"
                    )
                raise Exception(
                    "Your message was flagged by our content policy and was not sent. "
                    "If you believe this is a mistake, please contact your administrator."
                )

        return body
