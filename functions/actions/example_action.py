"""
Example Action — adds a button to chat messages.
Actions appear as buttons on message bubbles; the `action` method is called on click.
"""
from pydantic import BaseModel, Field


class Action:
    class Valves(BaseModel):
        priority: int = Field(default=0, description="Execution order (lower runs first)")

    def __init__(self):
        self.valves = self.Valves()

    async def action(
        self,
        body: dict,
        __user__=None,
        __event_emitter__=None,
        __event_call__=None,
    ) -> dict:
        await __event_emitter__(
            {
                "type": "status",
                "data": {"description": "Action executed", "done": True},
            }
        )
        return body
