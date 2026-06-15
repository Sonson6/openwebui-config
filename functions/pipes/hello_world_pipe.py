"""
Hello World Pipe — minimal example that always replies with "Hello World !".
"""
from pydantic import BaseModel


class Pipe:
    class Valves(BaseModel):
        pass

    def __init__(self):
        self.valves = self.Valves()

    def pipes(self) -> list[dict]:
        return [{"id": "hello-world-pipe", "name": "Hello World Pipe"}]

    async def pipe(self, body: dict) -> str:
        return "Hello World !"
