"""
Example Pipe — routes requests to a custom upstream model endpoint.
Pipes appear as selectable models in the UI; `pipes()` declares the model list.
"""
from pydantic import BaseModel, Field


class Pipe:
    class Valves(BaseModel):
        MODEL_ID: str = Field(default="", description="Upstream model identifier")
        API_BASE_URL: str = Field(default="", description="Upstream API base URL")
        API_KEY: str = Field(default="", description="Upstream API key")

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self) -> list[dict]:
        return [{"id": "example-pipe", "name": "Example Pipe"}]

    async def pipe(self, body: dict) -> str:
        # Minimal echo — replace with real upstream call via httpx or requests
        last = body.get("messages", [{}])[-1]
        return f"[pipe] received: {last.get('content', '')}"
