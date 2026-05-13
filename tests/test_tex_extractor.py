from pathlib import Path

from paper_verify.extractors.tex_extractor import extract_claims
from paper_verify.models import ClaimType

FIXTURE = Path(__file__).parent / "fixtures" / "sample.tex"


def test_extracts_all_four_claim_types():
    claims = extract_claims(FIXTURE)
    types = {c.type for c in claims}
    assert ClaimType.NUMERIC in types
    assert ClaimType.HYPERPARAM in types
    assert ClaimType.COUNT in types
    assert ClaimType.METHOD in types


def test_every_claim_has_anchor():
    for c in extract_claims(FIXTURE):
        assert c.tex_anchor.path == FIXTURE
        assert c.tex_anchor.line > 0, f"missing anchor: {c}"


def test_accuracy_value_parsed():
    claims = extract_claims(FIXTURE)
    acc = [c for c in claims if c.label == "accuracy"]
    assert acc, "expected an accuracy claim"
    # 87.3 stored as parsed_value (percent stripped)
    assert abs(acc[0].parsed_value - 87.3) < 1e-6


def test_learning_rate_parsed_as_scientific():
    claims = extract_claims(FIXTURE)
    lr = [c for c in claims if c.label == "learning_rate"]
    assert lr, "expected a learning_rate claim"
    assert abs(lr[0].parsed_value - 3e-4) < 1e-9


def test_count_transitions():
    claims = extract_claims(FIXTURE)
    trans = [c for c in claims if c.label == "transitions"]
    assert trans
    assert int(trans[0].parsed_value) == 127
