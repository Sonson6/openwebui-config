"""
title: Data Analyzer
description: Execute DuckDB SQL queries on uploaded CSV, Excel, or Parquet files.
author: openweb-ui-local
version: 0.1.0
requirements: duckdb, openpyxl, tabulate, pandas
"""
from pathlib import Path
from typing import Optional

import duckdb
from pydantic import BaseModel, Field


class Tools:
    class Valves(BaseModel):
        UPLOADS_DIR: str = Field(
            default="/app/backend/data/uploads",
            description="Path to OpenWebUI's uploads directory on disk.",
        )
        MAX_ROWS: int = Field(
            default=100,
            description="Maximum rows returned in a single query result.",
        )

    def __init__(self) -> None:
        self.valves = self.Valves()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _resolve_file(self, file_ref: str) -> Path:
        p = Path(file_ref)
        if p.is_absolute() and p.exists():
            return p
        uploads = Path(self.valves.UPLOADS_DIR)
        if uploads.exists():
            matches = [f for f in uploads.iterdir() if file_ref in f.name]
            if len(matches) == 1:
                return matches[0]
            if len(matches) > 1:
                raise FileNotFoundError(
                    f"Ambiguous reference '{file_ref}' — matched: {[m.name for m in matches]}"
                )
        raise FileNotFoundError(f"File not found for reference: {file_ref}")

    def _reader(self, path: Path) -> str:
        ext = path.suffix.lower()
        if ext == ".csv":
            return f"read_csv_auto('{path}')"
        if ext in (".xlsx", ".xls"):
            return f"read_xlsx('{path}')"
        if ext == ".parquet":
            return f"read_parquet('{path}')"
        raise ValueError(f"Unsupported file format: {ext}")

    # ── LLM-callable methods ──────────────────────────────────────────────────

    def describe_file(self, file_ref: str) -> str:
        """
        Describe the schema and a 5-row preview of a structured data file.

        :param file_ref: identifier (filename, partial name, or full path) of the uploaded file
        :return: markdown-formatted schema and preview
        """
        try:
            path = self._resolve_file(file_ref)
            reader = self._reader(path)
        except (FileNotFoundError, ValueError) as e:
            return f"**Error:** {e}"

        con = duckdb.connect(":memory:")
        try:
            schema = con.execute(f"DESCRIBE SELECT * FROM {reader}").fetchall()
            preview = con.execute(f"SELECT * FROM {reader} LIMIT 5").fetchdf()
            schema_md = "| Column | Type |\n|---|---|\n" + "\n".join(
                f"| `{row[0]}` | {row[1]} |" for row in schema
            )
            return (
                f"### File: `{path.name}`\n\n"
                f"#### Schema\n{schema_md}\n\n"
                f"#### Preview (5 rows)\n{preview.to_markdown(index=False)}"
            )
        except Exception as e:
            return f"**Error:** {e}"
        finally:
            con.close()

    def query(self, sql: str, file_ref: str) -> str:
        """
        Execute a DuckDB SQL query against an uploaded file.
        The file's contents are exposed as a view named `data`.

        Example queries:
          SELECT COUNT(*) FROM data
          SELECT region, SUM(amount) AS total FROM data GROUP BY region ORDER BY total DESC

        :param sql: DuckDB SQL query referencing the table `data`
        :param file_ref: identifier of the uploaded file
        :return: query result as a markdown table (truncated if too large)
        """
        try:
            path = self._resolve_file(file_ref)
            reader = self._reader(path)
        except (FileNotFoundError, ValueError) as e:
            return f"**Error:** {e}"

        con = duckdb.connect(":memory:")
        try:
            con.execute(f"CREATE VIEW data AS SELECT * FROM {reader}")
            df = con.execute(sql).fetchdf()
            truncated = ""
            if len(df) > self.valves.MAX_ROWS:
                df = df.head(self.valves.MAX_ROWS)
                truncated = f"\n\n*(result truncated to {self.valves.MAX_ROWS} rows)*"
            if df.empty:
                return "*Query returned no rows.*"
            return df.to_markdown(index=False) + truncated
        except Exception as e:
            return f"**Error executing query:** {e}\n\n```sql\n{sql}\n```"
        finally:
            con.close()
