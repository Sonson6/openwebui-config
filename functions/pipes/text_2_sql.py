"""
title: Text-2-SQL Agent
description: Conversational SQL agent for CSV/Excel files using DuckDB.
             Generates SQL, executes it, interprets results, and optionally plots.
             Uses structured-output intent routing for follow-up messages.
author: openweb-ui-local
version: 0.2.1
requirements: duckdb, openpyxl, pandas, tabulate, matplotlib, openai
"""

import base64
import io
import time
from pathlib import Path
from typing import Literal, Optional

import duckdb
import openai
import pandas as pd
from pydantic import BaseModel, Field

# ── Intent schema (Pydantic structured output) ─────────────────────────────────


class IntentClassification(BaseModel):
    intent: Literal["new_query", "explain_results", "fix_plot", "general"]
    reasoning: str


# ── System prompts ─────────────────────────────────────────────────────────────

SUPPORTED_EXTENSIONS = {".csv", ".xlsx", ".xls"}

_INTENT_SYSTEM = """\
You are a routing classifier for a Text-2-SQL data analysis agent.
Classify the user's latest message into one of these intents:

- new_query        : User wants a fresh SQL analysis (first message, or a new analytical question)
- explain_results  : User wants more detail, clarification, or deeper explanation of results already shown
- fix_plot         : User wants to modify, fix, or redo a chart/visualization that was already generated
- general          : Conversational message that requires no SQL execution

Populate `reasoning` with a one-sentence justification for your choice."""

_SQL_SYSTEM = """\
You are an expert DuckDB SQL analyst. Write a single, valid DuckDB SQL query answering the user's question.

Rules:
- The data is exposed as a view named `data` — always reference it as `data`
- Use DuckDB syntax (window functions, PIVOT, LIST, STRUCT, etc. are all available)
- For aggregations, add ORDER BY for meaningful ordering
- Return ONLY the raw SQL — no markdown fences, no explanation"""

_INTERP_SYSTEM = """\
You are a senior data analyst explaining SQL results to a business user.
Given the original question, the SQL executed, and the result table, provide a concise (2–4 sentence)
interpretation highlighting key findings, trends, or anomalies. Be precise with numbers."""

_PLOT_DECISION_SYSTEM = """\
You are a data visualization expert deciding whether a chart adds value to the results.

If a plot is appropriate, write self-contained Python matplotlib code that:
  1. Reads data from the variable `df` (a pandas DataFrame, already available)
  2. Creates a clear, labeled figure with title and axis labels
  3. Saves the figure to `buf` (a BytesIO buffer) via:
       plt.savefig(buf, format='png', bbox_inches='tight', dpi=120)
  4. Does NOT call plt.show()

If the result is a single number, boolean, or a plot would add no insight, return exactly:
  NO_PLOT

Return ONLY raw Python code or the string NO_PLOT — no markdown fences, no explanation."""

_PLOT_FIX_SYSTEM = """\
You are fixing a matplotlib visualization based on user feedback.
Rewrite the complete Python code (using `df` DataFrame, saving to `buf` BytesIO).
Return ONLY raw Python code — no markdown fences, no explanation."""

_EXPLAIN_SYSTEM = """\
You are a data analyst helping the user understand previously shown results.
Use the conversation history to give detailed, accurate explanations.
Do not re-run any SQL — work only from what is already visible in the conversation."""

_GENERAL_SYSTEM = """\
You are a helpful data analysis assistant. Answer the user's question based on the conversation context.
If new SQL analysis is needed, say so and guide the user to ask a specific analytical question."""


# ── Pipe ───────────────────────────────────────────────────────────────────────


class Pipe:
    # Open WebUI calls pipe() 3× per message (known bug #17472).
    # We use a class-level time-keyed dict so only the first call emits status
    # events; duplicates arriving within _DEDUP_TTL seconds are silenced.
    _dedup: dict[str, float] = {}
    _DEDUP_TTL: float = 10.0  # seconds — wide enough to catch all 3 rapid calls

    class Valves(BaseModel):
        LLM_API_BASE_URL: str = Field(
            default="http://localhost:11434/v1",
            description="OpenAI-compatible LLM API base URL (no trailing slash)",
        )
        LLM_API_KEY: str = Field(
            default="none",
            description="API key for the LLM endpoint (use 'none' for local servers)",
        )
        SQL_MODEL: str = Field(
            default="gpt-4o",
            description="Model used to generate SQL queries",
        )
        INTERPRETATION_MODEL: str = Field(
            default="gpt-4o",
            description="Model used to interpret query results",
        )
        INTENT_MODEL: str = Field(
            default="gpt-4o-mini",
            description="Smaller/faster model for intent classification (must support structured outputs)",
        )
        PLOT_MODEL: str = Field(
            default="gpt-4o",
            description="Model used to generate and fix plot code",
        )
        UPLOADS_DIR: str = Field(
            default="/app/backend/data/uploads",
            description="Path to OpenWebUI's uploads directory on disk",
        )
        MAX_ROWS: int = Field(
            default=500,
            description="Maximum result rows returned per query",
        )
        ENABLE_PLOTS: bool = Field(
            default=True,
            description="Enable matplotlib plot generation",
        )
        SQL_RETRY_ON_ERROR: bool = Field(
            default=True,
            description="Retry SQL generation once if execution fails",
        )

    def __init__(self) -> None:
        self.valves = self.Valves()
        # Per-chat file cache: chat_id -> file metadata dict
        self._file_cache: dict[str, dict] = {}

    def pipes(self) -> list[dict]:
        return [{"id": "text-2-sql", "name": "Text-2-SQL Agent"}]

    # ── OpenAI client factory ────────────────────────────────────────────────────

    def _client(self) -> openai.AsyncOpenAI:
        """Return a fresh AsyncOpenAI client configured from current Valves."""
        return openai.AsyncOpenAI(
            base_url=self.valves.LLM_API_BASE_URL,
            api_key=self.valves.LLM_API_KEY or "none",
        )

    # ── File helpers ─────────────────────────────────────────────────────────────

    def _pick_structured_file(self, files: list[dict]) -> Optional[dict]:
        """Return the most recently uploaded structured data file from a list."""
        for f in reversed(files):
            name = f.get("name", f.get("filename", ""))
            if Path(name).suffix.lower() in SUPPORTED_EXTENSIONS:
                return f
        return None

    def _resolve_path(self, file_meta: dict) -> Optional[Path]:
        """Map file metadata to an absolute path on disk."""
        # 1. Explicit path field
        raw = file_meta.get("path") or file_meta.get("meta", {}).get("path", "")
        if raw:
            p = Path(raw)
            if p.exists():
                return p

        # 2. Uploads dir + filename
        uploads = Path(self.valves.UPLOADS_DIR)
        name = file_meta.get("name", file_meta.get("filename", ""))
        if name:
            direct = uploads / name
            if direct.exists():
                return direct
            # Partial / fuzzy match (e.g. UUIDs prepended to filename)
            if uploads.exists():
                candidates = [f for f in uploads.iterdir() if name in f.name]
                if len(candidates) == 1:
                    return candidates[0]

        # 3. Most-recently-modified structured file in uploads dir (last resort)
        if uploads.exists():
            structured = [
                f
                for f in uploads.iterdir()
                if f.suffix.lower() in SUPPORTED_EXTENSIONS
            ]
            if structured:
                return max(structured, key=lambda f: f.stat().st_mtime)

        return None

    def _duckdb_reader(self, path: Path) -> str:
        ext = path.suffix.lower()
        if ext == ".csv":
            return f"read_csv_auto('{path}')"
        if ext in (".xlsx", ".xls"):
            return f"read_xlsx('{path}')"
        raise ValueError(f"Unsupported extension: {ext}")

    def _describe_schema(self, path: Path) -> tuple[str, str]:
        """Return (schema_markdown, reader_expr) for the given file."""
        reader = self._duckdb_reader(path)
        con = duckdb.connect(":memory:")
        try:
            rows = con.execute(f"DESCRIBE SELECT * FROM {reader}").fetchall()
            preview = con.execute(f"SELECT * FROM {reader} LIMIT 3").fetchdf()
            schema_md = "| Column | Type |\n|---|---|\n" + "\n".join(
                f"| `{r[0]}` | {r[1]} |" for r in rows
            )
            preview_md = preview.to_markdown(index=False)
            description = (
                f"**File:** `{path.name}`\n\n"
                f"#### Schema\n{schema_md}\n\n"
                f"#### Sample rows (3)\n{preview_md}"
            )
            return description, reader
        finally:
            con.close()

    def _run_sql(self, sql: str, reader: str) -> tuple[pd.DataFrame, str]:
        """Execute a DuckDB query; return (DataFrame, markdown_table)."""
        con = duckdb.connect(":memory:")
        try:
            con.execute(f"CREATE VIEW data AS SELECT * FROM {reader}")
            df = con.execute(sql).fetchdf()
            truncated = ""
            if len(df) > self.valves.MAX_ROWS:
                df = df.head(self.valves.MAX_ROWS)
                truncated = f"\n\n*(result truncated to {self.valves.MAX_ROWS} rows)*"
            if df.empty:
                return df, "*Query returned no rows.*"
            return df, df.to_markdown(index=False) + truncated
        finally:
            con.close()

    # ── LLM helpers ──────────────────────────────────────────────────────────────

    async def _call_llm(
        self,
        model: str,
        messages: list[dict],
        temperature: float = 0.3,
    ) -> str:
        """Plain chat completion — returns the assistant message content."""
        response = await self._client().chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""

    async def _classify_intent(
        self, messages: list[dict], has_previous_results: bool
    ) -> str:
        """
        Use structured output (Pydantic parse) to classify the user's intent.
        Falls back to 'new_query' on any error.
        """
        last_user = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
        )
        context_note = (
            "Previous SQL results ARE present in the conversation."
            if has_previous_results
            else "No previous SQL results in this conversation yet."
        )
        intent_messages = [
            {"role": "system", "content": _INTENT_SYSTEM},
            {
                "role": "user",
                "content": f"Context: {context_note}\n\nUser message: {last_user}",
            },
        ]
        try:
            response = await self._client().beta.chat.completions.parse(
                model=self.valves.INTENT_MODEL,
                messages=intent_messages,
                response_format=IntentClassification,
                temperature=0.0,
            )
            parsed: IntentClassification = response.choices[0].message.parsed
            return parsed.intent
        except Exception:
            return "new_query"

    # ── SQL generation ────────────────────────────────────────────────────────────

    async def _generate_sql(
        self,
        user_question: str,
        file_description: str,
        history: list[dict],
    ) -> str:
        sys_msg = f"{_SQL_SYSTEM}\n\n{file_description}"
        chat: list[dict] = [{"role": "system", "content": sys_msg}]
        # Include last 3 exchange pairs for context, stripping base64 blobs
        for m in history[-6:]:
            if m["role"] in ("user", "assistant"):
                content = m.get("content", "")
                if isinstance(content, str) and "base64," in content:
                    content = "[plot omitted]"
                chat.append({"role": m["role"], "content": content})
        chat.append({"role": "user", "content": user_question})
        sql = await self._call_llm(self.valves.SQL_MODEL, chat, temperature=0.1)
        return (
            sql.strip()
            .removeprefix("```sql")
            .removeprefix("```")
            .removesuffix("```")
            .strip()
        )

    # ── Interpretation ────────────────────────────────────────────────────────────

    async def _interpret(self, user_question: str, sql: str, table_md: str) -> str:
        content = (
            f"**User question:** {user_question}\n\n"
            f"**SQL executed:**\n```sql\n{sql}\n```\n\n"
            f"**Result:**\n{table_md}"
        )
        messages = [
            {"role": "system", "content": _INTERP_SYSTEM},
            {"role": "user", "content": content},
        ]
        return await self._call_llm(
            self.valves.INTERPRETATION_MODEL, messages, temperature=0.3
        )

    # ── Plot helpers ──────────────────────────────────────────────────────────────

    def _exec_plot_code(self, code: str, df: pd.DataFrame) -> Optional[str]:
        """Execute matplotlib code in-process; return base64 PNG or None."""
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        buf = io.BytesIO()
        namespace: dict = {"df": df.copy(), "plt": plt, "pd": pd, "buf": buf}
        try:
            exec(compile(code, "<plot>", "exec"), namespace)  # noqa: S102
            buf.seek(0)
            data = buf.read()
            if data:
                return base64.b64encode(data).decode()
        except Exception:
            pass
        finally:
            plt.close("all")
        return None

    async def _generate_plot(
        self, user_question: str, sql: str, table_md: str, df: pd.DataFrame
    ) -> Optional[str]:
        if not self.valves.ENABLE_PLOTS:
            return None
        content = f"Question: {user_question}\nSQL: {sql}\nResult:\n{table_md}"
        messages = [
            {"role": "system", "content": _PLOT_DECISION_SYSTEM},
            {"role": "user", "content": content},
        ]
        code = await self._call_llm(self.valves.PLOT_MODEL, messages, temperature=0.2)
        code = code.strip()
        if "NO_PLOT" in code or len(code) < 30:
            return None
        code = (
            code.removeprefix("```python").removeprefix("```").removesuffix("```").strip()
        )
        return self._exec_plot_code(code, df)

    async def _fix_plot(
        self, user_question: str, history: list[dict], df: pd.DataFrame
    ) -> Optional[str]:
        messages: list[dict] = [{"role": "system", "content": _PLOT_FIX_SYSTEM}]
        for m in history[-8:]:
            if m["role"] in ("user", "assistant"):
                content = m.get("content", "")
                if isinstance(content, str) and "base64," in content:
                    content = "[previous plot]"
                messages.append({"role": m["role"], "content": content})
        messages.append({"role": "user", "content": user_question})
        code = await self._call_llm(self.valves.PLOT_MODEL, messages, temperature=0.2)
        code = (
            code.strip()
            .removeprefix("```python")
            .removeprefix("```")
            .removesuffix("```")
            .strip()
        )
        return self._exec_plot_code(code, df)

    def _extract_last_sql(self, messages: list[dict]) -> Optional[str]:
        """Scan assistant messages in reverse to find the last SQL block."""
        for m in reversed(messages):
            if m["role"] != "assistant":
                continue
            content = m.get("content", "")
            if not isinstance(content, str):
                continue
            if "```sql" in content:
                start = content.find("```sql") + 6
                end = content.find("```", start)
                if end > start:
                    return content[start:end].strip()
        return None

    # ── Status emission ───────────────────────────────────────────────────────────

    async def _emit(self, emitter, description: str, done: bool = False) -> None:
        if emitter:
            await emitter(
                {"type": "status", "data": {"description": description, "done": done}}
            )

    # ── File discovery ────────────────────────────────────────────────────────────

    def _find_file_meta(
        self,
        messages: list[dict],
        files: list[dict],
        body: dict,
        chat_id: Optional[str],
    ) -> Optional[dict]:
        """3-tier file lookup: current request → per-chat cache → message history."""
        # Tier 1: files attached to the current request
        meta = self._pick_structured_file(list(files) + body.get("files", []))
        if meta:
            return meta

        # Tier 2: file seen in a prior turn of this chat
        if chat_id and chat_id in self._file_cache:
            return self._file_cache[chat_id]

        # Tier 3: embedded file references inside message history
        for m in reversed(messages):
            content = m.get("content")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") == "file":
                        candidate = part.get("file", part)
                        if self._pick_structured_file([candidate]):
                            return candidate
        return None

    # ── SQL generation + execution (with retry) ───────────────────────────────────

    async def _execute_sql(
        self,
        user_question: str,
        file_description: str,
        reader: str,
        history: list[dict],
        emit,
    ) -> tuple[str, pd.DataFrame, str]:
        """
        Generate SQL, run it, retry once on error.
        Returns (sql, df, table_md). Raises RuntimeError on unrecoverable failure.
        """
        await emit("Generating SQL query...")
        sql = await self._generate_sql(user_question, file_description, history)

        await emit("Executing query...")
        sql_error: Optional[str] = None
        try:
            df, table_md = self._run_sql(sql, reader)
            return sql, df, table_md
        except Exception as exc:
            sql_error = str(exc)

        if self.valves.SQL_RETRY_ON_ERROR:
            await emit("Fixing SQL error...")
            retry_prompt = (
                f"The following DuckDB SQL query failed:\n\n```sql\n{sql}\n```\n\n"
                f"Error: {sql_error}\n\n"
                "Fix the query and return only the corrected SQL, no explanation."
            )
            sql = await self._generate_sql(retry_prompt, file_description, history)
            df, table_md = self._run_sql(sql, reader)  # let this propagate if it also fails
            return sql, df, table_md

        raise RuntimeError(sql_error)

    # ── Intent handlers ───────────────────────────────────────────────────────────

    async def _handle_explain_results(self, messages: list[dict], emit) -> str:
        """Return a detailed explanation of previously shown results."""
        await emit("Generating explanation...")
        chat: list[dict] = [{"role": "system", "content": _EXPLAIN_SYSTEM}]
        for m in messages[-10:]:
            if m["role"] in ("user", "assistant"):
                content = m.get("content", "")
                if isinstance(content, str) and "base64," in content:
                    content = "[plot omitted]"
                chat.append({"role": m["role"], "content": content})
        return await self._call_llm(self.valves.INTERPRETATION_MODEL, chat, temperature=0.4)

    async def _handle_fix_plot(
        self, user_question: str, messages: list[dict], reader: str, emit
    ) -> str:
        """Re-run the last SQL query and regenerate the plot with the user's feedback."""
        await emit("Regenerating plot...")
        last_sql = self._extract_last_sql(messages)
        if not last_sql:
            return "No previous SQL found to regenerate the plot from. Please ask a new analytical question."
        df, _ = self._run_sql(last_sql, reader)
        b64 = await self._fix_plot(user_question, messages, df)
        if b64:
            return f"### Updated Visualization\n\n![Updated plot](data:image/png;base64,{b64})"
        return "Could not generate the updated plot. Please describe exactly what to change."

    async def _handle_general(self, messages: list[dict], emit) -> str:
        """Answer a general conversational message using the chat history."""
        await emit("Generating response...")
        chat: list[dict] = [{"role": "system", "content": _GENERAL_SYSTEM}]
        for m in messages[-8:]:
            if m["role"] in ("user", "assistant"):
                content = m.get("content", "")
                if isinstance(content, str) and "base64," in content:
                    content = "[plot omitted]"
                chat.append({"role": m["role"], "content": content})
        return await self._call_llm(self.valves.INTERPRETATION_MODEL, chat, temperature=0.5)

    async def _handle_new_query(
        self,
        user_question: str,
        file_description: str,
        reader: str,
        messages: list[dict],
        emit,
    ) -> str:
        """Full pipeline: SQL → execute → interpret → optional plot → assemble response."""
        sql, df, table_md = await self._execute_sql(
            user_question, file_description, reader, messages[:-1], emit
        )

        await emit("Interpreting results...")
        try:
            interpretation = await self._interpret(user_question, sql, table_md)
        except Exception as exc:
            interpretation = f"*(Interpretation unavailable: {exc})*"

        plot_md = ""
        if self.valves.ENABLE_PLOTS and not df.empty:
            await emit("Checking if a visualization would help...")
            try:
                b64 = await self._generate_plot(user_question, sql, table_md, df)
                if b64:
                    plot_md = (
                        f"### Visualization\n\n"
                        f"![Data visualization](data:image/png;base64,{b64})"
                    )
            except Exception:
                pass

        parts = [
            f"### Results\n\n{table_md}",
            f"**Analysis:** {interpretation}",
            f"<details><summary>SQL</summary>\n\n```sql\n{sql}\n```\n</details>",
        ]
        if plot_md:
            parts.append(plot_md)

        return "\n\n".join(parts)

    # ── Main pipe ─────────────────────────────────────────────────────────────────

    async def pipe(
        self,
        body: dict,
        __user__: Optional[dict] = None,
        __files__: list[dict] = [],
        __chat_id__: Optional[str] = None,
        __event_emitter__=None,
    ) -> str:
        messages: list[dict] = body.get("messages", [])
        user_messages = [m for m in messages if m["role"] == "user"]
        is_first_message = len(user_messages) <= 1
        user_question = user_messages[-1].get("content", "") if user_messages else ""

        # ── Duplicate-call guard ──────────────────────────────────────────────
        # Open WebUI triggers pipe() 3× per message (bug #17472).  All three
        # calls share the same message_id, so their status events pile up in the
        # same bubble.  We let only the first call within _DEDUP_TTL seconds
        # emit status events; the rest process silently and return the result.
        dedup_key = f"{__chat_id__}|{user_question[:120]}"
        now = time.monotonic()
        is_duplicate = (now - Pipe._dedup.get(dedup_key, 0.0)) < self._DEDUP_TTL
        if not is_duplicate:
            Pipe._dedup[dedup_key] = now

        if is_duplicate:
            async def _noop(_event): pass  # swallow all status events
            emit = _noop
        else:
            emit = lambda msg, done=False: self._emit(__event_emitter__, msg, done)

        # 1. Locate the data file ─────────────────────────────────────────────
        await emit("Locating data file...")
        file_meta = self._find_file_meta(messages, __files__, body, __chat_id__)
        if file_meta is None:
            await emit("No file — stopped", done=True)
            return (
                "**No structured data file found.**\n\n"
                "Please upload a CSV or Excel file alongside your message so I can analyse it."
            )

        if __chat_id__:
            self._file_cache[__chat_id__] = file_meta

        file_path = self._resolve_path(file_meta)
        if file_path is None:
            name = file_meta.get("name", file_meta.get("filename", "unknown"))
            await emit("File not on disk — stopped", done=True)
            return f"**Could not locate `{name}` on disk.**\n\nThe file may have expired. Please re-upload it."

        # 2. Read schema ───────────────────────────────────────────────────────
        await emit(f"Reading `{file_path.name}`...")
        try:
            file_description, reader = self._describe_schema(file_path)
        except Exception as exc:
            await emit("Read error", done=True)
            return f"**Error reading file:** {exc}"

        # 3. Classify intent ───────────────────────────────────────────────────
        if is_first_message:
            intent = "new_query"
        else:
            await emit("Classifying intent...")
            has_results = any(m["role"] == "assistant" for m in messages)
            intent = await self._classify_intent(messages, has_results)

        # 4. Dispatch to handler ───────────────────────────────────────────────
        handlers = {
            "explain_results": lambda: self._handle_explain_results(messages, emit),
            "fix_plot": lambda: self._handle_fix_plot(user_question, messages, reader, emit),
            "general": lambda: self._handle_general(messages, emit),
            "new_query": lambda: self._handle_new_query(user_question, file_description, reader, messages, emit),
        }
        try:
            response = await handlers.get(intent, handlers["new_query"])()
        except Exception as exc:
            response = f"**Error:** {exc}"

        await emit("Done", done=True)
        return response
