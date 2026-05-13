from __future__ import annotations

import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

from .extractors.tex_extractor import extract_claims
from .models import Claim, Status
from .reporter import render_report
from .verifier import verify_all
from .waivers import active_waivers

LOCK_FILENAME = "claims.lock.json"
LOCK_DIR = ".paper-verify"


def lock_path(repo_root: Path) -> Path:
    return repo_root / LOCK_DIR / LOCK_FILENAME


def _staged_tex_files(repo_root: Path) -> list[Path]:
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=AM"],
        cwd=repo_root, capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        return []
    files = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if line.endswith(".tex"):
            p = repo_root / line
            if p.exists():
                files.append(p)
    return files


_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def _changed_line_ranges(repo_root: Path, file_path: Path) -> list[tuple[int, int]]:
    """Return list of (start, end) inclusive line ranges in the staged version."""
    rel = file_path.relative_to(repo_root)
    out = subprocess.run(
        ["git", "diff", "--cached", "-U0", "--", str(rel)],
        cwd=repo_root, capture_output=True, text=True, check=False,
    )
    if out.returncode != 0:
        return []
    ranges: list[tuple[int, int]] = []
    for line in out.stdout.splitlines():
        m = _HUNK_RE.match(line)
        if m:
            start = int(m.group(1))
            length = int(m.group(2)) if m.group(2) else 1
            if length == 0:
                continue
            ranges.append((start, start + length - 1))
    return ranges


def _load_lock(repo_root: Path) -> dict[str, str]:
    p = lock_path(repo_root)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _save_lock(repo_root: Path, claims: list[Claim]) -> None:
    p = lock_path(repo_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {c.id: c.fingerprint() for c in claims if c.status == Status.MATCH}
    p.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _claim_in_ranges(claim: Claim, ranges: list[tuple[int, int]]) -> bool:
    if not ranges:
        return False
    line = claim.tex_anchor.line
    return any(s <= line <= e for s, e in ranges)


def run_hook(repo_root: Path, code_root: Path, log_root: Path, report_path: Path) -> int:
    """Pre-commit entry. Lenient mode: only re-verify claims that are inside
    staged hunks or whose fingerprint differs from the lock snapshot."""
    tex_files = _staged_tex_files(repo_root)
    if not tex_files:
        return 0  # No .tex changes — nothing to verify.

    lock = _load_lock(repo_root)
    waivers = active_waivers(repo_root)
    failures: list[Claim] = []
    all_changed_claims: list[Claim] = []

    for tex_file in tex_files:
        all_claims = extract_claims(tex_file)
        ranges = _changed_line_ranges(repo_root, tex_file)
        for c in all_claims:
            changed = _claim_in_ranges(c, ranges) or lock.get(c.id) != c.fingerprint()
            if not changed:
                continue
            all_changed_claims.append(c)

        # Verify only the changed subset.
        if not all_changed_claims:
            continue
        verify_all(all_changed_claims, code_root=code_root, log_root=log_root)

        for c in all_changed_claims:
            if c.id in waivers:
                c.status = Status.WAIVED
                c.detail = "waived in claims_waived.yaml"
            if c.status in (Status.MISMATCH, Status.METHOD_DRIFT):
                failures.append(c)

    if all_changed_claims:
        report = render_report(all_changed_claims, base=repo_root)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report, encoding="utf-8")

    if failures:
        sys.stderr.write(
            f"\npaper-verify: {len(failures)} unresolved claim(s). Report: {report_path}\n"
            f"Fix the code/paper, or waive with:\n"
            f"  paper-verify waive <claim_id> --reason '...'\n\n"
        )
        return 1

    # Update lock for all matched (or unchanged) claims to avoid re-verifying
    # them on the next commit.
    if all_changed_claims:
        # Merge fresh fingerprints into existing lock.
        merged = dict(lock)
        for c in all_changed_claims:
            if c.status == Status.MATCH:
                merged[c.id] = c.fingerprint()
        lp = lock_path(repo_root)
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text(json.dumps(merged, indent=2, sort_keys=True), encoding="utf-8")
    return 0


_HOOK_TEMPLATE = """#!/usr/bin/env bash
# Installed by paper-verify. Lenient mode: only verifies claims touched by
# the current commit. Bypass intentionally with `git commit --no-verify`.
set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
CODE_ROOT="${{PAPER_VERIFY_CODE_ROOT:-$REPO_ROOT}}"
LOG_ROOT="${{PAPER_VERIFY_LOG_ROOT:-$REPO_ROOT}}"

exec {python} -m paper_verify.cli hook \\
  --repo "$REPO_ROOT" \\
  --code-root "$CODE_ROOT" \\
  --logs "$LOG_ROOT"
"""


def install_hook(repo_root: Path) -> Path:
    hook_dir = repo_root / ".git" / "hooks"
    if not hook_dir.exists():
        raise FileNotFoundError(f"{hook_dir} does not exist — is this a git repository?")
    hook_path = hook_dir / "pre-commit"
    if hook_path.exists():
        hook_path.rename(hook_path.with_suffix(".pre-paper-verify.bak"))
    hook_path.write_text(_HOOK_TEMPLATE.format(python=sys.executable), encoding="utf-8")
    mode = os.stat(hook_path).st_mode
    os.chmod(hook_path, mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return hook_path
