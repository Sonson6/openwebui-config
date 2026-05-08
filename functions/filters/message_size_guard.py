"""
title: Message Size Guard
description: Blocks messages that exceed a configurable byte threshold to prevent
             accidental data dumps and excessive token consumption. Applies to the
             last user message only by default.
author: openweb-ui-local
version: 0.1.0
"""

from typing import Optional

from pydantic import BaseModel, Field


def _content_bytes(msg: dict) -> int:
    content = msg.get("content", "")
    if isinstance(content, str):
        return len(content.encode())
    if isinstance(content, list):
        return sum(
            len(part.get("text", "").encode())
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return 0


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=5, description="Execution order (lower runs first)")
        enabled: bool = Field(default=True)
        max_bytes: int = Field(
            default=32_000,
            description="Maximum byte size for a single user message (~8k tokens). Default: 32 000.",
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

        last = user_messages[-1]
        size = _content_bytes(last)
        if size > self.valves.max_bytes:
            kb = size // 1024
            raise Exception(
                f"Message too large ({kb} KB). "
                "Please shorten your input or use the file upload feature instead."
            )

        return body
