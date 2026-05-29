"""
title: Claude PPTX Skill
description: Generate and edit PowerPoint presentations using Claude's native pptx skill via the Anthropic API. Supports multi-turn editing by reusing the same container across a conversation.
author: openweb-ui-local
version: 1.0.0
requirements: anthropic>=0.52.0
"""

import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import anthropic
from pydantic import BaseModel, Field

_BETAS = ["code-execution-2025-08-25", "skills-2025-10-02", "files-api-2025-04-14"]
_PPTX_SKILL = {"type": "anthropic", "skill_id": "pptx", "version": "latest"}
_CODE_EXEC_TOOL = {"type": "code_execution_20250825", "name": "code_execution"}
_CONTAINER_FILE = "container_id.txt"
_NO_QA_SUFFIX = "\n\nSkip thumbnail generation and visual QA. Generate the file and return it directly."
_NO_QA_SYSTEM = (
    "You are generating a PowerPoint file under a strict token budget. "
    "Do NOT render slides to images, do NOT generate thumbnails, and do NOT "
    "perform visual quality-assurance loops. Write the pptxgenjs script once, "
    "execute it once to produce the .pptx file, and stop. Do not re-render or "
    "self-review the output visually."
)


class Tools:
    class Valves(BaseModel):
        ANTHROPIC_API_KEY: str = Field(default="", description="Anthropic API key")
        BASE_OUTPUT_DIR: str = Field(
            default="/home/user/pptx",
            description="Base directory; each conversation gets its own subdirectory here",
        )
        MODEL: str = Field(
            default="claude-sonnet-4-6",
            description="Claude model ID (claude-sonnet-4-6 or claude-opus-4-7)",
        )
        MAX_TOKENS: int = Field(default=16000, description="Max output tokens per call")
        SKIP_VISUAL_QA: bool = Field(
            default=True,
            description="Append an instruction to skip thumbnail generation and visual QA. Saves ~80-90% of tokens. Disable only when quality verification is needed.",
        )
        TOKEN_BUDGET: int = Field(
            default=300000,
            description="HARD CAP. The loop aborts once cumulative input+output tokens exceed this. Prevents runaway cost. ~300k ≈ <$1 on Sonnet.",
        )
        MAX_API_ROUNDS: int = Field(
            default=3,
            description="Max number of API round-trips (pause_turn continuations). Each round re-sends accumulated context, so keep this low.",
        )

    def __init__(self) -> None:
        self.valves = self.Valves()

    # ── helpers ───────────────────────────────────────────────────────────────

    def _session_dir(self, metadata: Optional[dict]) -> Path:
        chat_id = (metadata or {}).get("chat_id") or datetime.datetime.now().strftime(
            "%Y%m%d_%H%M%S"
        )
        d = Path(self.valves.BASE_OUTPUT_DIR) / chat_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _load_container_id(self, session_dir: Path) -> Optional[str]:
        p = session_dir / _CONTAINER_FILE
        return p.read_text().strip() if p.exists() else None

    def _save_container_id(self, session_dir: Path, container_id: str) -> None:
        (session_dir / _CONTAINER_FILE).write_text(container_id)

    def _extract_file_ids(self, response) -> list[str]:
        """Walk the response for file_ids. Tolerant of block-type naming
        ('bash_code_execution_tool_result', 'code_execution_tool_result',
        'tool_result') so a naming change never silently drops the file and
        forces an expensive re-run."""
        file_ids: list[str] = []

        def collect(node) -> None:
            if node is None:
                return
            if isinstance(node, list):
                for n in node:
                    collect(n)
                return
            fid = getattr(node, "file_id", None)
            if fid:
                file_ids.append(fid)
            inner = getattr(node, "content", None)
            if inner is not None and not isinstance(inner, str):
                collect(inner)

        collect(response.content)
        # Dedupe, preserve order
        seen: set[str] = set()
        return [f for f in file_ids if not (f in seen or seen.add(f))]

    async def _emit(
        self,
        emitter: Optional[Callable[[Any], Any]],
        description: str,
        done: bool = False,
    ) -> None:
        if emitter:
            await emitter(
                {"type": "status", "data": {"description": description, "done": done}}
            )

    # ── public tool ──────────────────────────────────────────────────────────

    async def create_or_edit_presentation(
        self,
        prompt: str,
        __event_emitter__: Optional[Callable[[Any], Any]] = None,
        __metadata__: Optional[dict] = None,
    ) -> str:
        """
        Create or edit a PowerPoint presentation using Claude's native pptx skill.

        On first call in a conversation, a new Anthropic container is created and its
        ID is saved to the session directory. Subsequent calls in the same conversation
        reuse that container, so Claude can edit the presentation it already built.

        :param prompt: What to create or change (e.g. "Create a 5-slide deck on climate change" or "Add a slide with Q3 revenue data")
        :return: Path to the generated .pptx file and session directory
        """
        if not self.valves.ANTHROPIC_API_KEY:
            return "Error: ANTHROPIC_API_KEY is not configured in the tool valves."

        session_dir = self._session_dir(__metadata__)
        container_id = self._load_container_id(session_dir)

        container_config: dict = {"skills": [_PPTX_SKILL]}
        if container_id:
            container_config["id"] = container_id

        client = anthropic.Anthropic(api_key=self.valves.ANTHROPIC_API_KEY)
        effective_prompt = prompt + (_NO_QA_SUFFIX if self.valves.SKIP_VISUAL_QA else "")
        messages: list[dict] = [{"role": "user", "content": effective_prompt}]

        await self._emit(__event_emitter__, "Calling Claude pptx skill…")

        # pause_turn loop — bounded by MAX_API_ROUNDS and a hard TOKEN_BUDGET.
        response = None
        total_tokens = 0
        for round_i in range(max(1, self.valves.MAX_API_ROUNDS)):
            create_kwargs: dict = dict(
                model=self.valves.MODEL,
                max_tokens=self.valves.MAX_TOKENS,
                betas=_BETAS,
                container=container_config,
                messages=messages,
                tools=[_CODE_EXEC_TOOL],
            )
            if self.valves.SKIP_VISUAL_QA:
                create_kwargs["system"] = _NO_QA_SYSTEM
            response = client.beta.messages.create(**create_kwargs)

            usage = getattr(response, "usage", None)
            if usage:
                total_tokens += (getattr(usage, "input_tokens", 0) or 0) + (
                    getattr(usage, "output_tokens", 0) or 0
                )

            # Persist container ID after first response
            if hasattr(response, "container") and response.container and response.container.id:
                self._save_container_id(session_dir, response.container.id)
                container_config["id"] = response.container.id

            if response.stop_reason != "pause_turn":
                break

            # HARD KILL-SWITCH: stop before paying for another expensive round.
            if total_tokens >= self.valves.TOKEN_BUDGET:
                await self._emit(__event_emitter__, "Token budget exceeded — aborting.", done=True)
                return (
                    f"Aborted: token budget of {self.valves.TOKEN_BUDGET:,} exceeded "
                    f"({total_tokens:,} tokens used) before the presentation finished.\n"
                    f"No file was saved. Simplify the request, keep SKIP_VISUAL_QA on, "
                    f"or raise the TOKEN_BUDGET valve if you accept the cost.\n"
                    f"Session dir: {session_dir}"
                )

            await self._emit(
                __event_emitter__,
                f"Generating… (round {round_i + 2}, {total_tokens:,} tokens so far)",
            )
            messages.append({"role": "assistant", "content": response.content})

        if response is None:
            return "Error: no response received from the API."

        # Loop ended while still paused = ran out of rounds before finishing.
        if response.stop_reason == "pause_turn":
            await self._emit(__event_emitter__, "Round limit reached — aborting.", done=True)
            return (
                f"Aborted: hit the {self.valves.MAX_API_ROUNDS}-round limit "
                f"({total_tokens:,} tokens used) before the presentation finished.\n"
                f"No file was saved. Raise MAX_API_ROUNDS / TOKEN_BUDGET or simplify the request.\n"
                f"Session dir: {session_dir}"
            )

        # Download generated files
        file_ids = self._extract_file_ids(response)
        if not file_ids:
            return (
                f"Claude finished but produced no file.\n"
                f"Session dir: {session_dir}\n\n"
                f"Response text:\n{next((b.text for b in response.content if hasattr(b, 'text')), '(none)')}"
            )

        saved: list[str] = []
        for file_id in file_ids:
            await self._emit(__event_emitter__, f"Downloading {file_id}…")
            meta = client.beta.files.retrieve_metadata(file_id=file_id)
            content = client.beta.files.download(file_id=file_id)
            filename = getattr(meta, "filename", f"{file_id}.pptx")
            dest = session_dir / filename
            with open(dest, "wb") as f:
                f.write(content.read())
            saved.append(str(dest))

        await self._emit(
            __event_emitter__, f"Done! ({total_tokens:,} tokens used)", done=True
        )

        files_str = "\n".join(f"  {p}" for p in saved)
        return (
            f"Presentation saved to:\n{files_str}\n\n"
            f"Tokens used: {total_tokens:,}\n"
            f"Session directory: {session_dir}\n"
            f"(Container ID persisted — you can ask me to edit this presentation in the same conversation)"
        )
