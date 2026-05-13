"""End-to-end pre-commit hook test using a real git repo.

Skipped if git is unavailable. Verifies:
  * staging only a typo => commit succeeds
  * introducing a numeric mismatch => commit blocked
  * waiver issued => commit succeeds again
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from paper_verify.cli import build_parser
from paper_verify.hook import install_hook, prime_lock
from paper_verify.waivers import add_waiver

FIX = Path(__file__).parent / "fixtures"


def _git_available() -> bool:
    return shutil.which("git") is not None


pytestmark = pytest.mark.skipif(not _git_available(), reason="git binary not available")


def _git(repo: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    real_env = os.environ.copy()
    real_env.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@x",
                     "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@x"})
    if env:
        real_env.update(env)
    return subprocess.run(["git", *args], cwd=repo, env=real_env,
                          capture_output=True, text=True, check=False)


def _setup_repo(tmp_path: Path, prime: bool = True) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    shutil.copy(FIX / "sample.tex", repo / "paper.tex")
    shutil.copytree(FIX / "sample_configs", repo / "configs")
    shutil.copytree(FIX / "sample_logs", repo / "logs")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "initial")
    install_hook(repo)
    if prime:
        # Pre-existing fixture has known mismatches; waive them so the test
        # focuses on NEW drift introduced by edits, not historical baseline.
        from paper_verify.extractors.tex_extractor import extract_claims
        from paper_verify.models import Status
        from paper_verify.verifier import verify_all
        claims = extract_claims(repo / "paper.tex")
        verify_all(claims, code_root=repo / "configs", log_root=repo / "logs")
        for c in claims:
            if c.status != Status.MATCH:
                add_waiver(repo, claim_id=c.id, reason="baseline", ttl_days=30)
        prime_lock(repo, repo / "configs", repo / "logs")
    return repo


def _commit_env(repo: Path) -> dict:
    return {
        "PAPER_VERIFY_CODE_ROOT": str(repo / "configs"),
        "PAPER_VERIFY_LOG_ROOT": str(repo / "logs"),
    }


def test_hook_blocks_commit_with_mismatch(tmp_path: Path):
    repo = _setup_repo(tmp_path)
    paper = repo / "paper.tex"
    paper.write_text(paper.read_text().replace("87.3", "99.9"))
    _git(repo, "add", "paper.tex")
    result = _git(repo, "commit", "-m", "introduce mismatch", env=_commit_env(repo))
    assert result.returncode != 0, f"hook should have blocked; stderr={result.stderr}"
    assert "paper-verify" in result.stderr
    # Report file should have been written.
    assert (repo / ".paper-verify" / "last-report.md").exists()


def test_hook_lets_through_unrelated_edits(tmp_path: Path):
    repo = _setup_repo(tmp_path)
    paper = repo / "paper.tex"
    # Append a harmless prose line. It contains no number/keyword that
    # would create a claim, so the hook has nothing to verify.
    paper.write_text(paper.read_text() + "\n% benign comment line\n")
    _git(repo, "add", "paper.tex")
    result = _git(repo, "commit", "-m", "typo fix", env=_commit_env(repo))
    assert result.returncode == 0, f"hook should have passed; stderr={result.stderr}"


def test_waiver_bypasses_hook(tmp_path: Path):
    repo = _setup_repo(tmp_path)
    paper = repo / "paper.tex"
    paper.write_text(paper.read_text().replace("87.3", "99.9"))
    _git(repo, "add", "paper.tex")
    blocked = _git(repo, "commit", "-m", "first attempt", env=_commit_env(repo))
    assert blocked.returncode != 0
    # Extract the offending claim id from the report.
    report = (repo / ".paper-verify" / "last-report.md").read_text()
    import re
    ids = re.findall(r"### `([a-f0-9]{12})`", report)
    assert ids, "expected at least one claim id in report"
    for cid in ids:
        add_waiver(repo, claim_id=cid, reason="test", ttl_days=1)
    passed = _git(repo, "commit", "-m", "second attempt", env=_commit_env(repo))
    assert passed.returncode == 0, f"waivered commit should have passed; stderr={passed.stderr}"


def test_cli_parser_smoke():
    parser = build_parser()
    args = parser.parse_args(["scan", "x.tex"])
    assert args.cmd == "scan"
    assert args.tex == "x.tex"
