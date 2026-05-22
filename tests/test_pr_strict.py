import os
import shutil
import subprocess
from pathlib import Path
import pytest
from shdpa.tools.pr import _open_pr


@pytest.fixture
def temp_git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@shdpa.local"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "test-agent"], cwd=repo, check=True)
    (repo / "file.txt").write_text("initial content", encoding="utf-8")
    subprocess.run(["git", "add", "file.txt"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "initial commit"], cwd=repo, check=True)
    return repo


def test_pr_strict_missing_token(monkeypatch, temp_git_repo):
    monkeypatch.setenv("SHDPA_STRICT_PR", "1")
    monkeypatch.setenv("GH_TOKEN", "")
    
    # Mock secrets get_secret to return None to bypass any cached secret
    with mock_get_secret(None):
        r = _open_pr(
            repo_path=str(temp_git_repo),
            branch="shdpa/test-strict-token",
            title="test title",
            body="test body",
            files={"file.txt": "new content"},
        )
    assert not r.ok
    assert r.error == "missing_gh_token"


def test_pr_strict_missing_gh_cli(monkeypatch, temp_git_repo):
    monkeypatch.setenv("SHDPA_STRICT_PR", "1")
    monkeypatch.setenv("GH_TOKEN", "mock-token")
    
    # Mock shutil.which to simulate gh not installed
    original_which = shutil.which
    def mock_which(cmd):
        if cmd == "gh":
            return None
        return original_which(cmd)
        
    monkeypatch.setattr(shutil, "which", mock_which)
    
    with mock_get_secret("mock-token"):
        r = _open_pr(
            repo_path=str(temp_git_repo),
            branch="shdpa/test-strict-cli",
            title="test title",
            body="test body",
            files={"file.txt": "new content"},
        )
    assert not r.ok
    assert r.error == "missing_gh_cli"


def test_pr_non_strict_fallback(monkeypatch, temp_git_repo):
    monkeypatch.setenv("SHDPA_STRICT_PR", "0")
    monkeypatch.setenv("GH_TOKEN", "")
    
    with mock_get_secret(None):
        r = _open_pr(
            repo_path=str(temp_git_repo),
            branch="shdpa/test-non-strict-fallback",
            title="test title",
            body="test body",
            files={"file.txt": "new content"},
        )
    assert r.ok
    assert r.data["url"].startswith("local://")


class mock_get_secret:
    def __init__(self, value):
        self.value = value
        
    def __enter__(self):
        from shdpa.middleware import secrets
        self.orig = secrets.get_secret
        secrets.get_secret = lambda k: self.value
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        from shdpa.middleware import secrets
        secrets.get_secret = self.orig
