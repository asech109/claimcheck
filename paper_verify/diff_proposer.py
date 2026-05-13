from __future__ import annotations

from pathlib import Path

from .models import Claim, Status


def propose_fix(claim: Claim, base: Path | None = None) -> str:
    """Return a unified-diff-style suggestion. Two options are surfaced so the
    user picks the direction; we do NOT auto-apply anything."""
    if claim.status not in (Status.MISMATCH, Status.METHOD_DRIFT):
        return ""

    tex_anchor = claim.tex_anchor.render(base)
    truth_anchor = claim.truth_anchor.render(base) if claim.truth_anchor else "<no source>"
    truth = claim.truth_value
    paper = claim.raw_value

    if claim.status == Status.METHOD_DRIFT:
        return (
            f"# claim {claim.id} ({claim.label or 'method'})\n"
            f"# Paper at {tex_anchor} claims algorithms missing in code.\n"
            f"# Option A — edit paper: remove unsupported algorithm mentions in the method section\n"
            f"# Option B — edit code: actually implement {claim.detail}\n"
        )

    return (
        f"# claim {claim.id} ({claim.type.value}/{claim.label})\n"
        f"# Option A — edit paper at {tex_anchor}\n"
        f"--- a/{tex_anchor.split(':')[0]}\n"
        f"+++ b/{tex_anchor.split(':')[0]}\n"
        f"@@ line {claim.tex_anchor.line} @@\n"
        f"- {paper}\n"
        f"+ {truth}\n"
        f"#\n"
        f"# Option B — edit code at {truth_anchor}\n"
        f"--- a/{truth_anchor.split(':')[0]}\n"
        f"+++ b/{truth_anchor.split(':')[0]}\n"
        f"@@ line {claim.truth_anchor.line if claim.truth_anchor else '?'} @@\n"
        f"- {truth}\n"
        f"+ {paper}\n"
    )


def propose_all(claims: list[Claim], base: Path | None = None) -> list[str]:
    blocks: list[str] = []
    for c in claims:
        block = propose_fix(c, base)
        if block:
            blocks.append(block)
    return blocks
