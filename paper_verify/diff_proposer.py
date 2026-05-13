from __future__ import annotations

from pathlib import Path

from .models import Claim, Status

_TEX_EXTS = {".tex"}
_NUMERIC_CONFIG_EXTS = {".yaml", ".yml", ".json", ".toml", ".py", ".cfg", ".ini"}


def _format_number(num: float) -> str:
    """Format a float without floating-point artifacts. Picks the shorter of
    fixed and scientific notation, mirroring how YAML/JSON would round-trip."""
    if num.is_integer() and abs(num) < 1e16:
        return str(int(num))
    # %g strips trailing zeros and avoids the 0.00030000000000000003 problem
    # caused by chained float arithmetic in _normalize_number.
    short = f"{num:.6g}"
    # Round-trip check — fall back to repr only when %g loses precision.
    try:
        if float(short) == num:
            return short
    except ValueError:
        pass
    return repr(num)


def _format_for_target(value, target_path: str) -> str:
    """Render the paper-side value in a form acceptable to the target file's
    syntax. LaTeX is fine in .tex files; numeric configs need plain numbers."""
    ext = Path(target_path).suffix.lower()
    if ext in _TEX_EXTS:
        return str(value)
    if ext in _NUMERIC_CONFIG_EXTS:
        try:
            return _format_number(float(value))
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def propose_fix(claim: Claim, base: Path | None = None) -> str:
    """Return a unified-diff-style suggestion. Two options are surfaced so the
    user picks the direction; we do NOT auto-apply anything."""
    if claim.status not in (Status.MISMATCH, Status.METHOD_DRIFT):
        return ""

    tex_anchor = claim.tex_anchor.render(base)
    truth_anchor = claim.truth_anchor.render(base) if claim.truth_anchor else "<no source>"
    truth = claim.truth_value
    paper = claim.raw_value
    paper_parsed = claim.parsed_value

    if claim.status == Status.METHOD_DRIFT:
        return (
            f"# claim {claim.id} ({claim.label or 'method'})\n"
            f"# Paper at {tex_anchor} claims algorithms missing in code.\n"
            f"# Option A — edit paper: remove unsupported algorithm mentions in the method section\n"
            f"# Option B — edit code: actually implement {claim.detail}\n"
        )

    tex_file = tex_anchor.split(":")[0]
    truth_file = truth_anchor.split(":")[0]
    paper_in_target = _format_for_target(paper_parsed, truth_file)
    truth_in_paper = _format_for_target(truth, tex_file)

    return (
        f"# claim {claim.id} ({claim.type.value}/{claim.label})\n"
        f"# Option A — edit paper at {tex_anchor}\n"
        f"--- a/{tex_file}\n"
        f"+++ b/{tex_file}\n"
        f"@@ line {claim.tex_anchor.line} @@\n"
        f"- {paper}\n"
        f"+ {truth_in_paper}\n"
        f"#\n"
        f"# Option B — edit code at {truth_anchor}\n"
        f"--- a/{truth_file}\n"
        f"+++ b/{truth_file}\n"
        f"@@ line {claim.truth_anchor.line if claim.truth_anchor else '?'} @@\n"
        f"- {truth}\n"
        f"+ {paper_in_target}\n"
    )


def propose_all(claims: list[Claim], base: Path | None = None) -> list[str]:
    blocks: list[str] = []
    for c in claims:
        block = propose_fix(c, base)
        if block:
            blocks.append(block)
    return blocks
