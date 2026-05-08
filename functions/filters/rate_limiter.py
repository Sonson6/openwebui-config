"""
title: Rate Limiter
description: Per-user sliding-window rate limiter. Blocks requests that exceed
             configurable per-minute and per-hour thresholds. Admin role is exempt.
author: openweb-ui-local
version: 0.1.0
"""

import time
from collections import defaultdict
from typing import Optional

from pydantic import BaseModel, Field

# Module-level storage — survives Filter() re-instantiation within the same module execution
_minute_window: dict[str, list[float]] = defaultdict(list)
_hour_window: dict[str, list[float]] = defaultdict(list)


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=0, description="Execution order (lower runs first)")
        enabled: bool = Field(default=True)
        requests_per_minute: int = Field(default=20)
        requests_per_hour: int = Field(default=200)
        exempt_roles: list[str] = Field(
            default=["admin"],
            description="Roles that bypass rate limiting",
        )

    def __init__(self):
        self.valves = self.Valves()

    async def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        if not self.valves.enabled or not __user__:
            return body

        if __user__.get("role", "") in self.valves.exempt_roles:
            return body

        user_id = __user__.get("id", "anonymous")
        now = time.time()

        _minute_window[user_id] = [t for t in _minute_window[user_id] if now - t < 60]
        _hour_window[user_id] = [t for t in _hour_window[user_id] if now - t < 3600]

        if len(_minute_window[user_id]) >= self.valves.requests_per_minute:
            raise Exception(
                f"Rate limit reached: maximum {self.valves.requests_per_minute} messages per minute."
            )

        if len(_hour_window[user_id]) >= self.valves.requests_per_hour:
            raise Exception(
                f"Rate limit reached: maximum {self.valves.requests_per_hour} messages per hour."
            )

        _minute_window[user_id].append(now)
        _hour_window[user_id].append(now)
        return body
