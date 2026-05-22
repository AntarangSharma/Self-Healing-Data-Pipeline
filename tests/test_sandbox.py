import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from shdpa.middleware.sandbox import validate_patches


def test_sandbox_python_compile_fallback(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    # Create an initial python file
    py_file = repo / "main.py"
    py_file.write_text("print('hello')", encoding="utf-8")

    # We patch the file to have a syntax error
    files = {"main.py": "print('hello'"}  # missing paren

    success, msg = validate_patches(str(repo), files)
    assert success is False
    assert "SyntaxError" in msg or "code" in msg or "failed" in msg

    # Verify original file content is restored
    assert py_file.read_text(encoding="utf-8") == "print('hello')"


def test_sandbox_custom_cmd_success(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    target = repo / "hello.txt"
    target.write_text("original", encoding="utf-8")

    files = {"hello.txt": "new content"}

    with patch.dict(os.environ, {"SHDPA_SANDBOX_CMD": "echo 'all good'"}):
        success, msg = validate_patches(str(repo), files)
        assert success is True
        assert "validation passed" in msg or "passed" in msg

        # Verify clean up restored the original
        assert target.read_text(encoding="utf-8") == "original"


def test_sandbox_dbt_compile_detection(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()

    dbt_proj = repo / "dbt_project.yml"
    dbt_proj.write_text("name: test", encoding="utf-8")

    files = {"models/schema.yml": "version: 2"}

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = subprocess.CompletedProcess(
            args=["dbt compile"],
            returncode=0,
            stdout="Success",
            stderr="",
        )

        success, msg = validate_patches(str(repo), files)
        assert success is True

        # Check command run in subprocess.run
        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "dbt compile" in cmd
        assert str(repo) in cmd
