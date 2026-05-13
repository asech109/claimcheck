from __future__ import annotations

import re
from pathlib import Path

from ..models import Claim, ClaimType, SourceAnchor

# Strip common LaTeX comment lines and inline comments (unescaped %).
_INLINE_COMMENT_RE = re.compile(r"(?<!\\)%.*$")

# LaTeX commands whose argument contents are references / labels / citations
# and must NOT be searched for numbers. e.g. \cite{2024,127} is a citation,
# not a claim of 127 transitions.
_REFERENCE_CMDS = (
    "cite", "citep", "citet", "citeauthor", "citeyear", "nocite",
    "ref", "autoref", "eqref", "pageref", "nameref", "cref", "Cref",
    "label", "bibitem", "url", "href",
)
_REFERENCE_CMD_RE = re.compile(
    r"\\(?:" + "|".join(_REFERENCE_CMDS) + r")\*?(?:\[[^\]]*\])?\{[^}]*\}"
)

# \input{file} or \include{file} with optional .tex extension.
_INCLUDE_RE = re.compile(r"\\(?:input|include|subfile)\{([^}]+)\}")

# Numeric literals with optional %, scientific, LaTeX-style \times 10^{-4}, etc.
# Captures the bare number form; LaTeX wrappers are normalized in _normalize_number.
_NUM_TOKEN = r"(?:\d+(?:\.\d+)?(?:\s*\\times\s*10\^\{?-?\d+\}?)?(?:[eE]-?\d+)?\s*\\?%?)"

# Hyperparam keywords -> canonical label.
_HYPERPARAM_KEYWORDS = {
    "learning rate": "learning_rate",
    "learning-rate": "learning_rate",
    r"\blr\b": "learning_rate",
    "batch size": "batch_size",
    "batch-size": "batch_size",
    "weight decay": "weight_decay",
    "dropout": "dropout",
    "hidden dim": "hidden_dim",
    "hidden size": "hidden_dim",
    "num layers": "num_layers",
    "num_layers": "num_layers",
    "epochs": "epochs",
    "warmup": "warmup_steps",
    "temperature": "temperature",
    "gamma": "gamma",
    "discount factor": "gamma",
    r"\\lambda\b": "lambda_",
    "seed": "seed",
}

# Numeric-metric keywords -> canonical label.
_NUMERIC_KEYWORDS = {
    "accuracy": "accuracy",
    "precision": "precision",
    "recall": "recall",
    "f1": "f1",
    r"f_?1\b": "f1",
    "auc": "auc",
    "rouge": "rouge",
    "bleu": "bleu",
    "perplexity": "perplexity",
    "loss": "loss",
    "reward": "reward",
    "win rate": "win_rate",
    "success rate": "success_rate",
    "mean": "mean",
    "median": "median",
    "std": "std",
}

# Count keywords + unit nouns -> canonical label.
# Only PLURAL forms — singular "1 example" is almost always rhetorical
# ("for example", "consider one example"), not a dataset count claim.
_COUNT_KEYWORDS = {
    "transitions": "transitions",
    "episodes": "episodes",
    "trajectories": "trajectories",
    "training samples": "samples",
    "training examples": "examples",
    "test samples": "samples",
    "test examples": "examples",
    "training instances": "examples",
    "data points": "samples",
    "environments": "environments",
    "tasks": "tasks",
    "parameters": "parameters",
    "tokens": "tokens",
}


def _normalize_number(raw: str) -> float | int:
    """Parse paper-style numbers: '3\\times 10^{-4}', '87.3\\%', '1e-4', '127'."""
    s = raw.strip().replace(",", "").replace(" ", "")
    s = s.replace("\\%", "").replace("%", "")
    m = re.match(r"^(-?\d+(?:\.\d+)?)\\times10\^\{?(-?\d+)\}?$", s)
    if m:
        # Compose into scientific notation as a string and let float() do
        # the conversion — avoids the 3 * 10**-4 → 0.00030000000000000003
        # artifact that chained float arithmetic would otherwise introduce.
        return float(f"{m.group(1)}e{m.group(2)}")
    try:
        if re.match(r"^-?\d+$", s):
            return int(s)
        return float(s)
    except ValueError:
        return float("nan")


def _strip_comments(text: str) -> str:
    out = []
    for line in text.splitlines(keepends=True):
        out.append(_INLINE_COMMENT_RE.sub("", line))
    return "".join(out)


def _strip_math_markers(text: str) -> str:
    """Replace single '$' math delimiters with spaces so number/unit regexes
    aren't blocked. Preserves line offsets (same-char replacement)."""
    return text.replace("$", " ")


def _strip_reference_cmds(text: str) -> str:
    """Replace contents of \\cite{}, \\ref{}, \\label{}, etc. with spaces.
    Numbers inside citation keys must not become claims."""
    def _blank(m: re.Match[str]) -> str:
        return " " * len(m.group(0))
    return _REFERENCE_CMD_RE.sub(_blank, text)


def _resolve_include_path(base_dir: Path, raw: str) -> Path | None:
    raw = raw.strip()
    candidates = [base_dir / raw]
    if not raw.endswith(".tex"):
        candidates.append(base_dir / f"{raw}.tex")
    for c in candidates:
        if c.exists():
            return c
    return None


def _build_line_index(text: str) -> list[int]:
    """Return cumulative char offsets per line; index 0 -> start of line 1."""
    offsets = [0]
    for line in text.splitlines(keepends=True):
        offsets.append(offsets[-1] + len(line))
    return offsets


def _char_to_line(line_offsets: list[int], char_pos: int) -> int:
    lo, hi = 0, len(line_offsets) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if line_offsets[mid] <= char_pos:
            lo = mid
        else:
            hi = mid - 1
    return lo + 1  # 1-indexed


def _context(text: str, start: int, end: int, window: int = 80) -> str:
    s = max(0, start - window)
    e = min(len(text), end + window)
    return text[s:e].replace("\n", " ")


def _scan_kw_value(
    text: str,
    keywords: dict[str, str],
    claim_type: ClaimType,
    tex_path: Path,
    line_offsets: list[int],
) -> list[Claim]:
    """For each keyword, scan for keyword followed (within ~80 chars) by a number."""
    claims: list[Claim] = []
    seen: set[tuple[int, str]] = set()  # (char_pos, raw_value) dedup

    for kw_pattern, label in keywords.items():
        # Build pattern: KEYWORD ... NUMBER, capturing the first number that follows.
        pat = re.compile(
            rf"({kw_pattern})\b[^.\n]{{0,80}}?({_NUM_TOKEN})",
            re.IGNORECASE,
        )
        for m in pat.finditer(text):
            raw = m.group(2).strip()
            num_start = m.start(2)
            key = (num_start, raw)
            if key in seen:
                continue
            seen.add(key)
            parsed = _normalize_number(raw)
            line = _char_to_line(line_offsets, num_start)
            ctx = _context(text, m.start(), m.end())
            claims.append(
                Claim(
                    type=claim_type,
                    raw_value=raw,
                    parsed_value=parsed,
                    tex_anchor=SourceAnchor(path=tex_path, line=line),
                    context_snippet=ctx,
                    label=label,
                )
            )
    return claims


def _scan_count_claims(
    text: str, tex_path: Path, line_offsets: list[int]
) -> list[Claim]:
    """Counts: NUMBER followed by a unit noun (within ~20 chars), integer only."""
    claims: list[Claim] = []
    seen: set[tuple[int, str]] = set()
    int_token = r"(\d{1,3}(?:,\d{3})+|\d+)"
    for noun_pat, label in _COUNT_KEYWORDS.items():
        pat = re.compile(
            rf"{int_token}\s+(?:[a-zA-Z\-]+\s+){{0,3}}({noun_pat})s?\b",
            re.IGNORECASE,
        )
        for m in pat.finditer(text):
            raw = m.group(1)
            num_start = m.start(1)
            key = (num_start, raw)
            if key in seen:
                continue
            seen.add(key)
            parsed = _normalize_number(raw)
            line = _char_to_line(line_offsets, num_start)
            ctx = _context(text, m.start(), m.end())
            claims.append(
                Claim(
                    type=ClaimType.COUNT,
                    raw_value=raw,
                    parsed_value=parsed,
                    tex_anchor=SourceAnchor(path=tex_path, line=line),
                    context_snippet=ctx,
                    label=label,
                )
            )
    return claims


_METHOD_SECTION_RE = re.compile(
    r"\\(?:section|subsection)\*?\{([^}]*(?:method|approach|algorithm|pipeline|model|architecture)[^}]*)\}",
    re.IGNORECASE,
)


def _scan_method_claims(
    text: str, tex_path: Path, line_offsets: list[int]
) -> list[Claim]:
    """Method sections: capture the whole section body as a single METHOD claim."""
    claims: list[Claim] = []
    section_starts = [(m.start(), m.group(1)) for m in _METHOD_SECTION_RE.finditer(text)]
    if not section_starts:
        return claims
    # End each method section at next \section or end-of-doc.
    next_section_re = re.compile(r"\\(?:section|subsection)\*?\{", re.IGNORECASE)
    for i, (start, heading) in enumerate(section_starts):
        next_match = next_section_re.search(text, start + 1)
        end = next_match.start() if next_match else len(text)
        body = text[start:end].strip()
        line = _char_to_line(line_offsets, start)
        claims.append(
            Claim(
                type=ClaimType.METHOD,
                raw_value=body[:200] + ("…" if len(body) > 200 else ""),
                parsed_value=body,
                tex_anchor=SourceAnchor(path=tex_path, line=line),
                context_snippet=heading,
                label=heading.lower(),
            )
        )
    return claims


def extract_claims(tex_path: Path) -> list[Claim]:
    """Scan a .tex file for numeric / hyperparam / count / method claims.

    Every emitted claim carries a SourceAnchor pointing back to the .tex line.
    Claims missing an anchor are never produced.
    """
    raw_text = Path(tex_path).read_text(encoding="utf-8", errors="replace")
    text = _strip_reference_cmds(_strip_math_markers(_strip_comments(raw_text)))
    line_offsets = _build_line_index(text)

    claims: list[Claim] = []
    claims.extend(_scan_kw_value(text, _HYPERPARAM_KEYWORDS, ClaimType.HYPERPARAM, tex_path, line_offsets))
    claims.extend(_scan_kw_value(text, _NUMERIC_KEYWORDS, ClaimType.NUMERIC, tex_path, line_offsets))
    claims.extend(_scan_count_claims(text, tex_path, line_offsets))
    claims.extend(_scan_method_claims(text, tex_path, line_offsets))

    # Dedup by (label, parsed_value, line) — same fact mentioned twice on same line
    deduped: dict[tuple, Claim] = {}
    for c in claims:
        key = (c.type.value, c.label, str(c.parsed_value), c.tex_anchor.line)
        if key not in deduped:
            deduped[key] = c
    return list(deduped.values())


def extract_claims_recursive(tex_path: Path, _seen: set[Path] | None = None) -> list[Claim]:
    """Like extract_claims but follows \\input{} and \\include{} relative to
    the parent file. Cycles are short-circuited via the _seen set so a
    misconfigured paper cannot loop forever.

    Each returned claim's tex_anchor points at the *real* file that contains
    the text — anchors stay actionable in multi-file manuscripts."""
    tex_path = tex_path.resolve()
    if _seen is None:
        _seen = set()
    if tex_path in _seen or not tex_path.exists():
        return []
    _seen.add(tex_path)

    claims: list[Claim] = list(extract_claims(tex_path))
    raw = tex_path.read_text(encoding="utf-8", errors="replace")
    base_dir = tex_path.parent
    for m in _INCLUDE_RE.finditer(_strip_comments(raw)):
        child_path = _resolve_include_path(base_dir, m.group(1))
        if child_path is not None:
            claims.extend(extract_claims_recursive(child_path, _seen=_seen))
    return claims
