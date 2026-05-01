"""
title: Strip Structured File Context
description: Inlet filter that removes CSV/Excel content injected into message history
             by OpenWebUI's RAG pipeline. Replaces large tabular content blocks with
             a lightweight placeholder to avoid burning tokens on every follow-up message.
             Run this at priority 1 (after structured_data_gate at priority 0).
author: openweb-ui-local
version: 0.1.0
"""

import logging
import re
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field

log = logging.getLogger(__name__)

# Extensions and MIME types that identify structured data files
STRUCTURED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".parquet", ".tsv"}

# ── OpenWebUI injects file content with these wrapper patterns ─────────────────
# Pattern 1 — XML-style context block (common in recent OWI versions):
#   <context>\nFile: foo.csv\n[content]\n</context>
# Pattern 2 — Markdown header block:
#   ### Context:\n**foo.csv**\n[content]
# Pattern 3 — file_id reference blocks injected into user message content:
#   [FILE: foo.csv]\n[content]
# We also catch any message part that is suspiciously large and comma-dense.

_CONTEXT_BLOCK_RE = re.compile(
    r"<context>.*?</context>",
    re.DOTALL | re.IGNORECASE,
)

_MARKDOWN_CONTEXT_RE = re.compile(
    r"#{1,3}\s*(?:Context|File context|Retrieved context)[:\s]*\n.*?(?=\n#{1,3}|\Z)",
    re.DOTALL | re.IGNORECASE,
)

_FILE_BLOCK_RE = re.compile(
    r"\[FILE:[^\]]*\.(csv|xlsx?|tsv|parquet)\].*?(?=\[FILE:|\Z)",
    re.DOTALL | re.IGNORECASE,
)


def _has_structured_extension(name: str) -> bool:
    return Path(name).suffix.lower() in STRUCTURED_EXTENSIONS


def _looks_like_tabular_data(text: str, min_bytes: int = 2_000) -> bool:
    """
    Heuristic: a block is tabular if it is large and has a high density of
    comma/tab/pipe separators (typical of CSV/TSV content dumps).
    """
    if len(text) < min_bytes:
        return False
    lines = text.splitlines()
    if len(lines) < 5:
        return False
    # Sample the first 20 lines and check separator density
    sample = lines[:20]
    sep_counts = [line.count(",") + line.count("\t") + line.count("|") for line in sample]
    avg_seps = sum(sep_counts) / len(sep_counts)
    return avg_seps >= 2  # at least 2 separators per line on average


def _strip_injected_content(text: str, file_names: set[str], debug: bool) -> tuple[str, int]:
    """
    Remove known injection patterns from a text block.
    Returns (cleaned_text, replacements_made).
    """
    original = text
    count = 0

    # 1. <context>…</context> blocks
    def replace_context(m: re.Match) -> str:
        nonlocal count
        block = m.group(0)
        # Only remove if the block mentions a structured file or looks tabular
        if any(name in block for name in file_names) or _looks_like_tabular_data(block):
            count += 1
            return "[structured file content removed — use the data tool to query it]"
        return block

    text = _CONTEXT_BLOCK_RE.sub(replace_context, text)

    # 2. ### Context / ### File context markdown blocks
    def replace_md_context(m: re.Match) -> str:
        nonlocal count
        block = m.group(0)
        if any(name in block for name in file_names) or _looks_like_tabular_data(block):
            count += 1
            return "[structured file context removed]"
        return block

    text = _MARKDOWN_CONTEXT_RE.sub(replace_md_context, text)

    # 3. [FILE: foo.csv] … blocks
    def replace_file_block(m: re.Match) -> str:
        nonlocal count
        count += 1
        return "[structured file content removed]"

    text = _FILE_BLOCK_RE.sub(replace_file_block, text)

    # 4. Fallback: any large paragraph that looks like raw tabular data
    #    Split on double-newlines and check each paragraph independently.
    paragraphs = text.split("\n\n")
    cleaned_paragraphs = []
    for para in paragraphs:
        if _looks_like_tabular_data(para):
            count += 1
            cleaned_paragraphs.append("[tabular data removed — query it with the data tool]")
        else:
            cleaned_paragraphs.append(para)
    text = "\n\n".join(cleaned_paragraphs)

    if debug and text != original:
        log.debug("[strip-structured-context] stripped %d block(s) from content (original length=%d → %d)",
                  count, len(original), len(text))

    return text, count


class Filter:
    class Valves(BaseModel):
        priority: int = Field(
            default=1,
            description="Run after structured_data_gate (priority 0)",
        )
        enabled: bool = Field(
            default=True,
            description="Enable/disable this filter",
        )
        min_content_bytes: int = Field(
            default=2_000,
            description="Minimum byte size of a text block before the tabular heuristic kicks in",
        )
        scan_all_messages: bool = Field(
            default=True,
            description=(
                "If True, scan the full message history. "
                "If False, only scan the most recent user message."
            ),
        )
        debug: bool = Field(
            default=False,
            description="Log detailed stripping info to container stdout (docker logs)",
        )

    def __init__(self) -> None:
        self.valves = self.Valves()

    async def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        if not self.valves.enabled:
            return body

        messages: list[dict] = body.get("messages", [])
        if not messages:
            return body

        # ── Collect structured file names from this request ───────────────────
        # These help us do targeted removal even when content isn't wrapped.
        file_names: set[str] = set()
        for f in body.get("files", []):
            name = f.get("name", f.get("filename", ""))
            if _has_structured_extension(name):
                file_names.add(name)

        # Also look for file names mentioned in body-level metadata
        for key in ("metadata", "info"):
            meta = body.get(key, {})
            if isinstance(meta, dict):
                for f in meta.get("files", []):
                    name = f.get("name", f.get("filename", ""))
                    if _has_structured_extension(name):
                        file_names.add(name)

        if self.valves.debug:
            log.debug(
                "[strip-structured-context] inlet called | messages=%d | known files=%s",
                len(messages),
                file_names,
            )

        # ── Determine which messages to scan ──────────────────────────────────
        if self.valves.scan_all_messages:
            indices = range(len(messages))
        else:
            # Only the last user message
            indices = [
                i for i, m in enumerate(messages)
                if m.get("role") == "user"
            ][-1:]

        # ── Strip injected content from each selected message ─────────────────
        total_stripped = 0
        for i in indices:
            msg = messages[i]
            content = msg.get("content")

            if isinstance(content, str):
                cleaned, n = _strip_injected_content(content, file_names, self.valves.debug)
                if n:
                    messages[i] = {**msg, "content": cleaned}
                    total_stripped += n

            elif isinstance(content, list):
                # Multipart content (text + images, etc.)
                new_parts = []
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "text":
                        cleaned, n = _strip_injected_content(
                            part.get("text", ""), file_names, self.valves.debug
                        )
                        total_stripped += n
                        new_parts.append({**part, "text": cleaned})
                    else:
                        new_parts.append(part)
                if new_parts != content:
                    messages[i] = {**msg, "content": new_parts}

        if total_stripped and self.valves.debug:
            log.info(
                "[strip-structured-context] removed %d content block(s) across %d message(s)",
                total_stripped,
                len(messages),
            )

        body["messages"] = messages
        return body
