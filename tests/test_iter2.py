"""Tests for iter2 robustness additions: multi-file \\input, citation
filtering, diff formatting, log-conflict warnings, rel-tol flag."""

from __future__ import annotations

import json
from pathlib import Path

from paper_verify.cli import build_parser
from paper_verify.diff_proposer import propose_fix
from paper_verify.extractors.tex_extractor import (
    extract_claims,
    extract_claims_recursive,
)
from paper_verify.models import Claim, ClaimType, SourceAnchor, Status
from paper_verify.verifier import VerifyContext, verify_all
from paper_verify.resolvers.log_resolver import resolve_numeric_or_count

FIX = Path(__file__).parent / "fixtures"
MULTI = FIX / "multifile"


def test_recursive_follows_input_and_include():
    claims = extract_claims_recursive(MULTI / "main.tex")
    anchor_paths = {c.tex_anchor.path.name for c in claims}
    # Top-level + intro + method should all appear.
    assert "intro.tex" in anchor_paths, anchor_paths
    assert "method.tex" in anchor_paths, anchor_paths


def test_recursive_picks_up_subfile_claims():
    claims = extract_claims_recursive(MULTI / "main.tex")
    labels = {c.label for c in claims}
    # samples + environments come from intro.tex; learning_rate from method.tex.
    assert "samples" in labels
    assert "environments" in labels
    assert "learning_rate" in labels


def test_citation_numbers_do_not_become_count_claims():
    # \cite{author2024,doe2025,127} contains '127' but is a citation, not a claim.
    claims = extract_claims(MULTI / "main.tex")
    bogus = [c for c in claims if c.parsed_value == 127]
    assert not bogus, f"citation digit leaked: {bogus}"


def test_diff_for_yaml_target_uses_clean_numeric():
    claim = Claim(
        type=ClaimType.HYPERPARAM,
        raw_value="3 \\times 10^{-4}",
        parsed_value=3e-4,
        tex_anchor=SourceAnchor(path=Path("paper.tex"), line=9),
        label="learning_rate",
        truth_value=0.0001,
        truth_anchor=SourceAnchor(path=Path("configs/train.yaml"), line=4),
        status=Status.MISMATCH,
    )
    block = propose_fix(claim)
    # Code-side diff goes into a YAML file: must show plain numeric, not LaTeX.
    assert "+ 0.0003" in block or "+ 0.0003," in block or "0.000" in block, block
    assert "3 \\times 10^{-4}" not in block.split("Option B")[1], (
        "LaTeX leaked into YAML target diff"
    )


def test_log_conflict_emits_warning(tmp_path: Path):
    # Two json files in the same logs dir disagree on the same key.
    (tmp_path / "newer.json").write_text(json.dumps({"accuracy": 0.873}))
    older = tmp_path / "older.json"
    older.write_text(json.dumps({"accuracy": 0.42}))
    # Force older file to be older by mtime.
    import os, time
    past = time.time() - 100_000
    os.utime(older, (past, past))

    claim = Claim(
        type=ClaimType.NUMERIC,
        raw_value="87.3\\%",
        parsed_value=87.3,
        tex_anchor=SourceAnchor(path=Path("p.tex"), line=1),
        label="accuracy",
    )
    ctx = VerifyContext()
    verify_all([claim], code_root=tmp_path, log_root=tmp_path, ctx=ctx)
    assert ctx.warnings, "conflict warning expected"
    assert "accuracy" in ctx.warnings[0].message
    # Newer file wins.
    assert claim.status == Status.MATCH


def test_rel_tol_flag_accepted():
    parser = build_parser()
    args = parser.parse_args(["scan", "x.tex", "--rel-tol", "0.05"])
    assert abs(args.rel_tol - 0.05) < 1e-9


def test_rel_tol_actually_widens_acceptance():
    claim = Claim(
        type=ClaimType.NUMERIC,
        raw_value="80",
        parsed_value=80.0,
        tex_anchor=SourceAnchor(path=Path("p.tex"), line=1),
        label="accuracy",
    )
    truth_dir = Path(__file__).parent / "fixtures" / "sample_logs"
    # Strict tolerance: 80 vs 0.873 (~87.3% paper convention) — not match at 1%.
    verify_all([claim], code_root=truth_dir, log_root=truth_dir, rel_tol=0.001)
    strict = claim.status
    # Re-make and rerun with very loose tolerance — should match because of
    # percent-vs-fraction reconciliation logic at rel_tol=0.10.
    claim2 = Claim(
        type=ClaimType.NUMERIC,
        raw_value="80",
        parsed_value=80.0,
        tex_anchor=SourceAnchor(path=Path("p.tex"), line=1),
        label="accuracy",
    )
    verify_all([claim2], code_root=truth_dir, log_root=truth_dir, rel_tol=0.10)
    assert strict == Status.MISMATCH
    assert claim2.status == Status.MATCH
