"""
Example Filter — intercepts messages before (inlet) and after (outlet) the model.
`stream` processes individual streamed chunks in real-time.
"""
from pydantic import BaseModel, Field
from typing import Optional


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=0, description="Execution order (lower runs first)")

    def __init__(self):
        self.valves = self.Valves()

    async def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        """Pre-process user input before it reaches the model."""
        print(f"[filter:inlet] messages={len(body.get('messages', []))}")
        return body

    async def stream(self, event: dict) -> dict:
        """Modify individual streamed chunks from the model."""
        return event

    async def outlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        """Post-process model output before it reaches the user."""
        print(f"[filter:outlet] messages={len(body.get('messages', []))}")
        return body
