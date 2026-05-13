from pathlib import Path

from paper_verify.models import Claim, ClaimType, SourceAnchor
from paper_verify.resolvers.config_resolver import resolve_hyperparam
from paper_verify.resolvers.log_resolver import resolve_numeric_or_count

FIX = Path(__file__).parent / "fixtures"


def _make_claim(claim_type: ClaimType, label: str) -> Claim:
    return Claim(
        type=claim_type,
        raw_value="0",
        parsed_value=0,
        tex_anchor=SourceAnchor(path=FIX / "sample.tex", line=1),
        label=label,
    )


def test_log_resolver_finds_accuracy():
    c = _make_claim(ClaimType.NUMERIC, "accuracy")
    result = resolve_numeric_or_count(c, FIX / "sample_logs")
    assert result is not None
    val, anchor = result
    assert abs(val - 0.873) < 1e-9
    assert anchor.path.name == "metrics.json"


def test_log_resolver_returns_none_for_unknown():
    c = _make_claim(ClaimType.NUMERIC, "nonexistent_metric")
    assert resolve_numeric_or_count(c, FIX / "sample_logs") is None


def test_config_resolver_finds_learning_rate():
    c = _make_claim(ClaimType.HYPERPARAM, "learning_rate")
    result = resolve_hyperparam(c, FIX / "sample_configs")
    assert result is not None
    val, anchor = result
    assert abs(float(val) - 1e-4) < 1e-9
    assert anchor.path.name == "train.yaml"
