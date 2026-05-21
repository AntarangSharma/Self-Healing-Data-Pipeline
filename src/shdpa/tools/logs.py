"""Log fetch tool. Reads from incident.log_text or a file path."""
from __future__ import annotations

from pathlib import Path

from shdpa.tools.registry import Tool, ToolResult


def _get_logs(log_text: str = "", log_path: str = "", tail: int = 200) -> ToolResult:
    if log_path:
        try:
            log_text = Path(log_path).read_text(encoding="utf-8", errors="replace")
        except Exception as e:  # noqa: BLE001
            return ToolResult(ok=False, summary=f"could not read {log_path}: {e}", error=str(e))
    if not log_text:
        return ToolResult(ok=False, summary="no log content available", error="empty")
    lines = log_text.splitlines()
    tail_lines = lines[-tail:] if len(lines) > tail else lines
    return ToolResult(
        ok=True,
        summary=f"{len(tail_lines)} log lines (of {len(lines)} total)",
        data="\n".join(tail_lines),
    )


TOOL = Tool(
    name="get_task_logs",
    description="Fetch the task log (last N lines).",
    schema={
        "type": "object",
        "properties": {
            "log_text": {"type": "string"},
            "log_path": {"type": "string"},
            "tail": {"type": "integer", "default": 200},
        },
    },
    fn=_get_logs,
)
