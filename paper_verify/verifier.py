from __future__ import annotations

import math
from pathlib import Path

from .extractors.method_parser import diff_fingerprints, parse_method_description
from .models import Claim, ClaimType, SourceAnchor, Status
from .resolvers.code_resolver import build_code_fingerprint
from .resolvers.config_resolver import resolve_hyperparam
from .resolvers.log_resolver import resolve_numeric_or_count


def _numbers_match(paper: float, code: float, rel_tol: float = 1e-2) -> bool:
    """Relative-tolerance comparison (default 1%). Percent-vs-fraction
    reconciliation is only attempted when the paper value plausibly looks
    like a percentage (>1) and code value like a fraction (<=1), to avoid
    spurious matches between small hyperparams like 3e-4 vs 1e-4."""
    if math.isnan(paper) or math.isnan(code):
        return False
    if math.isclose(paper, code, rel_tol=rel_tol):
        return True
    if 1.0 < paper <= 100.0 and 0.0 <= code <= 1.0:
        if math.isclose(paper / 100.0, code, rel_tol=rel_tol):
            return True
    if 1.0 < code <= 100.0 and 0.0 <= paper <= 1.0:
        if math.isclose(paper, code / 100.0, rel_tol=rel_tol):
            return True
    return False


def verify_claim(
    claim: Claim,
    code_root: Path,
    log_root: Path,
    code_fp_cache: tuple | None = None,
) -> Claim:
    if claim.type in (ClaimType.NUMERIC, ClaimType.COUNT):
        result = resolve_numeric_or_count(claim, log_root)
        if result is None:
            claim.status = Status.UNVERIFIABLE
            claim.detail = (
                f"no log entry found for label '{claim.label}' under {log_root}; "
                f"run experiment and ensure metrics are written to a JSON/CSV under --logs"
            )
            return claim
        truth, anchor = result
        claim.truth_value = truth
        claim.truth_anchor = anchor
        if isinstance(truth, (int, float)) and isinstance(claim.parsed_value, (int, float)):
            if _numbers_match(float(claim.parsed_value), float(truth)):
                claim.status = Status.MATCH
            else:
                claim.status = Status.MISMATCH
                claim.detail = f"paper={claim.parsed_value} truth={truth}"
        else:
            claim.status = Status.UNVERIFIABLE
            claim.detail = f"truth value has non-numeric type: {type(truth).__name__}"
        return claim

    if claim.type == ClaimType.HYPERPARAM:
        result = resolve_hyperparam(claim, code_root)
        if result is None:
            claim.status = Status.UNVERIFIABLE
            claim.detail = f"no config/code constant found for '{claim.label}' under {code_root}"
            return claim
        truth, anchor = result
        claim.truth_value = truth
        claim.truth_anchor = anchor
        if isinstance(truth, (int, float)) and isinstance(claim.parsed_value, (int, float)):
            if _numbers_match(float(claim.parsed_value), float(truth)):
                claim.status = Status.MATCH
            else:
                claim.status = Status.MISMATCH
                claim.detail = f"paper={claim.parsed_value} code={truth}"
        else:
            if str(truth).strip() == str(claim.parsed_value).strip():
                claim.status = Status.MATCH
            else:
                claim.status = Status.MISMATCH
                claim.detail = f"paper={claim.parsed_value!r} code={truth!r}"
        return claim

    if claim.type == ClaimType.METHOD:
        paper_fp = parse_method_description(str(claim.parsed_value))
        if code_fp_cache is None:
            code_fp, anchors = build_code_fingerprint(code_root)
        else:
            code_fp, anchors = code_fp_cache
        # Drift only if the paper named algorithms; otherwise unverifiable.
        if not paper_fp.algorithms and not paper_fp.architecture:
            claim.status = Status.UNVERIFIABLE
            claim.detail = "no recognizable algorithm/architecture tokens in section text"
            return claim
        if not code_fp.algorithms and not code_fp.architecture:
            claim.status = Status.UNVERIFIABLE
            claim.detail = f"no algorithm tokens found in code under {code_root}"
            return claim
        diff = diff_fingerprints(paper_fp, code_fp)
        missing = diff["algorithms_in_paper_not_code"]
        if missing:
            claim.status = Status.METHOD_DRIFT
            claim.detail = (
                f"paper mentions {missing} but no such token found in code"
            )
            # Anchor to the first algorithm we *did* match, for traceability.
            for algo in paper_fp.algorithms:
                if algo in anchors:
                    claim.truth_anchor = anchors[algo]
                    break
        else:
            claim.status = Status.MATCH
            for algo in paper_fp.algorithms:
                if algo in anchors:
                    claim.truth_anchor = anchors[algo]
                    claim.truth_value = f"algorithms confirmed: {sorted(paper_fp.algorithms)}"
                    break
        return claim

    return claim


def verify_all(claims: list[Claim], code_root: Path, log_root: Path) -> list[Claim]:
    code_fp_cache = build_code_fingerprint(code_root)
    for c in claims:
        verify_claim(c, code_root, log_root, code_fp_cache=code_fp_cache)
    return claims
