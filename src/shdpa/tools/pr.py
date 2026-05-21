"""PR tool. Two modes:
 - GitHub (uses `gh` CLI if available + GH_TOKEN)
 - Local bare repo (creates branch + commit, prints local "PR URL")

The local mode lets the demo run on a fresh machine without GitHub auth.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from shdpa.tools.registry import Tool, ToolResult


def _open_pr(
    repo_path: str,
    branch: str,
    title: str,
    body: str,
    files: dict[str, str],  # path -> new content
) -> ToolResult:
    if not Path(repo_path).exists():
        return ToolResult(ok=False, summary=f"no repo at {repo_path}", error="no_repo")

    def run(*args: str) -> str:
        return subprocess.check_output(
            ["git", "-C", repo_path, *args],
            stderr=subprocess.STDOUT,
            timeout=15,
        ).decode(errors="replace").strip()

    try:
        # ensure we are on main and clean
        run("checkout", "main")
        run("checkout", "-B", branch)
        for path, content in files.items():
            full = Path(repo_path) / path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content, encoding="utf-8")
            run("add", path)
        # config in case of fresh repo
        try:
            run("config", "user.email", "agent@shdpa.local")
            run("config", "user.name", "shdpa-agent")
        except subprocess.CalledProcessError:
            pass
        commit_msg = f"{title}\n\n{body}"
        run("commit", "-m", commit_msg)
        sha = run("rev-parse", "HEAD")
    except subprocess.CalledProcessError as e:
        return ToolResult(ok=False, summary=f"git failed: {e.output[:300]!r}", error="git_error")

    pr_url: str | None = None
    if shutil.which("gh") and os.getenv("GH_TOKEN"):
        try:
            run("push", "-u", "origin", branch)
            out = subprocess.check_output(
                ["gh", "pr", "create", "--title", title, "--body", body, "--head", branch],
                cwd=repo_path,
                stderr=subprocess.STDOUT,
                timeout=20,
            ).decode(errors="replace").strip()
            pr_url = out.splitlines()[-1] if out else None
        except Exception as e:  # noqa: BLE001
            pr_url = f"(gh pr failed: {e}; commit {sha[:8]})"

    if not pr_url:
        pr_url = f"local://{repo_path}#branch={branch}&sha={sha[:8]}"

    return ToolResult(
        ok=True,
        summary=f"PR opened: {pr_url}",
        data={"url": pr_url, "branch": branch, "sha": sha},
    )


TOOL = Tool(
    name="open_pr",
    description="Create a branch with the proposed file changes and 'open' a PR. "
    "Falls back to a local branch+commit if GH CLI isn't configured.",
    schema={
        "type": "object",
        "properties": {
            "repo_path": {"type": "string"},
            "branch": {"type": "string"},
            "title": {"type": "string"},
            "body": {"type": "string"},
            "files": {"type": "object"},
        },
        "required": ["repo_path", "branch", "title", "body", "files"],
    },
    fn=_open_pr,
)
