from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .diff_proposer import propose_all
from .extractors.tex_extractor import extract_claims, extract_claims_recursive
from .hook import install_hook, prime_lock, run_hook
from .models import Status
from .reporter import render_report
from .verifier import VerifyContext, verify_all
from .waivers import add_waiver, load_waivers


def cmd_scan(args: argparse.Namespace) -> int:
    tex_path = Path(args.tex).resolve()
    code_root = Path(args.code_root).resolve()
    log_root = Path(args.logs).resolve()
    if not tex_path.exists():
        print(f"error: {tex_path} not found", file=sys.stderr)
        return 2

    extractor = extract_claims_recursive if args.follow_includes else extract_claims
    claims = extractor(tex_path)
    if not claims:
        print(f"warning: no claims extracted from {tex_path}", file=sys.stderr)

    ctx = VerifyContext()
    verify_all(claims, code_root=code_root, log_root=log_root, rel_tol=args.rel_tol, ctx=ctx)

    # Apply active waivers if a repo root is implied.
    if args.repo:
        waivers = {cid for cid, w in load_waivers(Path(args.repo)).items() if w.is_active()}
        for c in claims:
            if c.id in waivers:
                c.status = Status.WAIVED
                c.detail = "waived in claims_waived.yaml"

    diffs = propose_all(claims, base=Path.cwd())
    report = render_report(claims, base=Path.cwd(), diff_blocks=diffs, warnings=ctx.warnings)
    out = Path(args.report).resolve()
    out.write_text(report, encoding="utf-8")
    print(f"report written: {out}")
    if ctx.warnings:
        print(f"  (with {len(ctx.warnings)} warning(s) — see report)")

    mismatches = sum(
        1 for c in claims if c.status in (Status.MISMATCH, Status.METHOD_DRIFT)
    )
    return 1 if mismatches else 0


def cmd_waive(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    w = add_waiver(repo, claim_id=args.claim_id, reason=args.reason, ttl_days=args.ttl)
    print(f"waived {w.claim_id} until {w.expires.isoformat()}: {w.reason}")
    return 0


def cmd_install_hook(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    hook_path = install_hook(repo)
    print(f"installed pre-commit hook: {hook_path}")
    if args.prime:
        code = Path(args.code_root or repo).resolve()
        logs = Path(args.logs or repo).resolve()
        locked, skipped = prime_lock(repo, code, logs)
        print(f"primed lock: {locked} matches recorded, {skipped} non-match claims left for review")
        if skipped:
            print("  → run `claimcheck scan ...` to see which claims still need a fix or waiver")
    return 0


def cmd_hook(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    code = Path(args.code_root).resolve()
    logs = Path(args.logs).resolve()
    report = repo / ".paper-verify" / "last-report.md"
    return run_hook(repo, code, logs, report)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="paper-verify")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="Scan a .tex file and write a verification report.")
    s.add_argument("tex", help="Path to the .tex file")
    s.add_argument("--code-root", default=".", help="Root of code/configs to search")
    s.add_argument("--logs", default=".", help="Root of logs (json/jsonl/csv) to search")
    s.add_argument("--report", default="paper-verify-report.md", help="Output markdown path")
    s.add_argument("--repo", default=None, help="Repo root for waiver lookup (optional)")
    s.add_argument("--rel-tol", type=float, default=1e-2,
                   help="Relative tolerance for numeric claims (default 0.01 = 1%%). "
                        "Counts always require exact equality regardless of this flag.")
    s.add_argument("--follow-includes", action="store_true", default=True,
                   help="Recursively follow \\input{} / \\include{} (default: on)")
    s.add_argument("--no-follow-includes", dest="follow_includes", action="store_false",
                   help="Disable include-following; scan only the top-level .tex")
    s.set_defaults(func=cmd_scan)

    w = sub.add_parser("waive", help="Add an active waiver for a specific claim id.")
    w.add_argument("claim_id")
    w.add_argument("--reason", required=True)
    w.add_argument("--ttl", type=int, default=30, help="Days until waiver expires (default 30)")
    w.add_argument("--repo", default=".", help="Repo root that holds .paper-verify/")
    w.set_defaults(func=cmd_waive)

    ih = sub.add_parser("install-hook", help="Install a pre-commit hook in a git repo.")
    ih.add_argument("repo", help="Path to a git repository")
    ih.add_argument("--prime", action="store_true",
                    help="After install, scan the repo and record current matches in the lock "
                         "so the hook only flags future drift.")
    ih.add_argument("--code-root", default=None, help="Used with --prime (default: repo root)")
    ih.add_argument("--logs", default=None, help="Used with --prime (default: repo root)")
    ih.set_defaults(func=cmd_install_hook)

    h = sub.add_parser("hook", help="Run as a git pre-commit hook (internal).")
    h.add_argument("--repo", required=True)
    h.add_argument("--code-root", required=True)
    h.add_argument("--logs", required=True)
    h.set_defaults(func=cmd_hook)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
