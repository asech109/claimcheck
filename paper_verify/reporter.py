from __future__ import annotations

from pathlib import Path

from .models import Claim, Status

_STATUS_ICON = {
    Status.MATCH: "✅ match",
    Status.MISMATCH: "❌ mismatch",
    Status.UNVERIFIABLE: "⚠️ unverifiable",
    Status.WAIVED: "🔕 waived",
    Status.METHOD_DRIFT: "❌ method-drift",
}


def _truth_cell(c: Claim, base: Path | None) -> str:
    if c.truth_value is None and c.truth_anchor is None:
        return "—"
    val = "" if c.truth_value is None else _flatten(str(c.truth_value))
    anchor = c.truth_anchor.render(base) if c.truth_anchor else ""
    if anchor:
        return f"`{val}` ({anchor})"
    return f"`{val}`"


def _flatten(s: str, max_len: int = 80) -> str:
    flat = s.replace("\n", " ").replace("|", "\\|").strip()
    if len(flat) > max_len:
        flat = flat[:max_len - 1] + "…"
    return flat


def _claim_cell(c: Claim, base: Path | None) -> str:
    anchor = c.tex_anchor.render(base)
    label = f" — {c.label}" if c.label else ""
    return f"`{_flatten(c.raw_value)}` ({anchor}){label}"


def render_report(
    claims: list[Claim],
    base: Path | None = None,
    diff_blocks: list[str] | None = None,
    warnings: list | None = None,
) -> str:
    """Markdown report with a summary line, the three-column table, and a
    details section for mismatches / drift / unverifiable claims."""
    counts: dict[Status, int] = {s: 0 for s in Status}
    for c in claims:
        counts[c.status] = counts.get(c.status, 0) + 1

    lines: list[str] = []
    lines.append("# paper-verify report")
    lines.append("")
    lines.append(
        f"**{len(claims)} claims** — "
        f"{counts[Status.MATCH]} match, "
        f"{counts[Status.MISMATCH] + counts[Status.METHOD_DRIFT]} mismatch, "
        f"{counts[Status.UNVERIFIABLE]} unverifiable, "
        f"{counts[Status.WAIVED]} waived"
    )
    lines.append("")
    lines.append("| Claim | Source-of-Truth | Status |")
    lines.append("|---|---|---|")
    for c in claims:
        lines.append(
            f"| {_claim_cell(c, base)} | {_truth_cell(c, base)} | {_STATUS_ICON.get(c.status, c.status.value)} |"
        )
    lines.append("")

    # Details for any non-match claim.
    detail_claims = [c for c in claims if c.status not in (Status.MATCH, Status.WAIVED)]
    if detail_claims:
        lines.append("## Details")
        lines.append("")
        for c in detail_claims:
            lines.append(f"### `{c.id}` — {c.type.value} / {c.label or '(no label)'}")
            lines.append(f"- **Status**: {_STATUS_ICON.get(c.status, c.status.value)}")
            lines.append(f"- **Paper**: `{c.raw_value}` at `{c.tex_anchor.render(base)}`")
            if c.truth_value is not None:
                lines.append(
                    f"- **Source-of-truth**: `{c.truth_value}` at "
                    f"`{c.truth_anchor.render(base) if c.truth_anchor else 'n/a'}`"
                )
            if c.detail:
                lines.append(f"- **Detail**: {c.detail}")
            if c.context_snippet:
                snippet = c.context_snippet[:240].replace("`", "ˋ")
                lines.append(f"- **Context**: `{snippet}`")
            lines.append("")

    if warnings:
        lines.append("## Warnings")
        lines.append("")
        for w in warnings:
            lines.append(f"- **`{w.claim_id}`** — {w.message}")
        lines.append("")

    if diff_blocks:
        lines.append("## Proposed fixes")
        lines.append("")
        for block in diff_blocks:
            lines.append("```diff")
            lines.append(block.rstrip())
            lines.append("```")
            lines.append("")

    return "\n".join(lines)
