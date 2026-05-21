"""Git diff tool. Returns recent diff for a file in the incident's repo snapshot."""
from __future__ import annotations

import subprocess
from pathlib import Path

from shdpa.tools.registry import Tool, ToolResult


def _git_diff(repo_path: str, file_path: str = "", since: str = "HEAD~1") -> ToolResult:
    if not repo_path or not Path(repo_path).exists():
        return ToolResult(ok=False, summary=f"repo path missing: {repo_path}", error="no_repo")
    cmd = ["git", "-C", repo_path, "diff", since]
    if file_path:
        cmd += ["--", file_path]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT, timeout=10).decode(
            errors="replace"
        )
    except subprocess.CalledProcessError as e:
        return ToolResult(ok=False, summary=f"git failed: {e.output[:200]!r}", error="git_error")
    except FileNotFoundError:
        return ToolResult(ok=False, summary="git not installed", error="no_git")
    return ToolResult(
        ok=True,
        summary=f"diff length {len(out)} bytes",
        data=out,
    )


TOOL = Tool(
    name="get_recent_diff",
    description="Return git diff of the repo since `since` (default HEAD~1).",
    schema={
        "type": "object",
        "properties": {
            "repo_path": {"type": "string"},
            "file_path": {"type": "string"},
            "since": {"type": "string", "default": "HEAD~1"},
        },
        "required": ["repo_path"],
    },
    fn=_git_diff,
)
