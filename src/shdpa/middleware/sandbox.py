"""Patch-validation sandbox middleware.

Applies proposed file changes to the repository path, runs validation/compilation
commands (such as `dbt compile`), and ensures the repository is restored back
to its original clean state afterwards.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import structlog

log = structlog.get_logger()


def validate_patches(repo_path: str, files: dict[str, str]) -> tuple[bool, str]:
    """Temporarily apply patches to repo_path, run a validation command, and restore.

    Returns:
        (success_bool, message_str)
    """
    repo = Path(repo_path)
    if not repo.exists():
        return True, "Repository path does not exist; skipping sandbox validation."

    # 1. Back up existing files
    backups: dict[Path, str | None] = {}
    for rel_path in files:
        target = repo / rel_path
        if target.exists():
            try:
                backups[target] = target.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                log.warning("sandbox.backup_failed", path=str(target), error=repr(e))
                backups[target] = None
        else:
            backups[target] = None

    try:
        # 2. Write proposed file contents to the repository
        for rel_path, content in files.items():
            target = repo / rel_path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        # 3. Determine the validation command to run
        cmd = os.getenv("SHDPA_SANDBOX_CMD")
        if not cmd:
            # Auto-detect dbt project first
            dbt_projects = list(repo.glob("**/dbt_project.yml"))
            if dbt_projects:
                dbt_dir = dbt_projects[0].parent
                cmd = f"dbt compile --project-dir {dbt_dir}"
            else:
                # Fallback to python syntax check if there are changed python files
                py_files = [f for f in files if f.endswith(".py")]
                if py_files:
                    # Target full paths in validation command
                    full_paths = [str(repo / f) for f in py_files]
                    cmd = f"python -m py_compile {' '.join(full_paths)}"
                else:
                    cmd = "echo 'No validation command configured, auto-passing'"

        log.info("sandbox.running_validation", command=cmd)

        # 4. Run the validation command
        res = subprocess.run(
            cmd,
            shell=True,
            cwd=str(repo),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=30,
        )

        if res.returncode != 0:
            err_msg = res.stderr or res.stdout or "(no output)"
            log.warning("sandbox.validation_failed", command=cmd, code=res.returncode, error=err_msg)
            return False, f"Sandbox validation command '{cmd}' failed with code {res.returncode}. Output:\n{err_msg}"

        log.info("sandbox.validation_passed", command=cmd)
        return True, "Sandbox validation passed."

    except Exception as e:
        log.error("sandbox.unexpected_error", error=str(e))
        return False, f"Sandbox validation encountered an error: {e}"

    finally:
        # 5. Restore backed-up files and delete newly created files
        for target, original_content in backups.items():
            try:
                if original_content is None:
                    if target.exists():
                        target.unlink()
                else:
                    target.write_text(original_content, encoding="utf-8")
            except Exception as e:
                log.warning("sandbox.restore_failed", path=str(target), error=repr(e))
