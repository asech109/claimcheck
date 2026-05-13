from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .diff_proposer import propose_all
from .extractors.tex_extractor import extract_claims, extract_claims_recursive
from .hook import install_hook, prime_lock, run_hook
from .models import Status
from .reporter import render_report
from .verifier import VerifyContext, verify_all
from .waivers import add_waiver, load_waivers


def _check_path(p: Path, label: str) -> None:
    """Hard-fail with a friendly error if a required path is missing or empty.
    Saves the user a 'why is everything unverifiable?' round-trip."""
    if not p.exists():
        sys.stderr.write(
            f"error: {label} '{p}' does not exist.\n"
            f"  If you have not run any experiments yet, point --logs at an empty "
            f"directory and the tool will mark numeric claims as 'unverifiable' "
            f"rather than fail.\n"
        )
        sys.exit(2)
    if p.is_dir() and not any(p.iterdir()):
        sys.stderr.write(
            f"warning: {label} '{p}' is empty — all numeric/hyperparam/count "
            f"claims will resolve as 'unverifiable'.\n"
        )


def _scan_pipeline(args: argparse.Namespace) -> tuple[list, VerifyContext]:
    tex_path = Path(args.tex).resolve()
    code_root = Path(args.code_root).resolve()
    log_root = Path(args.logs).resolve()
    if not tex_path.exists():
        sys.stderr.write(f"error: {tex_path} not found\n")
        sys.exit(2)
    _check_path(code_root, "--code-root")
    _check_path(log_root, "--logs")

    extractor = extract_claims_recursive if args.follow_includes else extract_claims
    claims = extractor(tex_path)
    if not claims:
        sys.stderr.write(f"warning: no claims extracted from {tex_path}\n")

    ctx = VerifyContext()
    verify_all(claims, code_root=code_root, log_root=log_root,
               rel_tol=args.rel_tol, ctx=ctx)
    return claims, ctx


def cmd_scan(args: argparse.Namespace) -> int:
    claims, ctx = _scan_pipeline(args)

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
    if args.list:
        waivers = load_waivers(repo)
        if not waivers:
            print("no waivers")
            return 0
        import datetime as _dt
        today = _dt.date.today()
        for w in sorted(waivers.values(), key=lambda x: x.expires):
            days_left = (w.expires - today).days
            tag = "active" if days_left >= 0 else "EXPIRED"
            print(f"  {w.claim_id}  [{tag}, {days_left:+d}d]  {w.reason}")
        return 0
    if not args.claim_id or not args.reason:
        sys.stderr.write("error: claim_id and --reason are required unless --list is given\n")
        return 2
    w = add_waiver(repo, claim_id=args.claim_id, reason=args.reason, ttl_days=args.ttl)
    print(f"waived {w.claim_id} until {w.expires.isoformat()}: {w.reason}")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    """CI-friendly: no file output. Exit 0 if clean, 1 if drift, 2 on error."""
    claims, ctx = _scan_pipeline(args)
    counts = {s: 0 for s in Status}
    for c in claims:
        counts[c.status] = counts.get(c.status, 0) + 1
    fail = counts.get(Status.MISMATCH, 0) + counts.get(Status.METHOD_DRIFT, 0)
    print(
        f"{len(claims)} claims | "
        f"{counts.get(Status.MATCH, 0)} match, "
        f"{fail} drift, "
        f"{counts.get(Status.UNVERIFIABLE, 0)} unverifiable, "
        f"{counts.get(Status.WAIVED, 0)} waived"
    )
    if ctx.warnings:
        print(f"warnings: {len(ctx.warnings)}")
    return 1 if fail else 0


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
    p = argparse.ArgumentParser(prog="claimcheck")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
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

    w = sub.add_parser("waive", help="Add or list waivers for specific claim ids.")
    w.add_argument("claim_id", nargs="?", help="Claim id from the report")
    w.add_argument("--reason", help="Why this claim is waived (required for adding)")
    w.add_argument("--ttl", type=int, default=30, help="Days until waiver expires (default 30)")
    w.add_argument("--repo", default=".", help="Repo root that holds .paper-verify/")
    w.add_argument("--list", action="store_true", help="List active waivers and exit")
    w.set_defaults(func=cmd_waive)

    st = sub.add_parser("status", help="Quick exit-code check; no report file is written.")
    st.add_argument("tex", help="Path to the .tex file")
    st.add_argument("--code-root", default=".")
    st.add_argument("--logs", default=".")
    st.add_argument("--rel-tol", type=float, default=1e-2)
    st.add_argument("--follow-includes", action="store_true", default=True)
    st.add_argument("--no-follow-includes", dest="follow_includes", action="store_false")
    st.set_defaults(func=cmd_status)

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
