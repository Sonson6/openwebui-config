"""
title: Custom Patterns
description: Admin-configurable regex filter. Patterns are defined as a JSON array
             in Valves — no redeployment needed. Each pattern can independently
             block the request or redact matched content in-place.
             Example patterns_json:
             [
               {"name": "employee ID", "pattern": "EMP-\\d{6}", "action": "redact", "replacement": "[REDACTED:EMPLOYEE_ID]"},
               {"name": "internal project code", "pattern": "PROJ-[A-Z]{3}-\\d{4}", "action": "block"}
             ]
author: openweb-ui-local
version: 0.1.0
"""

import json
import re
from typing import Optional

from pydantic import BaseModel, Field

_ACTION_BLOCK = "block"
_ACTION_REDACT = "redact"


class _CompiledPattern:
    __slots__ = ("name", "pattern", "action", "replacement")

    def __init__(self, name: str, pattern: re.Pattern, action: str, replacement: str):
        self.name = name
        self.pattern = pattern
        self.action = action
        self.replacement = replacement


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=40, description="Execution order (lower runs first)")
        enabled: bool = Field(default=True)
        patterns_json: str = Field(
            default="[]",
            description=(
                "JSON array of pattern objects. Each object must have:\n"
                '  "name": display label\n'
                '  "pattern": regex string (Python re syntax, case-insensitive by default)\n'
                '  "action": "block" or "redact"\n'
                '  "replacement": replacement string for redact action (optional, '
                'defaults to "[REDACTED:<NAME>]")'
            ),
        )

    def __init__(self):
        self.valves = self.Valves()
        self._compiled: list[_CompiledPattern] = []
        self._cache_key: str = ""

    def _ensure_compiled(self) -> None:
        if self.valves.patterns_json == self._cache_key:
            return
        self._cache_key = self.valves.patterns_json
        self._compiled = []
        try:
            entries = json.loads(self.valves.patterns_json)
            for entry in entries:
                name = entry.get("name", "custom")
                action = entry.get("action", _ACTION_REDACT)
                replacement = entry.get(
                    "replacement", f"[REDACTED:{name.upper().replace(' ', '_')}]"
                )
                pattern = re.compile(entry["pattern"], re.IGNORECASE)
                self._compiled.append(_CompiledPattern(name, pattern, action, replacement))
        except (json.JSONDecodeError, re.error, KeyError):
            # Invalid config — fail open to avoid blocking all messages
            pass

    def _process_text(self, text: str) -> tuple[str, list[str]]:
        blocked_by: list[str] = []
        for cp in self._compiled:
            if cp.action == _ACTION_BLOCK:
                if cp.pattern.search(text):
                    blocked_by.append(cp.name)
            else:
                text = cp.pattern.sub(cp.replacement, text)
        return text, blocked_by

    def _process_message(self, msg: dict) -> tuple[dict, list[str]]:
        content = msg.get("content", "")
        all_blocked: list[str] = []

        if isinstance(content, str):
            cleaned, blocked = self._process_text(content)
            if blocked:
                all_blocked.extend(blocked)
            return {**msg, "content": cleaned}, all_blocked

        if isinstance(content, list):
            new_parts = []
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text":
                    cleaned, blocked = self._process_text(part.get("text", ""))
                    all_blocked.extend(blocked)
                    new_parts.append({**part, "text": cleaned})
                else:
                    new_parts.append(part)
            return {**msg, "content": new_parts}, all_blocked

        return msg, []

    async def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        if not self.valves.enabled:
            return body

        self._ensure_compiled()
        if not self._compiled:
            return body

        messages: list[dict] = body.get("messages", [])
        user_indices = [i for i, m in enumerate(messages) if m.get("role") == "user"]
        if not user_indices:
            return body

        # Only process the last user message
        i = user_indices[-1]
        new_msg, blocked = self._process_message(messages[i])
        if blocked:
            raise Exception(
                f"Your message was blocked by a content policy rule: {', '.join(blocked)}."
            )
        messages[i] = new_msg
        body["messages"] = messages
        return body
