from typing import Any

import httpx
from openai import OpenAI
from openai.types.chat import ChatCompletion


class OWUIClient:
    """Thin wrapper around the OpenAI client + raw OWUI REST calls."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 60.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._openai = OpenAI(
            base_url=f"{self.base_url}/api",
            api_key=api_key,
            timeout=timeout,
        )
        self._http = httpx.Client(
            base_url=self.base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # OpenAI-compatible helpers
    # ------------------------------------------------------------------

    def list_models(self):
        return self._openai.models.list()

    def chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 512,
        **kwargs: Any,
    ) -> ChatCompletion:
        return self._openai.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # OWUI native REST helpers
    # ------------------------------------------------------------------

    def get_chat(self, chat_id: str) -> dict[str, Any]:
        resp = self._http.get(f"/api/v1/chats/{chat_id}")
        resp.raise_for_status()
        return resp.json()  # type: ignore[no-any-return]

    def close(self) -> None:
        self._http.close()
