"""
Filter: Structured Data Gate
Intercepts uploaded files before context injection.
For structured data files (CSV, Excel, Parquet), removes them from the inline
RAG injection pipeline and replaces with a lightweight reference message so the
LLM can call the data_analyzer tool instead of receiving a huge text dump.
Other file types (PDF, Word, etc.) pass through untouched.
"""
from typing import Optional
from pydantic import BaseModel, Field

STRUCTURED_EXTENSIONS = {".csv", ".xlsx", ".xls", ".parquet", ".tsv"}
STRUCTURED_MIMETYPES = {
    "text/csv",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/octet-stream",  # parquet has no standard MIME
}


def _is_structured(file: dict) -> bool:
    name = file.get("name", file.get("filename", ""))
    mime = file.get("type", file.get("content_type", ""))
    ext = "." + name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return ext in STRUCTURED_EXTENSIONS or mime in STRUCTURED_MIMETYPES


class Filter:
    class Valves(BaseModel):
        priority: int = Field(default=0, description="Execution order (lower runs first)")
        enabled: bool = Field(default=True, description="Enable/disable the gate")

    def __init__(self):
        self.valves = self.Valves()

    async def inlet(self, body: dict, __user__: Optional[dict] = None) -> dict:
        if not self.valves.enabled:
            return body

        files: list[dict] = body.get("files", [])
        if not files:
            return body

        passthrough = []
        intercepted = []

        for f in files:
            if _is_structured(f):
                intercepted.append(f)
            else:
                passthrough.append(f)

        if not intercepted:
            return body

        # Replace structured files with lightweight references in the system prompt
        names = [f.get("name", f.get("filename", "fichier inconnu")) for f in intercepted]
        refs = "\n".join(f"- `{n}`" for n in names)
        notice = (
            "📊 **Fichiers de données détectés — injection directe désactivée pour éviter la consommation excessive de tokens.**\n\n"
            f"Fichiers disponibles pour analyse via l'outil `data_analyzer` :\n{refs}\n\n"
            "Commence par appeler `describe_file` avec le nom du fichier pour en découvrir la structure, "
            "puis utilise `query` pour répondre à la question de l'utilisateur."
        )

        # Inject the notice as a system message (prepend to messages list)
        messages: list[dict] = body.get("messages", [])
        if messages and messages[0].get("role") == "system":
            messages[0]["content"] = messages[0]["content"] + "\n\n" + notice
        else:
            messages.insert(0, {"role": "system", "content": notice})

        body["files"] = passthrough
        body["messages"] = messages
        return body
