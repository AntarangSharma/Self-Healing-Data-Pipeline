"""Tool registry. Each tool: name, JSON schema, callable.

The agent only sees tools registered here. Calls are wrapped to record
latency, errors, and a short result summary in the Incident.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from shdpa.models import Incident, ToolCall


@dataclass
class ToolResult:
    ok: bool
    summary: str
    data: Any = None
    error: str | None = None


@dataclass
class Tool:
    name: str
    description: str
    schema: dict[str, Any]
    fn: Callable[..., ToolResult]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def names(self) -> list[str]:
        return list(self._tools.keys())

    def describe(self) -> str:
        lines = []
        for t in self._tools.values():
            lines.append(f"- {t.name}: {t.description}")
        return "\n".join(lines)

    def call(self, name: str, incident: Incident, **kwargs: Any) -> ToolResult:
        if name not in self._tools:
            return ToolResult(ok=False, summary=f"unknown tool {name}", error="unknown_tool")
        t0 = time.time()
        try:
            result = self._tools[name].fn(**kwargs)
            err = None
        except Exception as e:  # noqa: BLE001
            result = ToolResult(ok=False, summary=f"exception: {e}", error=str(e))
            err = str(e)
        latency_ms = int((time.time() - t0) * 1000)
        incident.tool_calls.append(
            ToolCall(
                name=name,
                args=kwargs,
                result_summary=(result.summary or "")[:2000],
                latency_ms=latency_ms,
                error=err,
            )
        )
        return result
