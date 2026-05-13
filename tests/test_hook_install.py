import os
import subprocess
from pathlib import Path

from paper_verify.hook import install_hook


def _init_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "fake-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return repo


def test_install_hook_writes_executable(tmp_path: Path):
    repo = _init_repo(tmp_path)
    hook = install_hook(repo)
    assert hook.exists()
    assert hook.name == "pre-commit"
    # Executable bit set.
    assert os.stat(hook).st_mode & 0o111


def test_install_hook_backs_up_existing(tmp_path: Path):
    repo = _init_repo(tmp_path)
    existing = repo / ".git" / "hooks" / "pre-commit"
    existing.write_text("# old hook")
    install_hook(repo)
    # Path("pre-commit").with_suffix(".pre-paper-verify.bak") -> "pre-commit.pre-paper-verify.bak"
    backup = repo / ".git" / "hooks" / "pre-commit.pre-paper-verify.bak"
    assert backup.exists()
    assert backup.read_text() == "# old hook"
