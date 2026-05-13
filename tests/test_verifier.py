from pathlib import Path

from paper_verify.extractors.tex_extractor import extract_claims
from paper_verify.models import ClaimType, Status
from paper_verify.verifier import verify_all

FIX = Path(__file__).parent / "fixtures"


def test_end_to_end_statuses():
    claims = extract_claims(FIX / "sample.tex")
    verify_all(claims, code_root=FIX / "sample_configs", log_root=FIX / "sample_logs")

    statuses = {(c.type, c.label): c.status for c in claims}

    # accuracy 87.3% in paper == 0.873 in log -> match
    assert statuses.get((ClaimType.NUMERIC, "accuracy")) == Status.MATCH
    # loss 0.42 == 0.42 -> match
    assert statuses.get((ClaimType.NUMERIC, "loss")) == Status.MATCH
    # lr paper=3e-4 vs config=1e-4 -> mismatch
    assert statuses.get((ClaimType.HYPERPARAM, "learning_rate")) == Status.MISMATCH
    # batch_size 64 == 64 -> match
    assert statuses.get((ClaimType.HYPERPARAM, "batch_size")) == Status.MATCH
    # transitions = 127, but the log doesn't have a "transitions" key -> unverifiable
    assert statuses.get((ClaimType.COUNT, "transitions")) == Status.UNVERIFIABLE
    # method section mentions PPO + GAE; code has PPO only -> drift
    method_statuses = [c.status for c in claims if c.type == ClaimType.METHOD]
    assert Status.METHOD_DRIFT in method_statuses


def test_truth_anchors_present_for_matches():
    claims = extract_claims(FIX / "sample.tex")
    verify_all(claims, code_root=FIX / "sample_configs", log_root=FIX / "sample_logs")
    for c in claims:
        if c.status == Status.MATCH and c.type != ClaimType.METHOD:
            assert c.truth_anchor is not None
            assert c.truth_anchor.line > 0
