"""
title: Data Analyzer
description: Profile, query, and interpret uploaded CSV, Excel, or Parquet files via DuckDB. Pairs with the MCP Chart tool for visualization.
author: openweb-ui-local
version: 0.2.0
requirements: duckdb, openpyxl, tabulate, pandas
"""
from pathlib import Path

import duckdb
from pydantic import BaseModel, Field

_NUMERIC_OR_TEMPORAL = {
    "DATE", "TIME", "TIMESTAMP", "TINYINT", "SMALLINT", "INTEGER",
    "BIGINT", "HUGEINT", "FLOAT", "DOUBLE", "DECIMAL",
}


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
        LOW_CARDINALITY_THRESHOLD: int = Field(
            default=20,
            description="Columns with at most this many distinct values are profiled as categorical.",
        )
        PROFILE_SAMPLE_VALUES: int = Field(
            default=5,
            description="Number of most frequent values to show for categorical columns.",
        )

    def __init__(self) -> None:
        self.valves = self.Valves()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _resolve_file(self, file_ref: str) -> Path:
        if not file_ref:
            raise FileNotFoundError("No file reference given.")
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
        quoted = str(path).replace("'", "''")
        ext = path.suffix.lower()
        if ext == ".csv":
            return f"read_csv_auto('{quoted}')"
        if ext in (".xlsx", ".xls"):
            return f"read_xlsx('{quoted}')"
        if ext == ".parquet":
            return f"read_parquet('{quoted}')"
        raise ValueError(f"Unsupported file format: {ext}")

    def _load(self, con: duckdb.DuckDBPyConnection, path: Path) -> None:
        """Materialize the file into an in-memory table, then lock down
        filesystem access so subsequent (LLM-authored) SQL can't read
        other files on disk."""
        con.execute(f"CREATE TABLE data AS SELECT * FROM {self._reader(path)}")
        con.execute("SET enable_external_access = false")

    # ── LLM-callable methods ──────────────────────────────────────────────────

    def describe_file(self, file_ref: str) -> str:
        """
        Profile an uploaded data file: column names, types, null rates,
        distinct value counts, and representative values or ranges. Use this
        first to understand what a file contains and what each column likely
        represents before writing queries.

        :param file_ref: identifier (filename, partial name, or full path) of the uploaded file
        :return: markdown-formatted column profile and 5-row preview
        """
        try:
            path = self._resolve_file(file_ref)
        except (FileNotFoundError, ValueError) as e:
            return f"**Error:** {e}"

        con = duckdb.connect(":memory:")
        try:
            self._load(con, path)
            schema = con.execute("DESCRIBE data").fetchall()
            row_count = con.execute("SELECT COUNT(*) FROM data").fetchone()[0]

            profile_rows = []
            for col, dtype, *_ in schema:
                ident = '"' + col.replace('"', '""') + '"'
                non_null, distinct_n = con.execute(
                    f"SELECT COUNT({ident}), APPROX_COUNT_DISTINCT({ident}) FROM data"
                ).fetchone()
                null_pct = round(100 * (1 - non_null / row_count), 1) if row_count else 0.0

                values = ""
                if distinct_n <= self.valves.LOW_CARDINALITY_THRESHOLD:
                    top = con.execute(
                        f"SELECT {ident}, COUNT(*) AS n FROM data "
                        f"GROUP BY {ident} ORDER BY n DESC LIMIT {self.valves.PROFILE_SAMPLE_VALUES}"
                    ).fetchall()
                    values = ", ".join(f"{v!r} ({n})" for v, n in top)
                elif dtype.split("(")[0] in _NUMERIC_OR_TEMPORAL:
                    lo, hi = con.execute(f"SELECT MIN({ident}), MAX({ident}) FROM data").fetchone()
                    values = f"range: {lo} … {hi}"

                profile_rows.append((col, dtype, distinct_n, f"{null_pct}%", values))

            profile_md = (
                "| Column | Type | Distinct | Null % | Sample values / range |\n"
                "|---|---|---|---|---|\n"
                + "\n".join(f"| `{c}` | {t} | {d} | {n} | {v} |" for c, t, d, n, v in profile_rows)
            )

            preview = con.execute("SELECT * FROM data LIMIT 5").fetchdf()
            return (
                f"### File: `{path.name}` ({row_count} rows)\n\n"
                f"#### Column profile\n{profile_md}\n\n"
                f"#### Preview (5 rows)\n{preview.to_markdown(index=False)}"
            )
        except Exception as e:
            return f"**Error:** {e}"
        finally:
            con.close()

    def query(self, sql: str, file_ref: str, output_format: str = "markdown") -> str:
        """
        Execute a DuckDB SQL query against an uploaded file. The file's
        contents are exposed as a table named `data`.

        Use output_format="json" when the result will be passed to a chart
        generation tool (e.g. MCP Chart) — it returns a JSON array of row
        objects that maps directly onto a chart tool's `data` parameter.

        Example queries:
          SELECT COUNT(*) FROM data
          SELECT region, SUM(amount) AS total FROM data GROUP BY region ORDER BY total DESC

        :param sql: DuckDB SQL query referencing the table `data`
        :param file_ref: identifier of the uploaded file
        :param output_format: "markdown" (human-readable table) or "json" (for chart tools)
        :return: query result as markdown or JSON, truncated if too large
        """
        if output_format not in ("markdown", "json"):
            return f"**Error:** invalid output_format '{output_format}', expected 'markdown' or 'json'"

        try:
            path = self._resolve_file(file_ref)
        except (FileNotFoundError, ValueError) as e:
            return f"**Error:** {e}"

        con = duckdb.connect(":memory:")
        try:
            self._load(con, path)
            df = con.execute(sql).fetchdf()

            if df.empty:
                return "*Query returned no rows.*"

            truncated = len(df) > self.valves.MAX_ROWS
            if truncated:
                df = df.head(self.valves.MAX_ROWS)
            note = f"\n\n*(result truncated to {self.valves.MAX_ROWS} rows)*" if truncated else ""

            if output_format == "json":
                return df.to_json(orient="records") + note
            return df.to_markdown(index=False) + note
        except Exception as e:
            return f"**Error executing query:** {e}\n\n```sql\n{sql}\n```"
        finally:
            con.close()
